"""The gateway's description of itself, as a file (suveryn-tracker#159, #161).

FastAPI builds a description of the gateway from its routes and their models (OpenAPI): what can be asked and what
comes back. The chat UI's code that calls the server is generated from it, one area at a time, so that a name is
typed once (#159; the clock first, #236, then #237, #238: ``packages/chat-ui/src/generated``). The description
names every operation and its group; a moved area's operations also describe every refusal
(``problems.refusals``). Elsewhere some answers, the states kept as text and the events aren't described yet (#159
lists them).

The description is kept as a file in the repository, ``packages/api-gateway/openapi.json``, so it can be read and
reviewed without a running gateway, and so a generator needs no server, database or model:

    uv run python -m suveryn_api_gateway.description          # write the file
    uv run python -m suveryn_api_gateway.description --check  # fail when it isn't what the gateway describes

A test runs the check (``tests/test_description.py``): a change to a route or a model changes the file in the same
PR. The file's text follows the locked versions of FastAPI and pydantic (``uv.lock``): a change of either can
change it, and the file is then written again in that change.

Names, because generated code is named after them (the convention: docs/design/names.md):
- An operation's id is its function's name: a verb, then what it acts on (``get_case``, ``list_documents``). A read
  starts with ``get_``, ``list_`` or ``preview_``, and nothing else does.
- An operation is in exactly one group (its tag: ``cases``, ``documents``, …), set on a router in ``routes/``.
- An operation can still be renamed: the chat UI is built from the same commit as the gateway, so nothing outside
  holds a name. That changes the day something outside calls the gateway (docs/design/names.md, *Released*).
"""

import argparse
import json
import sys
from pathlib import Path

from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict

FILE = Path(__file__).resolve().parents[2] / "openapi.json"


class Answer(BaseModel):
    """What an operation answers, for a model of a strictly described area: a member with a default is always
    sent, and is described as always there, so generated code doesn't call it optional (pydantic's switch for
    exactly that). Without it only the members without a default are."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


def operation_id(route: APIRoute) -> str:
    """An operation's id in the description: its function's name."""
    return route.name


def describe() -> dict:
    """The description as the gateway serves it at ``/openapi.json``: built from the routes, nothing started."""
    from .app import create_app  # here, not at the top: app.py names its operations with operation_id

    return create_app(load_documents=False).openapi()


def as_text(description: dict) -> str:
    """The file's text: the same for the same description, whatever built it (keys in order, one per line)."""
    return json.dumps(description, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m suveryn_api_gateway.description", description="Write the gateway's description to openapi.json.")
    parser.add_argument("--check", action="store_true", help="write nothing; fail when the file isn't what the gateway describes")
    args = parser.parse_args(argv)
    text = as_text(describe())
    if args.check:
        if not FILE.exists() or FILE.read_text(encoding="utf-8") != text:
            print(f"{FILE.name} isn't what the gateway describes: run `uv run python -m suveryn_api_gateway.description` "
                  "and commit the file with the change", file=sys.stderr)
            return 1
        return 0
    FILE.write_text(text, encoding="utf-8")
    print(f"wrote {FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
