"""Sentence embeddings (bge-m3 by default), normalised for cosine similarity.

bge-m3 was chosen in the October 2026 benchmark because it handles Dutch, French and English
in one model, which matches Belgian notarial documents.
"""

import numpy as np


class Embedder:
    """Loads the embedding model once; ``dim`` must match the ``vector(...)`` column in the store."""

    def __init__(self, model: str, device: str = "cuda"):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model, device=device)
        if device == "cuda":
            self._model.half()  # about half the GPU memory; it shares the card with the LLM
        self.dim = self._model.get_sentence_embedding_dimension()

    def embed(self, texts: list[str]) -> np.ndarray:
        """One unit-length float32 vector per text (so cosine similarity = dot product)."""
        return self._model.encode(texts, normalize_embeddings=True, batch_size=16, convert_to_numpy=True).astype(np.float32)
