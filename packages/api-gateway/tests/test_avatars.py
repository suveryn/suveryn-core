"""Avatars (docs/design/avatars.md): a person's picture, re-encoded on the server, served to
colleagues with an ETag, removable by the person and by an administrator."""

import io
import os
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from suveryn_api_gateway.app import create_app
from suveryn_api_gateway.auth import Authenticator, OIDCProvider
from suveryn_api_gateway.avatars import (
    SIZE,
    AvatarStore,
    NotAnImage,
    etag_of,
    normalise,
)
from suveryn_api_gateway.cases import CaseSettings
from suveryn_engine import LlamaServerClient, LLMSettings
from test_auth import SETTINGS, FakeKeycloak
from test_cases import ADMIN, ALICE, BOB, NEW, FakeCases, FakeDirectory, admin_headers
from test_conversations import FakeConversations, as_user
from test_documents import FakeDocuments, llm_transport


def picture(width=640, height=480, fmt="JPEG", exif_rotate=False) -> bytes:
    img = Image.new("RGB", (width, height), (250, 91, 53))
    img.paste((13, 138, 131), (0, 0, width // 2, height))  # the left half teal: orientation is checkable
    out = io.BytesIO()
    if exif_rotate:
        exif = Image.Exif()
        exif[0x0112] = 6  # rotate 90° clockwise to display
        img.save(out, format=fmt, exif=exif)
    else:
        img.save(out, format=fmt)
    return out.getvalue()


def test_normalise_makes_a_small_square_webp_without_distortion():
    out = normalise(picture(640, 480))
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "WEBP" and img.size == (SIZE, SIZE)
        # centre-cropped, not squashed: the left half is still teal, the right half still orange
        assert img.getpixel((20, 128))[1] > 100 and img.getpixel((SIZE - 20, 128))[0] > 200
    assert len(out) < 20_000 and len(etag_of(out)) == 16
    assert normalise(picture(300, 300, "PNG")) != out  # a different picture, a different image


def test_normalise_applies_the_cameras_orientation():
    with Image.open(io.BytesIO(normalise(picture(640, 480, exif_rotate=True)))) as img:
        assert img.size == (SIZE, SIZE)
        # rotated 90° clockwise: the teal half (left) ends up at the top
        assert img.getpixel((128, 20))[1] > 100 and img.getpixel((128, SIZE - 20))[0] > 200


def test_normalise_refuses_what_isnt_a_picture():
    for bad in (b"", b"%PDF-1.7 not a picture", b"\x89PNG\r\n\x1a\n" + b"\x00" * 50):
        with pytest.raises(NotAnImage):
            normalise(bad)
    gif = io.BytesIO()
    Image.new("P", (8, 8)).save(gif, format="GIF")
    with pytest.raises(NotAnImage):
        normalise(gif.getvalue())  # not one of the three formats
    with pytest.raises(NotAnImage):
        normalise(b"x" * (2 * 1024 * 1024 + 1))


# ------------------------------------------------------------------ through the app (needs PostgreSQL)

URL = os.environ.get("SUVERYN_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not URL, reason="SUVERYN_TEST_DATABASE_URL not set")


@pytest.fixture
def avatars():
    s = AvatarStore(URL)
    yield s
    s._execute("DELETE FROM user_avatars WHERE sub IN (%s, %s, %s)", (ALICE, BOB, ADMIN))
    s.close()


@pytest.fixture
def office(avatars):
    kc, cases = FakeKeycloak(), FakeCases()
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    app = create_app(llm, documents=FakeDocuments(owner=ALICE), load_documents=False, auth=auth, conversations=FakeConversations(),
                     cases=cases, avatars=avatars, case_settings=CaseSettings(default_access="members", keep="6m"),
                     directory=FakeDirectory())
    with TestClient(app) as c:
        yield c, kc


@needs_db
def test_a_person_sets_sees_and_removes_their_picture_and_colleagues_see_it(office):
    c, kc = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    assert c.get(f"/v1/users/{ALICE}/avatar", headers=bob).status_code == 404  # initials, then
    assert c.get("/auth/me", headers=alice).status_code in (200, 401)  # bearer sessions have no /auth/me; fine
    r = c.put("/v1/me/avatar", content=picture(), headers={**alice, "Content-Type": "image/jpeg"})
    assert r.status_code == 200 and len(r.json()["avatar"]) == 16
    etag = r.json()["avatar"]
    r = c.get(f"/v1/users/{ALICE}/avatar", headers=bob)
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp" and r.headers["etag"] == f'"{etag}"'
    assert "private" in r.headers["cache-control"]
    with Image.open(io.BytesIO(r.content)) as img:
        assert img.size == (SIZE, SIZE)
    assert c.get(f"/v1/users/{ALICE}/avatar", headers={**bob, "If-None-Match": f'"{etag}"'}).status_code == 304
    # the office's directory and a case's members carry the ETag and the administrator's badge
    people = {p["sub"]: p for p in c.get("/v1/users?q=", headers=bob).json()}
    assert people[ALICE]["avatar"] == etag and people[BOB]["avatar"] is None
    assert people[ADMIN]["admin"] is True and people[ALICE]["admin"] is False
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "reader"}, headers=alice)
    members = {m["user"]: m for m in c.get(f"/v1/cases/{cid}/members", headers=bob).json()}
    assert members[ALICE]["avatar"] == etag and members[BOB]["avatar"] is None and members[ALICE]["admin"] is False
    # not a picture, too large
    assert c.put("/v1/me/avatar", content=b"%PDF-1.7", headers={**alice, "Content-Type": "application/pdf"}).status_code == 415
    assert c.put("/v1/me/avatar", content=b"x", headers={**alice, "Content-Length": str(3 * 1024 * 1024)}).status_code == 413
    # removal: the person's own, and an administrator's of anyone's; a colleague can't remove someone else's
    assert c.delete(f"/v1/users/{ALICE}/avatar", headers=bob).status_code == 403
    assert c.delete("/v1/me/avatar", headers=alice).status_code == 204
    assert c.get(f"/v1/users/{ALICE}/avatar", headers=bob).status_code == 404
    c.put("/v1/me/avatar", content=picture(), headers={**bob, "Content-Type": "image/jpeg"})
    assert c.delete(f"/v1/users/{BOB}/avatar", headers=admin_headers(kc)).status_code == 204
    assert c.get(f"/v1/users/{BOB}/avatar", headers=alice).status_code == 404
    assert c.get(f"/v1/users/{uuid.uuid4()}/avatar", headers=alice).status_code == 404


@needs_db
def test_store_replaces_and_lists_etags(avatars):
    first = avatars.set(ALICE, picture())
    second = avatars.set(ALICE, picture(300, 300, "PNG"))
    assert first != second and avatars.etag(ALICE) == second and avatars.etags([ALICE, BOB]) == {ALICE: second}
    assert avatars.updated_at(ALICE) is not None and avatars.remove(ALICE) and not avatars.remove(ALICE)
    assert avatars.etags([]) == {}
