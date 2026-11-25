"""What every gateway test shares."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from suveryn_api_gateway.conversations import Conversation, ConversationSummary, cited_documents, redact


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


# ---------------------------------------------------------------- a conversation store, and asking in it

class FakeConversations:
    """In-memory stand-in for ``ConversationStore``."""

    def __init__(self):
        self.rows: dict[uuid.UUID, dict] = {}
        self.keep = "manual"  # the gateway sets the office's period before listing (routes/common.py)

    def close(self):
        pass

    def purge(self):
        self.purged = getattr(self, "purged", []) + [self.keep]
        return 0

    def older_than(self, days):
        limit = datetime.now(UTC) - timedelta(days=days)
        return sum(1 for r in self.rows.values() if r["updated_at"] <= limit)

    # unfinished cleanings after a document's deletion (routes/documents.py): (owner, document) -> (delete, case)
    cleanups: dict

    def note_cleanup(self, owner, document_id, delete_conversations, case_id):
        self.__dict__.setdefault("cleanups", {})[(owner, document_id)] = (delete_conversations, case_id)

    def cleanup_done(self, owner, document_id):
        self.__dict__.setdefault("cleanups", {}).pop((owner, document_id), None)

    def finish_cleanups(self):
        pending = list(self.__dict__.setdefault("cleanups", {}).items())
        for (owner, did), (delete, case_id) in pending:
            self.remove_document(owner, did, delete, case_id)
            self.cleanup_done(owner, did)
        return len(pending)

    def summaries_all(self, owner, case_ids):
        rows = sorted((r for r in self.rows.values() if (r["owner"] == owner and (r["case_id"] is None or r["case_id"] in case_ids))
                       or (r["shared"] and r["case_id"] in case_ids)),
                      key=lambda r: r["updated_at"], reverse=True)
        return [self._summary(r) for r in rows]

    def summaries(self, owner, case_id=None):
        rows = sorted((r for r in self.rows.values() if r["case_id"] == case_id
                       and (r["owner"] == owner or (r["shared"] and case_id is not None))),
                      key=lambda r: r["updated_at"], reverse=True)
        return [self._summary(r) for r in rows]

    @staticmethod
    def _summary(r):
        return ConversationSummary(**{k: r[k] for k in ("id", "title", "created_at", "updated_at", "owner", "shared")},
                                   case_id=str(r["case_id"]) if r["case_id"] else None, messages=len(r["turns"]),
                                   pinned=bool(r.get("pinned")))

    def get(self, cid, owner):
        r = self.rows.get(cid)
        if not r or r["owner"] != owner:
            return None
        return Conversation(**self._summary(r).model_dump(), turns=r["turns"])

    def get_shared(self, cid):
        r = self.rows.get(cid)
        if not r or not r["shared"] or r["case_id"] is None:
            return None
        return Conversation(**self._summary(r).model_dump(), turns=r["turns"])

    def rename(self, cid, owner, title):
        r = self.rows.get(cid)
        if not r or r["owner"] != owner:
            return None
        r["title"] = title
        return self._summary(r)

    def set_pinned(self, cid, owner, pinned):
        r = self.rows.get(cid)
        if not r or r["owner"] != owner or r["case_id"] is not None:
            return None
        r["pinned"] = pinned
        return self._summary(r)

    def move(self, cid, owner, case_id):
        r = self.rows.get(cid)
        if not r or r["owner"] != owner or r["case_id"] is not None:
            return None
        r.update(case_id=case_id, shared=False, pinned=False)
        return self._summary(r)

    def unshare_case(self, case_id):
        rows = [r for r in self.rows.values() if str(r["case_id"]) == str(case_id) and r["shared"]]
        for r in rows:
            r["shared"] = False
        return len(rows)

    def set_shared(self, cid, owner, shared):
        r = self.rows.get(cid)
        if not r or r["owner"] != owner or r["case_id"] is None:
            return None
        r["shared"] = shared
        return self._summary(r)

    # A conversation the server writes turn by turn (suveryn-tracker#251), as ``ConversationStore`` does.
    def place(self, cid):
        r = self.rows.get(cid)
        return (r["owner"], r["case_id"], bool(r.get("run"))) if r else None

    def start(self, cid, owner, title, case_id):
        if cid in self.rows:
            return False
        now = datetime.now(UTC)
        self.rows[cid] = {"id": str(cid), "owner": owner, "title": title, "pinned": False, "turns": [],
                          "created_at": now, "updated_at": now, "case_id": case_id, "shared": False}
        return True

    def turns_of(self, cid):
        from suveryn_api_gateway.conversations import Turn

        return [Turn(seq=i, role=t["role"], by=t.get("by", "x"), at=t.get("at", datetime.now(UTC)), text=t.get("text", ""),
                     meta={k: v for k, v in t.items() if k not in ("role", "text", "by", "at")})
                for i, t in enumerate(self.rows[cid]["turns"], start=1)]

    def add(self, cid, role, by, text, meta, documents):
        self.rows[cid]["turns"].append({"role": role, "text": text, "by": by, **meta})
        self.rows[cid]["updated_at"] = datetime.now(UTC)
        return self.turns_of(cid)[-1]

    def using_document(self, owner, document_id, case_id=None):
        rows = sorted((r for r in self.rows.values() if (r["case_id"] == case_id if case_id is not None else r["owner"] == owner)),
                      key=lambda r: r["updated_at"], reverse=True)
        return [self._summary(r) for r in rows if str(document_id) in cited_documents(r["turns"])]

    def remove_document(self, owner, document_id, delete_conversations=False, case_id=None):
        hits = self.using_document(owner, document_id, case_id)
        for h in hits:
            if delete_conversations:
                del self.rows[uuid.UUID(h.id)]
            else:
                redact(self.rows[uuid.UUID(h.id)]["turns"], lambda d: d == str(document_id))
        return len(hits)

    def delete(self, cid, owner):
        if cid in self.rows and self.rows[cid]["owner"] == owner:
            del self.rows[cid]
            return True
        return False

    def delete_all(self, owner):
        mine = [c for c, r in self.rows.items() if r["owner"] == owner]
        for c in mine:
            del self.rows[c]
        return len(mine)

    def delete_case(self, case_id):
        gone = [c for c, r in self.rows.items() if r["case_id"] == case_id]
        for c in gone:
            del self.rows[c]
        return len(gone)


class Asked:
    """What a question asked as the screens ask it gave back (``ask``): its ``status_code`` and its ``events``; and, read
    like an answer, ``json()``: the ``done`` event's answer, the refusal, or the ``error`` event, whose code's status is
    then the ``status_code`` (an answer that failed once it had started: the model gone, the documents unreadable)."""

    def __init__(self, response, events: list[tuple[str, dict]]):
        self.response, self.events, self.headers = response, events, response.headers
        failed = next((data for name, data in events if name == "error"), None)
        self.status_code = response.status_code
        if failed is not None:
            from suveryn_harness.messages import CODES

            self.status_code = CODES[failed["code"]].status or 500
        self._json = (failed if failed is not None else next((data for name, data in events if name == "done"), None)
                      if response.status_code == 200 else response.json())

    def json(self):
        return self._json


def ask(c, body: dict, headers: dict | None = None, conversation: str | None = None) -> Asked:
    """A question asked as the screens ask it (suveryn-tracker#251): in a conversation the server keeps (a new one
    unless ``conversation`` is given), streamed. ``body`` says what is asked: ``text`` (or the last of ``messages``),
    and the documents, case, model and thinking as a question takes them. A test app without a conversation store gets
    a stand-in (``FakeConversations``), since a question is always kept: a test of asking without one asks by hand
    (test_usage.py)."""
    from suveryn_api_gateway.routes.common import Database

    if not c.app.state.history.configured:
        c.app.state.history = Database("conversation", store=FakeConversations())
    question = {k: v for k, v in body.items() if k not in ("messages", "stream", "max_tokens")}
    if "messages" in body:
        assert len(body["messages"]) <= 1, "earlier turns come from the conversation the server keeps"
        question.setdefault("text", body["messages"][-1]["content"] if body["messages"] else "")
    with c.stream("POST", f"/v1/conversations/{conversation or uuid.uuid4()}/questions", json=question,
                  headers=headers or {}) as r:
        if r.status_code != 200:
            r.read()
            return Asked(r, [])
        events, name = [], None
        for line in r.iter_lines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                events.append((name, json.loads(line[6:])))
        return Asked(r, events)
