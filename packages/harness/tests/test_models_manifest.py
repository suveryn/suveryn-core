"""The models manifest pins what is downloaded (suveryn-tracker#134).

A publisher replaced a model file under the same name on 11 November 2026: the checksum caught it, and every fresh
set-up stopped, because the file was fetched from the publisher's ``main``. Each model names the commit that holds it.
"""
import configparser
import importlib.util
import json
import re
from pathlib import Path

import pytest

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


def _presets_module():
    spec = importlib.util.spec_from_file_location("presets", Path(__file__).parents[3] / "models" / "scripts" / "presets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_router_presets_are_written_from_the_manifest():
    """One place for a model's file and settings (suveryn-tracker#133): models/scripts/presets.py writes llama-server's
    presets from each model's options, so Mistral gets its smaller file and its 4-bit cache, and Qwen its template."""
    ini = configparser.ConfigParser(interpolation=None)
    ini.read_string(_presets_module().presets(MANIFEST, "/models"))
    llms = [m for m in MANIFEST["models"] if m["role"] == "llm"]
    assert ini.sections() == [m["id"] for m in llms]
    for model in llms:
        preset = ini[model["id"]]
        assert preset["model"] == f"/models/{model['file']}"
        assert (preset.get("load-on-startup") == "true") == bool(model.get("default")), model["id"]
    assert ini["mistral-small-3.2-24b"]["ctk"] == ini["mistral-small-3.2-24b"]["ctv"] == "q4_0"
    assert ini["qwen3.8-27b"]["chat-template-kwargs"] == '{"enable_thinking":false}'
    assert ini["qwen3.8-27b"]["jinja"] == "true"


def test_a_mistake_in_a_models_options_stops_the_presets():
    """An option is named once, short or long; a switch takes no value, and a word that is neither stops the writing
    rather than becoming a setting llama-server would read wrongly."""
    options = _presets_module().options
    assert options("-c 65536 -kvu --flash-attn on -ngl 99") == [("c", "65536"), ("kvu", "true"), ("flash-attn", "on"),
                                                                 ("ngl", "99")]
    assert options("--kv-unified -fa on") == [("kv-unified", "true"), ("fa", "on")]
    for wrong in ("65536", "--a=1", "-c 1 2"):
        with pytest.raises(ValueError):
            options(wrong)
