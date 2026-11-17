"""llama-server's router presets, written from models/manifest.json (suveryn-tracker#133).

Each language model's ``llama_server_args`` in the manifest is llama-server's own options. On the command line they
are used as they are; for llama-server in router mode, where people choose the model per conversation, this writes
them as its presets file: one section per model, each option under its name without the dashes (short or long, as
llama.cpp's ``--models-preset`` format takes either), an option without a value as ``true``. So a model's file and
settings are written in one place, the manifest.

    python3 models/scripts/presets.py --models-dir /path/to/models > /path/to/presets.ini
    llama-server --models-preset /path/to/presets.ini --models-max 1 --host 127.0.0.1 --port 8080

Python's standard library only, so the appliance can run it from its copy of core.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path

MANIFEST = Path(__file__).parents[1] / "manifest.json"
_OPTION = re.compile(r"--?[a-z][a-z0-9-]*")
_NUMBER = re.compile(r"-?[0-9.]+")


def options(args: str) -> list[tuple[str, str]]:
    """``-c 65536 -kvu --flash-attn on`` as ``[("c", "65536"), ("kvu", "true"), ("flash-attn", "on")]``. A word that is
    neither an option nor the value right after one is refused, so a mistake in the manifest stops the writing."""
    words, out, i = shlex.split(args), [], 0
    while i < len(words):
        if not _OPTION.fullmatch(words[i]):
            raise ValueError(f"not an option: {words[i]!r} in {args!r}")
        name = words[i].lstrip("-")
        has_value = i + 1 < len(words) and (not words[i + 1].startswith("-") or _NUMBER.fullmatch(words[i + 1]))
        out.append((name, words[i + 1] if has_value else "true"))
        i += 2 if has_value else 1
    return out


def presets(manifest: dict, models_dir: str) -> str:
    """The presets file for every language model in the manifest; the default one loads at start."""
    folder = Path(models_dir).resolve()  # llama-server reads a relative path from where it runs: always absolute
    out = ["; Written by models/scripts/presets.py from suveryn-core's models/manifest.json; change the manifest.", ""]
    for model in (m for m in manifest["models"] if m.get("role") == "llm"):
        out += [f"[{model['id']}]", f"model = {folder / model['file']}"]
        out += [f"{key} = {value}" for key, value in options(model["llama_server_args"])]
        if model.get("default"):
            out.append("load-on-startup = true")
        out.append("")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models-dir", required=True, help="the folder that holds the model files")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    a = parser.parse_args()
    sys.stdout.write(presets(json.loads(a.manifest.read_text(encoding="utf-8")), a.models_dir))


if __name__ == "__main__":
    main()
