"""An experiment, not a test: can the model on the box judge what the rules in ``support`` judge by word lists?

For every answer of the planted-error benchmark (``check_cases.json``: correct answers on fictional passages, and the
same answers with one mistake planted by ``check_benchmark``'s rules), each cited claim is put to the model with the
passages it cites: do they say this? An answer is flagged when the model says no for one of its claims. Reported
beside the rules' own result: mistakes caught per kind, correct answers flagged, and the seconds a claim takes.
Needs a llama-server with the appliance's model (``scripts/gpu-round.sh`` with MEANING=1 runs it):

    python packages/harness/tests/meaning_experiment.py --url http://127.0.0.1:8080 --out meaning.json
    ... --thinking       # let the model think first (slower)

Fictional text only. The report holds counts, times and the benchmark's own sentences.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time

import check_benchmark as bench
import httpx
from suveryn_harness.marking import marker_claims

# "same": the first prompt (10 November 2026; one correct answer of 40 flagged, for leaving words out). "follows":
# what is asked is whether the passages carry the statement, not whether the two say the same.
PROMPTS = {
    "same": (
        "You check one statement against the source passages it cites. The statement is supported only if the passages "
        "say the same thing: the same amounts, numbers, dates, names and units, the same party doing or owing it, and "
        "the same meaning, not its opposite. A paraphrase, a summary or a translation of what the passages say is "
        "supported. A number written in words and the same number in figures are the same. First name the difference "
        "in a few words (or \"none\"), then say whether the statement is supported."),
    "follows": (
        "You check one statement against the source passages it cites. The statement is supported if everything it "
        "says follows from the passages. It may leave things out, shorten, reword, explain a legal term in plain words "
        "or be in another language than the passages: none of that is a difference. It is not supported if it says "
        "something the passages don't say or contradicts them: another amount, number, date, name or unit, another "
        "party doing or owing it, the opposite, a condition or limit dropped or added, or more than the passages say. "
        "A number in words and the same number in figures are the same. First name what the statement says that the "
        "passages don't, in a few words (or \"none\"), then say whether the statement is supported."),
    # The second run (10 November 2026): the model named two right answers' differences correctly as leaving words
    # out, and still said "not supported". Here it names the kind of difference and the code decides: leaving out is none.
    "kind": (
        "You compare one statement with the source passages it cites. Name the difference in a few words, then its "
        "kind. \"none\": the statement says what the passages say, reworded, explained in plain words or in another "
        "language. \"leaves_out\": the statement only leaves out or shortens something the passages say, and what it "
        "does say is in them. \"adds\": the statement says something the passages don't: more than they say, a unit, "
        "a condition or a limit they don't hold. \"contradicts\": the statement says something else than the passages: "
        "another amount, number, date, name or unit, another party doing or owing it, the opposite, earlier for later, "
        "may for must. A number in words and the same number in figures are the same."),
}
KINDS = {"type": "object", "additionalProperties": False, "required": ["difference", "kind"],
         "properties": {"difference": {"type": "string", "maxLength": 160},
                        "kind": {"type": "string", "enum": ["none", "leaves_out", "adds", "contradicts"]}}}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["difference", "supported"],
          "properties": {"difference": {"type": "string", "maxLength": 160}, "supported": {"type": "boolean"}}}


class Judge:
    def __init__(self, url: str, thinking: bool, prompt: str = "follows"):
        self.system, self.schema = PROMPTS[prompt], KINDS if prompt == "kind" else SCHEMA
        self.kinds: dict[str, int] = {}
        self.differences: dict[str, str] = {}
        self.http = httpx.Client(base_url=url, timeout=600)
        self.thinking = thinking
        self.verdicts: dict[tuple[str, tuple[str, ...]], bool] = {}
        self.seconds: list[float] = []
        self.unreadable = 0

    def supported(self, claim: str, passages: tuple[str, ...]) -> bool:
        key = (claim, passages)
        if key not in self.verdicts:
            cited = "\n\n".join(f"Passage {i}:\n{p}" for i, p in enumerate(passages, 1))
            payload = {"messages": [{"role": "system", "content": self.system},
                                    {"role": "user", "content": f"{cited}\n\nStatement:\n{claim}"}],
                       "temperature": 0, "max_tokens": 2000 if self.thinking else 120,
                       "chat_template_kwargs": {"enable_thinking": self.thinking},
                       "response_format": {"type": "json_schema", "json_schema": {"name": "verdict", "strict": True, "schema": self.schema}}}
            started = time.monotonic()
            r = self.http.post("/v1/chat/completions", json=payload)
            r.raise_for_status()
            self.seconds.append(time.monotonic() - started)
            try:
                verdict = json.loads(r.json()["choices"][0]["message"]["content"])
                if "kind" in verdict:
                    self.kinds[verdict["kind"]] = self.kinds.get(verdict["kind"], 0) + 1
                    verdict["supported"] = verdict["kind"] in ("none", "leaves_out")
                    verdict["difference"] = f"{verdict['kind']}: {verdict.get('difference', '')}"
                self.verdicts[key] = bool(verdict["supported"])
                if not verdict["supported"]:
                    self.differences[claim] = str(verdict.get("difference", ""))
            except (ValueError, KeyError, TypeError):
                self.unreadable += 1
                self.verdicts[key] = True  # no verdict: nothing is flagged, as when a check can't run
        return self.verdicts[key]

    def flags(self, answer: str, case: dict) -> bool:
        """Whether the model says no for one of the answer's cited claims."""
        texts = [p["text"] for p in case["passages"]]
        by_claim: dict[str, list[int]] = {}
        for n, claim in marker_claims(answer, len(texts)):
            if claim and n not in by_claim.setdefault(claim, []):
                by_claim[claim].append(n)
        return any(not self.supported(claim, tuple(texts[n - 1] for n in ns)) for claim, ns in by_claim.items())


def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("--url", default="http://127.0.0.1:8080")
    args.add_argument("--out", default="")
    args.add_argument("--thinking", action="store_true")
    args.add_argument("--prompt", choices=sorted(PROMPTS), default="follows")
    o = args.parse_args()
    judge = Judge(o.url, o.thinking, o.prompt)
    hard = json.loads((bench.HERE / "meaning_cases.json").read_text(encoding="utf-8"))["cases"]
    for c in hard:
        c["passages"] = [{"text": p} for p in c["passages"]]
    cases = json.loads(bench.CASES.read_text(encoding="utf-8"))["cases"]
    rules = bench.run()

    started = time.monotonic()
    false_alarms = [c["answer"] for c in cases if judge.flags(c["answer"], c)]
    caught, missed = {}, {}
    for rule in bench.RULES:
        planted = [(c, changed) for c in cases if (changed := rule(c["answer"], c)) and changed != c["answer"]]
        hit = [changed for c, changed in planted if judge.flags(changed, c)]
        caught[rule.__name__] = [len(hit), len(planted)]
        missed[rule.__name__] = [changed for _, changed in planted if changed not in hit]
    hard_right = [c for c in hard if c["right"]]
    hard_wrong = [c for c in hard if not c["right"]]
    hard_flagged = [c["answer"] for c in hard_right if judge.flags(c["answer"], c)]
    hard_missed = [c["answer"] for c in hard_wrong if not judge.flags(c["answer"], c)]
    rules_flagged = [c["answer"] for c in hard_right if bench.reports(c["answer"], c)]
    rules_missed = [c["answer"] for c in hard_wrong if not bench.reports(c["answer"], c)]
    s = sorted(judge.seconds)

    print(f"meaning experiment (prompt {o.prompt}, {'thinking' if o.thinking else 'no thinking'}): {len(cases)} correct answers, {len(s)} claims judged "
          f"in {time.monotonic() - started:.0f} s")
    print(f"  per claim: median {statistics.median(s):.1f} s, slowest tenth from {s[int(len(s) * 0.9)]:.1f} s, longest {s[-1]:.1f} s"
          f"; no verdict: {judge.unreadable}")
    print(f"  correct answers flagged: the model {len(false_alarms)}, the rules {len(rules['false_alarms'])}")
    print("  planted mistake   the model   the rules")
    for rule in bench.RULES:
        a, n = caught[rule.__name__]
        print(f"    {rule.__name__:12}  {a:>2} of {n:<2}    {rules['caught'][rule.__name__][0]:>2} of {n}")
    print(f"  harder cases, by hand: right answers flagged: the model {len(hard_flagged)} of {len(hard_right)}, the rules "
          f"{len(rules_flagged)}; wrong answers caught: the model {len(hard_wrong) - len(hard_missed)} of {len(hard_wrong)}, "
          f"the rules {len(hard_wrong) - len(rules_missed)}")
    if judge.kinds:
        print("  kinds named: " + ", ".join(f"{k} {n}" for k, n in sorted(judge.kinds.items())))
    for a in dict.fromkeys(false_alarms + hard_flagged):
        said = "; ".join(d for claim, d in judge.differences.items() if claim and claim in a.replace("**", ""))
        print(f"  flagged though right: {a}  <- {said}")
    for a in hard_missed:
        print(f"  wrong but passed: {a}")
    if o.out:
        with open(o.out, "w", encoding="utf-8") as f:
            json.dump({"thinking": o.thinking, "cases": len(cases), "claims": len(s), "seconds": [round(x, 2) for x in s],
                       "prompt": o.prompt, "false_alarms": false_alarms, "hard_flagged": hard_flagged,
                       "hard_missed": hard_missed, "differences": judge.differences, "caught": caught, "missed": missed, "rules": rules["caught"],
                       "no_verdict": judge.unreadable}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
