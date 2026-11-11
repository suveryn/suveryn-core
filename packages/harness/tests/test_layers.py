"""The harness's modules import one way only (decision of 10 November 2026): what a module may use sits in a lower
layer. ``values`` reads amounts, numbers and dates for everything above it and uses only the languages' words, so a
check, a marking and a playbook's facts can't come to read a figure their own way again."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "suveryn_harness"

# Lowest first. A module may import only from modules in a lower layer.
LAYERS = [
    {"language"},                                                              # each language's words, from its files
    {"values", "identifiers", "schemas", "config", "audit", "usage", "guard", "thinking"},  # reading, shapes, settings
    {"calc", "terms", "grounding", "llm"},                                     # computing, terms, the prompt, the model client
    {"marking"},                                                               # where a claim's support is in its passage
    {"support", "checks"},                                                     # does the source say it; a playbook's checks
    {"facts"},                                                                 # a playbook's facts, read and checked
    {"service"},                                                               # the chat surface
    {"__init__"},                                                              # what the package offers
]


def _layer(name: str) -> int:
    return next(i for i, layer in enumerate(LAYERS) if name in layer)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level == 1 and n.module}


def test_every_module_has_a_layer():
    assert {p.stem for p in SRC.glob("*.py")} == set().union(*LAYERS)


def test_values_uses_only_the_languages_words():
    assert _imports(SRC / "values.py") == {"language"}
    assert _imports(SRC / "language.py") == set()


def test_imports_go_down_only():
    wrong = []
    for path in SRC.glob("*.py"):
        mine = _layer(path.stem)
        for used in _imports(path):
            if _layer(used) >= mine:
                wrong.append(f"{path.stem} imports {used}")
    assert wrong == []
