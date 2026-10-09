"""Sūveryn RAG: extraction (ocr_fast), chunking, embeddings, pgvector store and retrieval.

Heavy dependencies (Docling, PyTorch) are imported lazily, so ``import suveryn_rag`` is cheap.
Importing it also switches the model libraries to offline mode (see ``offline``), before any of
them can be imported.
"""

from . import offline

offline.enforce()

from .config import RagSettings

__all__ = ["RagSettings"]
