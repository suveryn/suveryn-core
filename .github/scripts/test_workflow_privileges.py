"""The guard's rule, on workflows that break it, and today's workflows passing.

    uv run pytest -q -p no:cacheprovider .github/scripts"""
import yaml

from workflow_privileges import WORKFLOWS, problems

WRITE = {"contents": "write"}
SPARSE = {"uses": "actions/checkout@v5", "with": {"sparse-checkout": "docs"}}


def job(*steps, permissions=WRITE, **more) -> dict:
    return {"permissions": {"contents": "read"}, "jobs": {"j": {"permissions": permissions, "steps": [SPARSE, *steps], **more}}}


def test_todays_workflows_pass():
    for path in WORKFLOWS.glob("*.y*ml"):
        assert problems(path.name, yaml.safe_load(path.read_text(encoding="utf-8"))) == []


def test_a_writing_job_that_runs_project_code():
    for line in ["npm ci", "npx playwright install", "uv sync", "python3 x.py", "./build.sh", "make all",
                 "cd a && ./x", "bash scripts/x.sh", "sh x.sh"]:
        assert problems("w", job({"run": line})), line


def test_a_writing_job_that_uses_a_local_action_or_another_workflow():
    assert "local action" in problems("w", job({"uses": "./.github/actions/x"}))[0]
    called = {"permissions": {"contents": "read"}, "jobs": {"j": {"permissions": "write-all", "uses": "./.github/workflows/x.yml"}}}
    assert "calls another workflow" in problems("w", called)[0]


def test_a_writing_job_that_checks_out_the_whole_tree():
    for given in [{}, {"sparse-checkout": "."}, {"sparse-checkout": "docs\n/*"}]:
        workflow = {"jobs": {"j": {"permissions": WRITE, "steps": [{"uses": "actions/checkout@v5", "with": given}]}}}
        assert "whole tree" in problems("w", workflow)[0], given


def test_write_permissions_from_the_workflow_count():
    workflow = {"permissions": WRITE, "jobs": {"j": {"steps": [SPARSE, {"run": "npm ci"}]}}}
    assert problems("w", workflow)


def test_a_writing_job_that_only_commits_passes():
    run = 'git add -A -- docs\nbash -c "true"\ngit push origin "HEAD:refs/heads/$B"\ngh workflow run ci.yml'
    assert problems("w", job({"run": run})) == []


def test_a_job_that_only_reads_may_run_anything():
    assert problems("w", job({"run": "npm ci"}, permissions={"contents": "read"})) == []
