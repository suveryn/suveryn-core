"""The models manifest pins what is downloaded (suveryn-tracker#134).

A publisher replaced a model file under the same name on 11 November 2026: the checksum caught it, and every fresh
set-up stopped, because the file was fetched from the publisher's ``main``. Each model names the commit that holds it.
"""
import json
import re
from pathlib import Path

MANIFEST = json.loads((Path(__file__).parents[3] / "models" / "manifest.json").read_text(encoding="utf-8"))
COMMIT = re.compile(r"\b[0-9a-f]{40}\b")


def test_every_model_names_the_publishers_commit():
    for model in MANIFEST["models"]:
        assert COMMIT.search(model.get("revision", "")), f"{model['id']}: no revision (a commit of {model['source']})"


def test_every_model_file_has_its_size_and_checksum():
    files = [m for m in MANIFEST["models"] if "file" in m]
    assert files, "no model file in the manifest"
    for model in files:
        assert re.fullmatch(r"[0-9a-f]{64}", model["sha256"]) and model["size_bytes"] > 0, model["id"]
