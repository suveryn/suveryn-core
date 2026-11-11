"""Several people at work at the same moment, with the real model (the GPU round's ``PEOPLE``, scripts/gpu-round.sh):
how long each of them waits, and whether anything fails, as their number grows.

For each number of people (``E2E_PEOPLE``, as "1 2 4 8"), every person has their own account and their own case, and
they all do the same three things at the same moment, one kind after the other, so each number is the worst case for
its kind:

1. **documents**: upload a run spec's documents (``E2E_PEOPLE_SPEC``; core's deed intake on the fictional trap deed
   unless said) and wait until they are read;
2. **questions**: ask three questions about them, as the chat UI does (streamed), one after the other;
3. **playbook**: run the spec's playbook to its summary, as tests/test_playbook_runs.py drives it.

Measured per person: the seconds until the documents are read, until an answer's first words, until the answer is
whole, until the playbook's summary (a playbook refused because too many runs are reading has failed as busy: the
person starts it again a little later, and that waiting counts); how often the gateway said to wait (429: its limits
per person) and how often a playbook was refused as busy; and what failed. The report (``E2E_PEOPLE_REPORT``) and what is printed hold
seconds, counts and the kind of a failure, never a document's or an answer's text, so a spec on one's own files can
be used. Slow is a finding, not a failure: the test fails only when something a person did failed.
"""

from __future__ import annotations

import json
import os
import shutil
import statistics
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from conftest import E2E
from stack import REAL_LLM, seed_accounts
from test_playbook_runs import Api, ToldToWait, documents_for, drive, upload

LEVELS = [int(n) for n in os.environ.get("E2E_PEOPLE", "").replace(",", " ").split()]
pytestmark = pytest.mark.skipif(not (REAL_LLM and LEVELS), reason="needs a real model server (E2E_LLM) and E2E_PEOPLE, as '1 2 4 8'")

SPEC = Path(os.environ.get("E2E_PEOPLE_SPEC") or E2E / "runs" / "deed-intake.json")
# Questions any file can be asked: the test measures the waiting, not the answers (test_answers_e2e.py holds those).
QUESTIONS = ["Who are the parties named in these documents?", "Which amounts do these documents state, and for what?",
             "Summarise these documents in five lines."]
ANSWER_TIMEOUT_S = 1800
REFUSED_TRIES, REFUSED_WAIT_S = 120, 15   # a playbook refused as busy is started again, for half an hour


def people(n: int) -> list[dict]:
    """The accounts of n people, none an administrator (made in the test realm when first needed)."""
    return [{"username": f"person{i:02d}.test", "email": f"person{i:02d}@example.test", "firstName": "Person", "lastName": f"{i:02d}",
             "password": "Person-e2e-2026!", "admin": False} for i in range(1, n + 1)]


def ask(api: Api, cid: str, documents: list[str], question: str) -> tuple[float, float]:
    """One streamed question: the seconds until the answer's first words, and until it is whole. Told to wait, the
    person waits and asks again: that time counts."""
    body = {"messages": [{"role": "user", "content": question}], "stream": True, "document_ids": documents, "case_id": cid}
    started = time.time()
    for _ in range(api.patience):
        first, event = None, None
        with api.client.stream("POST", "/v1/chat", json=body, headers=api.headers(),
                               timeout=httpx.Timeout(ANSWER_TIMEOUT_S, connect=20.0)) as r:
            if r.status_code == 429:
                api.waits += 1
                time.sleep(int(r.headers.get("retry-after", "10")) + 1)
                continue
            assert r.status_code == 200, f"a question: {r.status_code}"
            for line in r.iter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: ") and event == "delta" and first is None:
                    first = time.time() - started
                elif line.startswith("data: ") and event == "error":
                    raise AssertionError("an answer ended in an error")
                elif line.startswith("data: ") and event == "done":
                    return first if first is not None else time.time() - started, time.time() - started
        raise AssertionError("an answer's stream ended before it was done")
    raise AssertionError("a question: told to wait too often")


class Memory:
    """The card's peak memory while a number of people work (nvidia-smi, once a second); None without a card."""

    def __init__(self):
        self.peak, self._stop = None, threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True)

    def _watch(self) -> None:
        while not self._stop.wait(1.0):
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True).stdout.split()
            if out:
                self.peak = max(self.peak or 0, *(int(v) for v in out))

    def __enter__(self) -> "Memory":
        if shutil.which("nvidia-smi"):
            self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()


def together(apis: list[Api], work) -> tuple[list, list[str]]:
    """Every person does ``work(api, index)`` from the same moment: what each got (None when it failed), and the
    failures, as the kind of error and its message (a status or a step, never a document's text)."""
    barrier = threading.Barrier(len(apis))

    def one(i: int):
        barrier.wait()
        try:
            return work(apis[i], i), None
        except Exception as e:  # whatever went wrong for this person is a failure to count, not to raise here
            return None, f"person {i + 1}: {type(e).__name__}: {str(e)[:160]}"

    with ThreadPoolExecutor(len(apis)) as pool:
        got = list(pool.map(one, range(len(apis))))
    return [g for g, _ in got], [f for _, f in got if f]


def spread(seconds: list[float]) -> dict | None:
    """The median and the worst of what people waited, in seconds; None when nobody got that far."""
    return {"median": round(statistics.median(seconds), 1), "worst": round(max(seconds), 1)} if seconds else None


def test_several_people_at_the_same_moment(stack_up):
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    folder = documents_for(spec, SPEC)
    names = sorted({n for group in spec.get("documents", {}).values() for n in group})
    seed_accounts(people(max(LEVELS)))
    report, failed_at = [], []
    for n in LEVELS:
        apis = [Api(a, patience=150) for a in people(n)]
        cases: list[str | None] = [None] * n
        have: list[dict[str, str]] = [{} for _ in range(n)]
        refused = [0] * n

        def documents(api: Api, i: int) -> float:
            started = time.time()
            cases[i] = api("POST", "/v1/cases", json={"reference": f"PEOPLE/{n}/{i + 1}/{uuid.uuid4().hex[:6]}",
                                                      "name": f"Several people: {n}", "type": spec["case_type"]}).json()["id"]
            for name in names:
                have[i][name] = upload(api, cases[i], folder / name)
            return time.time() - started

        def questions(api: Api, i: int) -> list[tuple[float, float]]:
            assert have[i], "no documents to ask about"
            return [ask(api, cases[i], list(have[i].values()), q) for q in spec.get("questions", QUESTIONS)]

        def playbook(api: Api, i: int) -> float:
            assert cases[i], "no case to run in"
            started, once = time.time(), Api(api.account, patience=1)
            for _ in range(REFUSED_TRIES):
                try:
                    run, _, _, _ = drive(once, cases[i], spec, folder, f"person {i + 1}", have[i])
                    break
                except ToldToWait:  # too many runs reading: this run has failed as busy, and the person starts another
                    refused[i] += 1
                    time.sleep(REFUSED_WAIT_S)
            else:
                raise AssertionError("the playbook was refused as busy every time")
            assert run["status"] == "done" and run.get("result_document_id"), "the run ended without its summary"
            return time.time() - started

        started = time.time()
        with Memory() as memory:
            read, f1 = together(apis, documents)
            asked, f2 = together(apis, questions)
            ran, f3 = together(apis, playbook)
        answers = [a for person in asked if person for a in person]
        level = {"people": n, "documents": spread([s for s in read if s is not None]),
                 "first_words": spread([first for first, _ in answers]), "answer": spread([whole for _, whole in answers]),
                 "playbook": spread([s for s in ran if s is not None]), "told_to_wait": sum(a.waits for a in apis), "runs_refused": sum(refused),
                 "failed": f1 + f2 + f3, "peak_mib": memory.peak, "seconds": round(time.time() - started)}
        report.append(level)
        failed_at += [f"{n} people: {f}" for f in level["failed"]]
        if path := os.environ.get("E2E_PEOPLE_REPORT"):
            Path(path).write_text(json.dumps({"spec": SPEC.stem, "playbook": spec["playbook"], "levels": report}, indent=1))
        print(f"\n{n} people: " + ", ".join(f"{k} {level[k]['median']} s (worst {level[k]['worst']} s)" for k in
                                             ("documents", "first_words", "answer", "playbook") if level[k])
              + f"; told to wait {level['told_to_wait']} times; playbook refused as busy {level['runs_refused']} times; "
                f"{len(level['failed'])} failed")
    assert not failed_at, "; ".join(failed_at)
