"""RAG settings, read from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_jobs() -> int:
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:  # macOS
        return os.cpu_count() or 4


@dataclass(frozen=True)
class RagSettings:
    database_url: str = ""
    # Multilingual (Dutch/French/English) embedding model used in the October 2026 benchmark.
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    device: str = "cuda"
    ocr_languages: str = "nld+fra+eng"
    ocr_jobs: int = field(default_factory=_default_jobs)
    chunk_max_tokens: int = 384
    # Private scratch space for intermediate files (searchable PDFs, OCR work files).
    # Never /tmp: a searchable copy of a document is the full confidential document.
    work_dir: Path = Path.home() / ".local" / "state" / "suveryn" / "work"

    @classmethod
    def from_env(cls) -> "RagSettings":
        d = cls()
        return cls(
            database_url=os.environ.get("SUVERYN_DATABASE_URL", d.database_url),
            embedding_model=os.environ.get("SUVERYN_EMBEDDING_MODEL", d.embedding_model),
            device=os.environ.get("SUVERYN_RAG_DEVICE", d.device),
            ocr_languages=os.environ.get("SUVERYN_OCR_LANGUAGES", d.ocr_languages),
            ocr_jobs=int(os.environ.get("SUVERYN_OCR_JOBS", d.ocr_jobs)),
            chunk_max_tokens=int(os.environ.get("SUVERYN_CHUNK_MAX_TOKENS", d.chunk_max_tokens)),
            work_dir=Path(os.environ.get("SUVERYN_WORK_DIR", d.work_dir)),
        )
