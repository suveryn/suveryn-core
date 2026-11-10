"""The answer checks are held to the planted-error benchmark (``check_benchmark.py``): a change to the checks, or to
the reader under them, may catch more planted mistakes than recorded, never fewer, and may never flag more correct
answers. After a change that catches more (or new cases), record it: ``python packages/harness/tests/check_benchmark.py
--update``, and say in the PR what moved."""
import json

from check_benchmark import RECORD, RULES, run, table


def test_the_checks_catch_what_they_caught_and_flag_no_more_correct_answers():
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    result = run()
    assert result["cases"] == record["cases"], "the cases changed: look at the table, then record it (--update)\n" + table(result)
    assert len(result["false_alarms"]) <= record["false_alarms"], "a correct answer is flagged:\n" + table(result)
    for rule in RULES:
        caught, planted = result["caught"][rule.__name__]
        was, of = record["caught"][rule.__name__]
        assert planted == of, f"{rule.__name__}: {planted} planted, {of} recorded: record it (--update)\n" + table(result)
        assert caught >= was, f"{rule.__name__}: {caught} caught, {was} recorded\n" + table(result)


def test_what_the_checks_compare_is_caught():
    """Amounts, dates, names and the source cited: what the checks are for. The other kinds are recorded as they are."""
    result = run()
    for kind in ("amount", "date", "name", "source"):
        caught, planted = result["caught"][kind]
        assert caught == planted and planted > 0, table(result)
