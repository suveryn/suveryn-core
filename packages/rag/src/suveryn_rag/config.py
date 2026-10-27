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
    """All tunables of the ingestion and retrieval pipeline. Immutable; build with ``from_env()``."""

    database_url: str = ""
    # Multilingual (Dutch/French/English) embedding model used in the October 2026 benchmark.
    # Changing the model after documents were stored needs re-ingestion: stored vectors from
    # another model aren't comparable, and a different dimension won't fit the vector column.
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    device: str = "cuda"
    ocr_languages: str = "nld+fra+eng"
    # Defaults to every core this process may use. The benchmark found 8 cores the sweet spot
    # (16 cores only gave 1.3x more); appliances should set SUVERYN_OCR_JOBS explicitly.
    ocr_jobs: int = field(default_factory=_default_jobs)
    # 384 tokens: big enough to hold a full article of a deed, small enough that a citation
    # points at a specific passage.
    chunk_max_tokens: int = 384
    # Private scratch space for intermediate files (searchable PDFs, OCR work files).
    # Never /tmp: a searchable copy of a document is the full confidential document.
    work_dir: Path = Path.home() / ".local" / "state" / "suveryn" / "work"
    # Uploaded PDFs are read in a separate process without the gateway's secrets (see ``isolation``).
    isolate_extraction: bool = True
    extract_timeout_s: int = 1800  # per document; a 60-page scan takes 1-2 minutes on 8 cores
    extract_wrapper: str = ""      # command prefix for the reader process, e.g. a sandbox (appliance)
    # When the reader runs as its own user (suveryn-appliance's sandbox), it can't enter the gateway's
    # 0700 work_dir. Then uploads wait in ``extract_inbox`` (provisioned: owner the gateway, group the
    # reader, mode 2750; files 0640) and the reader works in its own ``extract_work_dir``.
    extract_inbox: Path | None = None
    extract_work_dir: Path | None = None
    # Without a wrapper the reader runs as the gateway's own user, with network access: refused unless
    # this is set (SUVERYN_EXTRACT_UNSANDBOXED=1, development only; security review 2026-10-11).
    extract_unsandboxed: bool = False
    max_pages: int = 2000  # a PDF with more pages is refused before OCR (a 2,000-page scan takes about an hour)
    # Pages Docling's layout and table models take at once on the GPU, and passages the embedder takes at
    # once: Docling's and our defaults until measured (suveryn-tracker#58). Larger batches use more GPU
    # memory beside the language model; layout falls back to the CPU on out-of-memory.
    layout_batch_size: int = 4
    table_batch_size: int = 4
    embed_batch_size: int = 16

    @classmethod
    def from_env(cls) -> "RagSettings":
        """Read the ``SUVERYN_*`` variables listed in the package README; unset ones keep their default."""
        d = cls()
        return cls(
            database_url=os.environ.get("SUVERYN_DATABASE_URL", d.database_url),
            embedding_model=os.environ.get("SUVERYN_EMBEDDING_MODEL", d.embedding_model),
            device=os.environ.get("SUVERYN_RAG_DEVICE", d.device),
            ocr_languages=os.environ.get("SUVERYN_OCR_LANGUAGES", d.ocr_languages),
            ocr_jobs=int(os.environ.get("SUVERYN_OCR_JOBS", d.ocr_jobs)),
            chunk_max_tokens=int(os.environ.get("SUVERYN_CHUNK_MAX_TOKENS", d.chunk_max_tokens)),
            work_dir=Path(os.environ.get("SUVERYN_WORK_DIR", d.work_dir)),
            isolate_extraction=os.environ.get("SUVERYN_EXTRACT_ISOLATION", "").lower() != "off",
            extract_timeout_s=int(os.environ.get("SUVERYN_EXTRACT_TIMEOUT_S", d.extract_timeout_s)),
            extract_wrapper=os.environ.get("SUVERYN_EXTRACT_WRAPPER", d.extract_wrapper),
            extract_inbox=Path(v) if (v := os.environ.get("SUVERYN_EXTRACT_INBOX")) else None,
            extract_work_dir=Path(v) if (v := os.environ.get("SUVERYN_EXTRACT_WORK_DIR")) else None,
            extract_unsandboxed=os.environ.get("SUVERYN_EXTRACT_UNSANDBOXED", "") == "1",
            max_pages=int(os.environ.get("SUVERYN_MAX_PAGES", d.max_pages)),
            layout_batch_size=int(os.environ.get("SUVERYN_LAYOUT_BATCH_SIZE", d.layout_batch_size)),
            table_batch_size=int(os.environ.get("SUVERYN_TABLE_BATCH_SIZE", d.table_batch_size)),
            embed_batch_size=int(os.environ.get("SUVERYN_EMBED_BATCH_SIZE", d.embed_batch_size)),
        )
