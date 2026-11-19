"""Sentence embeddings (bge-m3 by default), normalised for cosine similarity.

bge-m3 was chosen in the October 2026 benchmark because it handles Dutch, French and English
in one model, which matches Belgian notarial documents.
"""

import logging
import threading

import numpy as np

from . import gpu

log = logging.getLogger("suveryn.rag")


class Embedder:
    """Loads the embedding model once; ``dim`` must match the ``vector(...)`` column in the store.

    Thread-safe: calls are serialised with a lock, so the ingestion worker and the retrieval path
    can share one model (one copy in GPU memory). Embedding a question takes milliseconds.

    When the GPU is full (on a 24 GB card it is shared with the chat model and the layout model), the texts are
    embedded on the CPU instead: slower, but nothing fails for want of GPU memory: a document's passages, a
    question, a sentence marked by meaning. A safeguard (suveryn-tracker#133): on 17 November a document failed to
    read after the GPU ran out of memory over and over, and this step had no fallback; whether it was this step
    the deleted logs can't say. The CPU's copy of the model is loaded the first time it is needed, then kept, as
    the layout model's is (``extract.convert_with_fallback``). Its vectors are float32 where the GPU's come from
    fp16; how close they are was not measured.

    Looked at first: catching only PyTorch's own ``OutOfMemoryError`` (a full GPU also shows as cuBLAS's
    ``CUBLAS_STATUS_ALLOC_FAILED``, a plain ``RuntimeError``), accelerate's ``should_reduce_batch_size`` (it
    doesn't know that form either), and retrying on the GPU with smaller batches first (the usual reaction in
    training; here the GPU is full because the chat model holds it, so a smaller batch is no surer, and the
    layout model already goes to the CPU).
    """

    def __init__(self, model: str, device: str = "cuda", batch_size: int = 16):
        from sentence_transformers import SentenceTransformer

        self._load = lambda on: SentenceTransformer(model, device=on)
        self._model = self._load(device)
        self._on_gpu = device == "cuda"
        self._cpu = None  # made on the first GPU out-of-memory failure, then kept
        if device == "cuda":
            self._model.half()  # about half the GPU memory; it shares the card with the LLM
        self.dim = self._model.get_sentence_embedding_dimension()
        self.batch_size = batch_size  # passages per step on the GPU (SUVERYN_EMBED_BATCH_SIZE, #58)
        self._lock = threading.Lock()
        self._local = threading.local()

    def embed(self, texts: list[str]) -> np.ndarray:
        """One unit-length float32 vector per text (so cosine similarity = dot product).

        In slices, each under the lock, so a question asked meanwhile waits for one slice, not for a whole
        document, also while a document is embedded on the CPU. ``fell_back`` says, for this thread's last call,
        whether a slice went to the CPU."""
        self._local.fell_back = False
        step = max(64, self.batch_size * 4)
        parts = [self._embed_slice(texts[i:i + step]) for i in range(0, len(texts), step)]
        return np.concatenate(parts) if parts else np.zeros((0, self.dim), dtype=np.float32)

    def fell_back(self) -> bool:
        """Whether this thread's last ``embed`` used the CPU because the GPU was full (the reading log line)."""
        return getattr(self._local, "fell_back", False)

    def _embed_slice(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            try:
                return self._encode(self._model, texts)
            except Exception as e:  # noqa: BLE001 - only a full GPU is handled; anything else is raised again
                if not (self._on_gpu and gpu.out_of_memory(e)):
                    raise
            log.warning("embedding on the GPU ran out of memory; %d texts embedded on the CPU", len(texts))
            self._local.fell_back = True
            try:
                import torch

                torch.cuda.empty_cache()
            except Exception:  # noqa: BLE001 - only frees GPU memory; the CPU doesn't depend on it
                pass
            if self._cpu is None:
                self._cpu = self._load("cpu")  # about 2.3 GB of memory, kept for the gateway's life
            return self._encode(self._cpu, texts)

    def _encode(self, model, texts: list[str]) -> np.ndarray:
        return model.encode(texts, normalize_embeddings=True, batch_size=self.batch_size,
                            convert_to_numpy=True).astype(np.float32)
