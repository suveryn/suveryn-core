"""A guard for the one rule zizmor has no audit for (suveryn-tracker#252): a job that can write runs no
project code, so a compromised package in a pull request never runs where a token can write.

    uv run python .github/scripts/workflow_privileges.py

For every job in .github/workflows/ that can write (by its own permissions or the workflow's):
- no step runs npm, node, uv, pip, python, make, playwright, ./a-script or bash/sh a-script;
- no step uses a local action (uses: ./…), and the job doesn't call another workflow;
- it checks out only the folders it writes (a sparse checkout that isn't the whole tree).

It is a guard against bringing those patterns back, not a proof: it reads words, and a pull request can
change this file and the workflows too. zizmor (.github/zizmor.yml) checks the rest: permissions, kept tokens,
injected expressions, triggers. Exits 1 and names each job and what it does."""
import re
import sys
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / "workflows"
RUNS_CODE = re.compile(r"(?<![\w-])(npm|npx|node|yarn|pnpm|uv|uvx|pip3?|python3?|make|playwright)(?![\w-])"
                       r"|(^|[\s;&|(])\./|(?<![\w-])(bash|sh)\s+(?!-c\b)[^\s-]")
WHOLE_TREE = {".", "/", "*", "/*", "**", "./"}


def writes(permissions) -> bool:
    if isinstance(permissions, str):
        return permissions == "write-all"
    return any(value == "write" for value in (permissions or {}).values())


def problems(name: str, workflow: dict) -> list[str]:
    found = []
    for job_id, job in (workflow.get("jobs") or {}).items():
        if not writes(job.get("permissions", workflow.get("permissions"))):
            continue
        where = f"{name}, job {job_id}: can write, and"
        if "uses" in job:
            found.append(f"{where} calls another workflow ({job['uses']})")
        for step in job.get("steps") or []:
            uses, given = step.get("uses", ""), step.get("with") or {}
            if "run" in step and RUNS_CODE.search(step["run"]):
                found.append(f"{where} a step runs project code ({step.get('name') or step['run'].splitlines()[0]})")
            if uses.startswith("./"):
                found.append(f"{where} a step uses a local action ({uses})")
            if uses.startswith("actions/checkout@"):
                paths = str(given.get("sparse-checkout") or "").split()
                if not paths or WHOLE_TREE & set(paths):
                    found.append(f"{where} checks out the whole tree instead of only the folders it writes")
    return found


def main() -> int:
    found = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        found += problems(path.name, yaml.safe_load(path.read_text(encoding="utf-8")))
    for line in found:
        print(line)
    print(f"{len(found)} problems" if found else "no job that can write runs project code")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
