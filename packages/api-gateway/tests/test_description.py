"""The gateway's description of itself (suveryn-tracker#159, #161): kept as a file the chat UI's code is to be
generated from, so it is what the gateway describes today, and every operation has a name and a group that follow
the naming convention."""

import json

from suveryn_api_gateway import description

# The groups (the convention's thirteen). A new group is added here on purpose, in the change that adds it.
GROUPS = {"auth", "answers", "models", "cases", "settings", "playbooks", "documents", "conversations", "users", "usage",
          "backups", "clock", "status"}
READS = ("get_", "list_", "preview_")


def operations() -> list[tuple[str, str, dict]]:
    described = json.loads(description.FILE.read_text(encoding="utf-8"))
    return [(method.upper(), path, op) for path, by_method in described["paths"].items() for method, op in by_method.items()]


def test_the_file_is_what_the_gateway_describes_today():
    # a change to a route or a model changes openapi.json in the same PR:
    #   uv run python -m suveryn_api_gateway.description
    assert description.FILE.read_text(encoding="utf-8") == description.as_text(description.describe()), (
        "packages/api-gateway/openapi.json is out of date: run `uv run python -m suveryn_api_gateway.description`")
    assert description.main(["--check"]) == 0


def test_every_operation_has_a_name_of_its_own_and_one_group():
    ops = operations()
    names = [op["operationId"] for _, _, op in ops]
    assert len(set(names)) == len(names), sorted(name for name in set(names) if names.count(name) > 1)
    for method, path, op in ops:
        name = op["operationId"]
        # its function's name: lower case words, and no path in it (FastAPI's default id carries the path and method)
        assert name.replace("_", "").isalnum() and name == name.lower() and "__" not in name and "_v1_" not in name, f"{method} {path}: {name}"
        assert len(op.get("tags", [])) == 1 and op["tags"][0] in GROUPS, f"{method} {path}: {op.get('tags')}"
    assert {op["tags"][0] for _, _, op in ops} == GROUPS  # and no group listed here that the gateway no longer has


def test_a_name_starts_with_a_verb_that_fits_what_the_operation_does():
    # the convention: a read is get_, list_ or preview_, and nothing else is; a change of some fields is update_
    for method, path, op in operations():
        name = op["operationId"]
        assert (method == "GET") == name.startswith(READS), f"{method} {path}: {name}"
        if method == "PATCH":
            assert name.startswith("update_"), f"{method} {path}: {name}"
        if name.startswith(("create_", "start_")):
            assert method == "POST", f"{method} {path}: {name}"
        if name.startswith("delete_"):
            assert method == "DELETE", f"{method} {path}: {name}"
        if method == "DELETE":
            assert name.startswith(("delete_", "remove_", "cancel_")), f"{method} {path}: {name}"
        assert "_" in name, f"{method} {path}: {name} (a verb, then what it acts on)"
        # one word for one thing (names.md): a picture, an upload
        assert "avatar" not in name and "_job" not in name, f"{method} {path}: {name}"


def test_every_route_of_the_gateway_is_in_the_description():
    # a module can hold routers of several groups (routes/cases.py); one left out of its `routers` would drop its
    # operations from the gateway without a word. And a route is left out of the description only on purpose.
    import ast
    import pathlib

    routes = pathlib.Path(description.__file__).parent / "routes"
    declared, hidden = 0, []
    for module in routes.glob("*.py"):
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ("get", "post", "put", "patch", "delete"):
                    if any(k.arg == "include_in_schema" for k in d.keywords):
                        hidden.append(node.name)
                    else:
                        declared += 1
    assert declared == len(operations()), f"{declared} routes are declared in routes/, {len(operations())} are described"
    # the two sign-in redirects: a browser follows them, no screen's code calls them
    assert sorted(hidden) == ["callback", "login"], f"routes left out of the description: {sorted(hidden)}"
