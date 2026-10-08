"""Sūveryn RAG: extraction (ocr_fast), chunking, embeddings, pgvector store and retrieval.

Heavy dependencies (Docling, PyTorch) are imported lazily, so ``import suveryn_rag`` is cheap.
"""

from .config import RagSettings

__all__ = ["RagSettings"]
