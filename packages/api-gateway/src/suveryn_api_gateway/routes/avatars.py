"""Avatars (``avatars.py``, docs/design/avatars.md): a person's picture, served to colleagues, set
and removed by the person, removable by an administrator."""

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from ..avatars import CONTENT_TYPE, MAX_UPLOAD_BYTES, AvatarStore, NotAnImage
from .common import admin_or_403, owner_of

log = logging.getLogger("suveryn.gateway")
router = APIRouter()


def avatars_or_503(request: Request) -> AvatarStore:
    db = request.app.state.avatars
    if not db.configured:
        raise HTTPException(503, "Pictures are not available on this server.")
    store = db.get()
    if store is None:
        raise HTTPException(503, f"Pictures are not available right now: {db.error}.")
    return store


@router.get("/v1/users/{sub}/avatar", responses={404: {"description": "No picture"}, 304: {"description": "Unchanged"}})
async def get_avatar(sub: str, request: Request):
    """A colleague's picture (every signed-in user may see it), with an ETag: a browser that has it
    sends ``If-None-Match`` and gets 304. 404 when the person has none (the UI shows initials)."""
    if "/" in sub or len(sub) > 200:
        raise HTTPException(404, "No picture.")
    found = await run_in_threadpool(avatars_or_503(request).get, sub)
    if found is None:
        raise HTTPException(404, "No picture.")
    image, etag = found
    headers = {"ETag": f'"{etag}"', "Cache-Control": "private, max-age=3600"}
    if request.headers.get("if-none-match", "").strip('"') == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=image, media_type=CONTENT_TYPE, headers=headers)


@router.put("/v1/me/avatar", responses={413: {"description": "Larger than 2 MB"}, 415: {"description": "Not a picture"}})
async def set_my_avatar(request: Request):
    """Set the caller's picture: the request body is the image (PNG, JPEG or WebP; the UI sends the
    square it cropped). It is re-encoded on the server (``avatars.normalise``); answers ``{"avatar": etag}``."""
    upload = await request.body()
    if len(upload) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "The picture is larger than 2 MB.")
    if not upload:
        raise HTTPException(415, "Send the picture as the request body.")
    try:
        etag = await run_in_threadpool(avatars_or_503(request).set, owner_of(request), upload)
    except NotAnImage as e:
        raise HTTPException(415, "That isn't a picture sūveryn can read: use a PNG, JPEG or WebP file.") from e
    return {"avatar": etag}


@router.delete("/v1/me/avatar", status_code=204)
async def remove_my_avatar(request: Request):
    """Remove the caller's picture; their initials are shown again."""
    await run_in_threadpool(avatars_or_503(request).remove, owner_of(request))
    return Response(status_code=204)


@router.delete("/v1/users/{sub}/avatar", status_code=204, responses={403: {"description": "Not an administrator"}})
async def remove_avatar(sub: str, request: Request):
    """Administrators: remove someone's picture (one that shouldn't be there). Never set one."""
    admin_or_403(request)
    await run_in_threadpool(avatars_or_503(request).remove, sub)
    log.info("avatar removed by an administrator")
    return Response(status_code=204)
