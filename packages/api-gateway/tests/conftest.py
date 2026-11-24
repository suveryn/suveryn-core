"""What every gateway test shares."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def not_an_appliance(monkeypatch, tmp_path):
    """The tests run as on a development machine, wherever they run: the gateway refuses uploads while an
    appliance's data partition is short (routes/status.py ``disk_low``), and a test machine with a fuller disk,
    or with a /var/lib/suveryn of its own, must not change what the tests see. A test that wants the data
    partition sets ``status.DATA_PATH`` itself; one that wants the clock's requests, ``clock.REQUESTS``."""
    import suveryn_api_gateway.clock as clock
    import suveryn_api_gateway.routes.status as status

    monkeypatch.setattr(status, "DATA_PATH", Path(tmp_path) / "no-data-partition")
    # nor this machine's clock: no folder for the appliance's clock requests, and no time server known
    monkeypatch.setattr(clock, "REQUESTS", Path(tmp_path) / "no-clock-requests")
    monkeypatch.setattr(clock, "time_server_keeps_it", lambda: None)


def kept(store, cid, owner: str, turns: list[dict], title: str = "Wat is de koopprijs?", case_id=None) -> bool:
    """A conversation as the server keeps one (suveryn-tracker#251), written straight to ``store`` for a test: started
    under ``owner`` (in ``case_id``, or the personal space), then each turn added after the one before, as the questions
    route writes them. A turn is given by its ``role`` and ``text``; the rest is its ``meta``, with the ``kind`` and the
    ``parent`` the server gives it (and ``outcome: done`` for an answer) unless the turn says otherwise. False when the
    id is taken already, by anyone."""
    import uuid

    from suveryn_api_gateway.conversations import cited_documents

    cid, case = uuid.UUID(str(cid)), uuid.UUID(str(case_id)) if case_id else None
    if not store.start(cid, owner, title, case):
        return False
    parent = None
    for turn in turns:
        meta = {"kind": "question" if turn["role"] == "user" else "answer", "parent": parent,
                **({"outcome": "done"} if turn["role"] == "assistant" else {}),
                **{k: v for k, v in turn.items() if k not in ("role", "text", "id")}}
        parent = store.add(cid, turn["role"], owner if turn["role"] == "user" else "assistant", turn.get("text", ""), meta,
                           cited_documents([meta])).seq
    return True
