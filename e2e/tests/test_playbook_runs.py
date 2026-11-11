"""Playbooks run start to finish with the real model (the GPU round, scripts/gpu-round.sh): the stack with a real
model server instead of the stub (``E2E_LLM``), driven through the gateway's API as the chat UI drives it.

Each run is a spec (``e2e/runs/*.json``, and ``*.json`` in ``E2E_RUNS_DIR``: suveryn-packs' playbooks, with
``E2E_PACKS_DIR`` set when the stack started): a case of the playbook's type, its fictional documents (built by
the spec's ``build`` module beside it, ``build_documents(folder)``), and per step what a person does:

- a ``request``: the documents named for that step id (``"*"``: all of them, in the case before the run starts);
  none named and the step allows it: "there is none";
- an ``ask``: the spec's answer in words (``say``), read by the model as the chat UI's answer is; asked again
  unchanged, the words weren't understood (a failed check), and the spec's values for that step (``answer``: a
  choice a branch depends on can't stay unknown) are given as a card gives them, else "Not known yet";
- the checkpoint: the values as read are confirmed, and the summary is made.

Held to, at the checkpoint: the facts the documents state are there as written (``facts``: a path, or a list's
name for any of its entries, and words its value contains); the facts a person's answer gives are there
(``found``); the facts they never mention are not invented
(``not_found``); planted text never reaches a value (``not_said``), or never a given fact's (``not_in``: a path, or
a list's name, and words none of its values may contain: the earlier owners in a title deed are never today's
sellers); the checks come out as expected (``checks``); the branches a choice leaves out are skipped (``skipped``);
the read steps whose documents were longer than one reading takes say so (``read_in_part``: step ids); a number
whose check digits are wrong is flagged, and no other number is (``flagged``: a path, or a list's name, and words of
the flagged value). After the confirmation: the run is done and its summary
is a document in the case. Fictional documents only, in the repositories. ``E2E_RUNS_REPORT``, if set, is a JSON
report path: per run which checks held, and counts, never a value's text.

A run on someone's own files (the GPU round's ``OWN_RUNS``: specs kept outside the repositories, on files their
owner may share) may say ``"show_facts": true``: the facts at its checkpoint, with their sources, and the checks are
then written to ``E2E_RUNS_FACTS``/<run>.txt for its owner to read, and never into the report or the summary.
"""

from __future__ import annotations

import importlib.util
import json
import mimetypes
import os
import re
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

from conftest import ADMIN, E2E, RUN
from stack import GATEWAY, KC_URL, REAL_LLM
from realm import CHAT_SECRET

pytestmark = pytest.mark.skipif(not REAL_LLM, reason="needs a real model server (E2E_LLM); the stub fills facts by keywords")

SPECS = sorted((E2E / "runs").glob("*.json"))
for runs_dir in filter(None, os.environ.get("E2E_RUNS_DIR", "").split(os.pathsep)):  # several, separated by ":"
    SPECS += sorted(Path(runs_dir).glob("*.json"))
# Never a hidden file: macOS's tar adds "._name.json" beside each file, its attributes, not a spec (the GPU round of
# 5 November: two runs failed on them).
SPECS = [p for p in SPECS if not p.name.startswith(".")]
REPORT: dict[str, dict] = {}
READ_TIMEOUT_S = 900   # a read with the real model: tens of seconds; the first one also waits for the documents


def token(account: dict = ADMIN) -> str:
    """A bearer token for a test account (the test realm's password grant, e2e/realm.py)."""
    r = httpx.post(f"{KC_URL}/realms/suveryn/protocol/openid-connect/token", timeout=20.0, data={
        "grant_type": "password", "client_id": "suveryn-chat", "client_secret": CHAT_SECRET,
        "username": account["username"], "password": account["password"], "scope": "openid profile"})
    r.raise_for_status()
    return r.json()["access_token"]


class ToldToWait(AssertionError):
    """The gateway still said to wait (429) when the patience ran out."""


class Api:
    """The gateway's API as one test account (the administrator unless said), with a fresh token every half minute
    (a run outlives one). ``waits`` counts the times the gateway said to wait (429); ``patience`` is how often one
    request is tried again before that counts as a failure."""

    def __init__(self, account: dict = ADMIN, patience: int = 10):
        self.client = httpx.Client(base_url=GATEWAY, timeout=120.0)
        self.account, self.patience, self.waits = account, patience, 0
        self._token, self._until = "", 0.0

    def headers(self) -> dict[str, str]:
        if time.time() >= self._until:
            self._token, self._until = token(self.account), time.time() + 30
        return {"Authorization": f"Bearer {self._token}"}

    def __call__(self, method: str, path: str, **kw) -> httpx.Response:
        for _ in range(self.patience):  # the per-person limits on questions and answers (a person types slower than this test)
            r = self.client.request(method, path, headers=self.headers(), **kw)
            if r.status_code != 429:
                break
            self.waits += 1
            time.sleep(int(r.headers.get("retry-after", "10")) + 1)
        if r.status_code == 429:
            raise ToldToWait(f"{method} {path}: 429 after {self.patience} tries")
        assert r.status_code < 400, f"{method} {path}: {r.status_code} {r.text[:300]}"
        return r


def upload(api: Api, case_id: str, path: Path) -> str:
    """One document into the case, waited for until it is read; its id."""
    with path.open("rb") as f:
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"  # a Word file among one's own runs
        job = api("POST", f"/v1/documents?case={case_id}", files={"file": (path.name, f, kind)}).json()
    deadline = time.time() + READ_TIMEOUT_S
    while time.time() < deadline:
        j = api("GET", f"/v1/documents/jobs/{job['id']}").json()
        if j["status"] in ("ready", "needs_review"):
            return j["document_id"]
        assert j["status"] not in ("failed", "cancelled"), f"{path.name}: {j['status']} {j.get('error_code')}"
        time.sleep(2)
    raise AssertionError(f"{path.name}: not read in {READ_TIMEOUT_S} s")


def documents_for(spec: dict, spec_path: Path) -> Path:
    """The spec's fictional documents, built once into the stack's run folder."""
    folder = RUN / "runs" / spec_path.stem
    if not folder.exists() or not any(folder.iterdir()):
        folder.mkdir(parents=True, exist_ok=True)
        module = spec_path.parent / spec["build"]
        sys.path.insert(0, str(E2E.parent / "packages" / "rag" / "tests"))  # trap_deed, for core's own specs
        sys.path.insert(0, str(spec_path.parent))  # the spec's own helpers beside it
        loaded = importlib.util.spec_from_file_location(f"build_{spec_path.stem.replace('-', '_')}", module)
        mod = importlib.util.module_from_spec(loaded)
        loaded.loader.exec_module(mod)
        mod.build_documents(folder)
    return folder


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", text).casefold()


def holds(run: dict, spec: dict) -> dict[str, bool]:
    """Every expectation of the spec against the run at its checkpoint: name -> held."""
    expect = spec["expect"]
    # Every value the run has: read from the documents, or given by a person's answer (``found`` is false then: the
    # documents didn't have it).
    values = {f["id"]: f["value"] for f in run["facts"] if f.get("value")}

    def says(prefix: str, needle: str) -> bool:
        return any(_plain(needle) in _plain(v) for k, v in values.items()
                   if k == prefix or k.startswith(prefix + "[") or k.startswith(prefix + "."))

    out = {f"{k} says {v!r}": says(k, v) for k, v in expect.get("facts", {}).items()}
    out |= {f"{k} found": any(p == k or p.startswith(k + "[") or p.startswith(k + ".") for p in values) for k in expect.get("found", [])}
    out |= {f"{k} not invented": not any(p == k or p.startswith(k + "[") for p in values) for k in expect.get("not_found", [])}
    out |= {f"no value says {c!r}": not any(c in v for v in values.values()) for c in expect.get("not_said", [])}
    out |= {f"{k} never says {v!r}": not says(k, v) for k, v in expect.get("not_in", {}).items()}
    out |= {f"check {k} {v}": (run.get("checks", {}).get(k) or {}).get("status") == v for k, v in expect.get("checks", {}).items()}
    out |= {f"step {k} skipped": (run.get("steps", {}).get(k) or {}).get("status") == "skipped" for k in expect.get("skipped", [])}
    out |= {f"step {k} says it read in part": bool((run.get("steps", {}).get(k) or {}).get("in_part")) for k in expect.get("read_in_part", [])}
    if "flagged" in expect:  # the numbers whose check digits are wrong (``needs``), each expected one among them
        def under(path: str, name: str) -> bool:
            return path == name or path.startswith((name + "[", name + "."))

        flagged = {f["id"]: f["value"] for f in run["facts"] if f.get("needs") == "invalid_number"}
        meant = {k: {p for p, value in flagged.items() if under(p, k) and _plain(v) in _plain(value)}
                 for k, v in expect["flagged"].items()}
        out |= {f"number {expect['flagged'][k]!r} of {k} flagged": bool(paths) for k, paths in meant.items()}
        out["number that passes its check flagged: none"] = set(flagged) == set().union(*meant.values())
    return out


def facts_text(run: dict) -> str:
    """The facts at the checkpoint for their owner to read (``show_facts``): one line per fact, its value and where
    it was read, then the checks and the documents read in part."""
    lines = []
    for f in run["facts"]:
        where = ", ".join(f"{c['filename']} p. {c['page']}" if c.get("page") else c["filename"] for c in f.get("citations") or [])
        lines.append(f"{f['id']}: {f.get('value') or '(not found)'}" + (f"  [{where}]" if where else "")
                     + (f"  CHECK: {', '.join(f['issues'])}" if f.get("issues") else ""))
    for name, c in (run.get("checks") or {}).items():
        lines.append(f"check {name}: {c.get('status')}" + (f" ({c.get('left')} / {c.get('right')})" if c.get("status") == "fails" else ""))
    in_part = sorted({d for st in (run.get("steps") or {}).values() for d in st.get("in_part") or []})
    if in_part:
        lines.append("read in part: " + ", ".join(in_part))
    return "\n".join(lines) + "\n"


def score(results: dict[str, bool]) -> dict[str, list[int]]:
    """The reading's score, from what held (``holds``): read right (a stated fact there as written), not invented (a
    fact never mentioned, planted text, an earlier owner), checks as expected (the
    playbook's, and a number's check digits). Per kind [held, of]: what the GPU round prints per playbook, so a change
    shows whether it made the reading better or worse."""
    kinds = {"read right": lambda n: " says " in n and " never says " not in n and not n.startswith(("no value", "step ")),
             "not invented": lambda n: n.endswith(" not invented") or " never says " in n or n.startswith("no value says"),
             "checks": lambda n: n.startswith(("check ", "number "))}
    return {kind: [sum(1 for n, ok in results.items() if test(n) and ok), sum(1 for n in results if test(n))]
            for kind, test in kinds.items()}


def drive(api: Api, cid: str, spec: dict, folder: Path, name: str,
          have: dict[str, str] | None = None) -> tuple[dict, dict | None, list[str], list[str]]:
    """One run of the spec's playbook in a case, driven as a person would to its end: its documents given at each
    request (``have``: the ones in the case already, file name -> id, not uploaded again), its asks answered, the
    facts confirmed as read. The run at its end, the run as it stood at the checkpoint, the asks it made and the ones
    whose answer in words it didn't understand."""
    named, have = spec.get("documents", {}), have or {}
    for filename in named.get("*", []):
        have.get(filename) or upload(api, cid, folder / filename)

    run = api("POST", f"/v1/cases/{cid}/playbooks/{spec['playbook']}/runs", json={"language": spec.get("language", "en")}).json()
    base = f"/v1/cases/{cid}/playbooks/runs/{run['id']}"
    at_checkpoint, asked, acted, answered, not_understood = None, [], {}, set(), []
    deadline = time.time() + 60 * 30
    while time.time() < deadline:
        run = api("GET", base).json()
        status, step, kind = run["status"], run.get("step"), run.get("step_kind")
        if status == "reading":
            time.sleep(2)
            continue
        assert status in ("waiting", "done"), f"{name}: the run is {status} ({run.get('error')}) at {step}"
        if status == "done":
            break
        acted[step] = acted.get(step, 0) + 1  # an ask may come back with its next question: answered again
        assert acted[step] <= 40, f"{name}: {step} keeps waiting"
        if kind == "request":
            names = named.get(step, [])
            if names:
                ids = [have.get(n) or upload(api, cid, folder / n) for n in names]
                api("POST", f"{base}/answer", json={"step_id": step, "documents": ids})
            elif "*" in named:
                api("POST", f"{base}/answer", json={"step_id": step})  # the documents are in the case already
            else:
                api("POST", f"{base}/answer", json={"step_id": step, "none": True})
        elif kind == "ask":
            # The question as the run last asked it: answered in words once. When the playbook says the words couldn't be
            # placed, they weren't understood; then the spec's values, else "Not known yet" (the checkpoint can fill it).
            last = max((t for t in run.get("turns", []) if t["role"] == "playbook" and t.get("step_id") == step),
                       key=lambda t: t["seq"], default=None)
            question = last["seq"] if last else 0
            words, choices = spec.get("say", {}).get(step), spec.get("answer", {}).get(step, {})
            asked.append(step)
            unplaced = (last or {}).get("meta", {}).get("kind") == "unplaced"  # "That couldn't be placed": asked again
            if words and not unplaced and (step, question) not in answered:
                answered.add((step, question))
                api("POST", f"{base}/say", json={"text": words})
            else:
                if words:
                    not_understood.append(step)
                # A choice a branch depends on can't stay unknown: the spec's values, as a card's answer would give them.
                open_facts = set((last or {}).get("meta", {}).get("facts") or choices)
                given = {k: v for k, v in choices.items() if k in open_facts}
                if given:
                    api("POST", f"{base}/answer", json={"step_id": step, "facts": given})
                else:
                    api("POST", f"{base}/say", json={"unknown": True})
        elif kind == "checkpoint":
            at_checkpoint = run
            confirmed = [{"id": f["id"], "confirmed": f.get("value") or ""} for f in run["facts"]]
            api("PUT", f"{base}/facts", json={"facts": confirmed})
        else:
            raise AssertionError(f"{name}: waiting on a {kind} step ({step})")
    else:
        raise AssertionError(f"{name}: not done in 30 minutes, at {run.get('step')}")

    return run, at_checkpoint, asked, not_understood


@pytest.mark.parametrize("spec_path", SPECS, ids=[p.stem for p in SPECS])
def test_a_playbook_runs_to_its_summary_with_the_real_model(stack_up, spec_path):
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    folder = documents_for(spec, spec_path)
    api = Api()
    reference = f"RUN/{spec_path.stem}/{uuid.uuid4().hex[:6]}"
    case = api("POST", "/v1/cases", json={"reference": reference, "name": spec["title"], "type": spec["case_type"]}).json()
    started = time.time()
    run, at_checkpoint, asked, not_understood = drive(api, case["id"], spec, folder, spec_path.stem)
    assert at_checkpoint is not None, f"{spec_path.stem}: never reached its checkpoint"
    results = holds(at_checkpoint, spec)
    results["done, with its summary in the case"] = run["status"] == "done" and bool(run.get("result_document_id"))
    results |= {f"the answer at {s} understood": s not in not_understood for s in spec.get("say", {})}
    found = sum(1 for f in at_checkpoint["facts"] if f.get("value"))
    REPORT[spec_path.stem] = {"playbook": spec["playbook"], "checks": results, "found": found, "facts": len(at_checkpoint["facts"]),
                              "asked": asked, "seconds": round(time.time() - started), "score": score(results),
                              "in_part": sorted({d for st in at_checkpoint.get("steps", {}).values() for d in st.get("in_part") or []})}
    if path := os.environ.get("E2E_RUNS_REPORT"):
        Path(path).write_text(json.dumps(REPORT, indent=1, ensure_ascii=False))
    if spec.get("show_facts") and (folder_out := os.environ.get("E2E_RUNS_FACTS")):
        Path(folder_out).mkdir(parents=True, exist_ok=True)
        (Path(folder_out) / f"{spec_path.stem}.txt").write_text(facts_text(at_checkpoint), encoding="utf-8")
    failures = [name for name, ok in results.items() if not ok]
    print(f"\n{spec_path.stem}: {len(results) - len(failures)}/{len(results)} held, {found} facts found, "
          f"asked at {asked}, {REPORT[spec_path.stem]['seconds']} s")
    assert not failures, f"{spec_path.stem}: " + "; ".join(failures)
