"""Keep the RAG models offline: no downloads and no update checks or usage data at runtime.

The embedding model (bge-m3) and Docling's layout and table models are fetched from the Hugging
Face Hub by name. Left to their defaults, the libraries would download them on first use and, even
when they are cached, contact huggingface.co on every load (sending library and version
information). An appliance must not do either: documents are confidential and the network may be
air-gapped. So ``enforce()`` switches the libraries to offline mode before any of them is imported;
models then load only from the local cache (``HF_HOME``).

Models are put in the cache once, when the machine is set up, with ``suveryn-fetch-models`` (which
sets ``SUVERYN_ALLOW_DOWNLOADS=1`` for that one process). Review note: a missing model then fails
loudly at startup instead of being downloaded silently.
"""

import os

OFFLINE = {
    "HF_HUB_OFFLINE": "1",             # huggingface_hub: no network calls at all, cache only
    "TRANSFORMERS_OFFLINE": "1",       # transformers: same, for tokenizers and models
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",   # no usage data, even if a call were made
    "DO_NOT_TRACK": "1",               # the cross-tool opt-out several libraries honour
}


def downloads_allowed() -> bool:
    """True only when ``SUVERYN_ALLOW_DOWNLOADS=1`` (set by ``suveryn-fetch-models``)."""
    return os.environ.get("SUVERYN_ALLOW_DOWNLOADS") == "1"


def enforce() -> None:
    """Set the offline variables, overriding any other value, unless downloads are explicitly allowed.

    Must run before huggingface_hub, transformers, sentence-transformers or Docling is imported:
    they read these variables once, at import. ``suveryn_rag`` calls it on import, and its heavy
    imports are all lazy.
    """
    if downloads_allowed():
        for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
            os.environ.pop(name, None)  # set by an earlier enforce() when suveryn_rag was imported
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["DO_NOT_TRACK"] = "1"
        return
    os.environ.update(OFFLINE)
