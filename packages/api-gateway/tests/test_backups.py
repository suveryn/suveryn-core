"""Administration › Backups against the gateway's description (suveryn-tracker#240): the chat UI's code for it is
generated from the description, so each answer its operations give, the refusals too, is checked against it and
kept for the chat UI's tests. What the operations do is tested in ``test_usage.py``."""

import json
from zoneinfo import ZoneInfo

from described import Checked
from test_usage import ALICE, BOB, as_user, setup  # noqa: F401 - the fixture

RID = "0123456789abcdef"
KEY_FILE = f"# Sūveryn backup recovery key\n# created: 2026-10-20\n{'AGE-SECRET-KEY-1' + 'Q' * 58}\n".encode()
SETTINGS = {"kind": "settings", "target": "share", "protocol": "smb", "address": "//nas.office.lan/b", "user": "backup",
            "password": "another-password", "retention_days": 30, "hour": 1}


def test_every_answer_of_backups_is_what_the_description_says(setup, tmp_path, monkeypatch):  # noqa: F811
    from suveryn_api_gateway.routes import backups

    c, kc, _ = setup
    drop, folder = tmp_path / "drop", tmp_path / "requests"
    monkeypatch.setattr(backups, "appliance_zone", lambda: ZoneInfo("Europe/Brussels"))
    for name, value in (("STATUS", tmp_path / "status.json"), ("SETTINGS", tmp_path / "backups.json"),
                        ("SHARE_SECRET", tmp_path / "share.secret"), ("REQUESTS", folder),
                        ("REQUEST_RESULT", tmp_path / "request-result.json"), ("KEY_TEST_RESULT", tmp_path / "key-test.json"),
                        ("KEY_TEST_DROP", drop)):
        monkeypatch.setattr(backups, name, value)
    check, user, admin = Checked(c, "backups"), as_user(kc, BOB), as_user(kc, ALICE, admin=True)
    status, key_test, requests, one = "/v1/admin/backups", "/v1/admin/backups/key-test", "/v1/admin/backups/requests", "/v1/admin/backups/requests/{rid}"
    octets = {"Content-Type": "application/octet-stream"}

    def answer_of(body):  # what the backup service leaves for the request just made
        (folder / "request.json").unlink()
        (tmp_path / "request-result.json").write_text(json.dumps(body))

    for method, path, at, sent in (("GET", status, None, {}), ("POST", key_test, None, {"content": KEY_FILE, "headers": octets}),
                                   ("POST", requests, None, {"json": {"kind": "run"}}), ("GET", one, f"{requests}/{RID}", {})):
        assert check(method, path, 401, at, **sent).json()["code"] == "auth.signed_out"
        sent = {**sent, "headers": {**sent.get("headers", {}), **user}}
        assert check(method, path, 403, at, "not_an_administrator" if path == status else None, **sent).json()["code"] == "request.forbidden"

    # not an appliance, or its backup service never ran
    assert check("GET", status, 200, keep="never_ran", headers=admin).json()["available"] is False
    assert check("POST", key_test, 503, keep="no_backup_service", content=KEY_FILE, headers={**admin, **octets}).json()["code"] == "backup.unavailable"
    assert check("POST", requests, 503, json={"kind": "run"}, headers=admin).json()["code"] == "backup.unavailable"

    # an appliance: a backup made, the next one failed, a key that didn't open it, a share as the target
    drop.mkdir()
    folder.mkdir()
    (tmp_path / "status.json").write_text(json.dumps({
        "configured": True, "target": "share", "retention_days": 90, "last_attempt": "2026-10-23T02:41:07Z",
        "last_success": {"at": "2026-10-22T02:39:00Z", "size": 123456, "on_target": 12, "oldest": "2026-09-23T02:31:00Z"},
        "last_error": {"at": "2026-10-23T02:41:07Z", "failure": {"code": "backup.target_unreachable"}}}))
    (tmp_path / "backups.json").write_text(json.dumps({"target": "share", "protocol": "smb", "address": "//nas.office.lan/b", "user": "backup",
                                                       "retention_days": 90, "hour": 23, "recipient": "age1" + "q" * 58}))
    (tmp_path / "share.secret").write_text("not-a-real-password")
    (tmp_path / "key-test.json").write_text(json.dumps({"at": "2026-10-26T10:00:00Z", "ok": False, "failure": {"code": "backup.key_mismatch"},
                                                        "last_ok": {"at": "2026-10-26T09:50:00Z"}}))

    def the_night_after(body):  # the next run is counted from now
        body["settings"]["next_run"] = "2026-11-22T22:00:00Z"
    told = check("GET", status, 200, keep="as_recorded", tidy=the_night_after, headers=admin).json()
    assert told["last_error"]["failure"] == {"kind": "unavailable", "code": "backup.target_unreachable", "params": {}}
    assert told["key_test"]["failure"]["code"] == "backup.key_mismatch" and told["settings"]["has_password"] is True
    assert "not-a-real-password" not in json.dumps(told)

    assert check("POST", key_test, 415, keep="not_a_key", content=b"not a key", headers={**admin, **octets}).json()["code"] == "backup.not_a_key"
    check("POST", key_test, 202, keep="key_accepted", content=KEY_FILE, headers={**admin, **octets})
    assert check("POST", key_test, 409, keep="key_test_running", content=KEY_FILE, headers={**admin, **octets}).json()["code"] == "backup.busy"

    assert check("POST", requests, 422, keep="settings_incomplete", json={"kind": "settings", "target": "usb"}, headers=admin).json()["code"] == "request.invalid"
    assert "errors" in check("POST", requests, 422, json={**SETTINGS, "hour": 24}, headers=admin).json()
    rid = check("POST", requests, 202, keep="asked", same_every_run={"id": RID}, json=SETTINGS, headers=admin).json()["id"]
    assert check("POST", requests, 409, keep="busy", json={"kind": "disks"}, headers=admin).json()["code"] == "backup.busy"
    assert check("GET", one, 200, f"{requests}/{rid}", "pending", {"id": RID}, headers=admin).json()["pending"] is True
    assert check("GET", one, 404, f"{requests}/not-an-id", "no_such_request", headers=admin).json()["code"] == "request.not_found"
    answer_of({"id": rid, "kind": "settings", "ok": False, "fields": {"address": {"code": "backup.share_address_invalid"}}})
    refused = check("GET", one, 200, f"{requests}/{rid}", "a_field_refused", {"id": RID}, headers=admin).json()
    assert refused["fields"] == {"address": {"kind": "refused", "code": "backup.share_address_invalid", "params": {}}} and refused["failure"] is None
    rid = c.post(requests, json={"kind": "disks"}, headers=admin).json()["id"]
    answer_of({"id": rid, "ok": True, "disks": [{"id": "usb-Extreme_SER1", "name": "Extreme", "size_bytes": 10**12}, {"id": "../../etc", "name": "x"}]})
    assert check("GET", one, 200, f"{requests}/{rid}", "disks", {"id": RID}, headers=admin).json()["disks"] == [
        {"id": "usb-Extreme_SER1", "name": "Extreme", "size_bytes": 10**12}]
    rid = c.post(requests, json={"kind": "run"}, headers=admin).json()["id"]
    answer_of({"id": rid, "ok": False, "failure": {"code": "backup.target_unreachable"}})
    assert check("GET", one, 200, f"{requests}/{rid}", "failed", {"id": RID}, headers=admin).json()["failure"]["code"] == "backup.target_unreachable"
    rid = c.post(requests, json={"kind": "settings", "target": "usb", "disk": "usb-Extreme_SER1", "retention_days": 30, "hour": 2,
                                 "recipient": "age1" + "q" * 58}, headers=admin).json()["id"]
    answer_of({"id": rid, "ok": True, "key_changed": True})
    assert check("GET", one, 200, f"{requests}/{rid}", "saved", {"id": RID}, headers=admin).json()["key_changed"] is True
    check.kept.check()
    # not seen: what nobody planned for; sign-in or the database down where the operation has no 503 of its own; and
    # the 422 FastAPI gives an operation with a parameter, which an id in the address, any text, never gets
    assert check.not_seen() == {("GET", status, 500), ("POST", key_test, 500), ("POST", requests, 500), ("GET", one, 500),
                                ("GET", status, 503), ("GET", one, 503), ("GET", one, 422)}
