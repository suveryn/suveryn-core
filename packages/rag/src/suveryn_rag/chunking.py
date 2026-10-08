"""Split a Docling document into chunks that keep their page numbers and section headings."""

from dataclasses import dataclass


@dataclass
class Chunk:
    index: int
    text: str            # the chunk's own text, returned as the cited passage
    embed_text: str      # text with section headings prepended, used for the embedding
    page_start: int | None
    page_end: int | None
    headings: list[str]


def chunk_pages(chunk) -> tuple[int | None, int | None]:
    """First and last page (1-based) of the document items a Docling chunk was built from."""
    pages = sorted({prov.page_no for item in chunk.meta.doc_items for prov in (getattr(item, "prov", None) or [])})
    return (pages[0], pages[-1]) if pages else (None, None)


def location_label(page_start: int | None, page_end: int | None, headings: list[str]) -> str | None:
    """Human-readable position, e.g. 'p. 3-4 · Artikel 2 — Koopprijs'."""
    parts = []
    if page_start is not None:
        parts.append(f"p. {page_start}" if page_end in (None, page_start) else f"p. {page_start}-{page_end}")
    if headings:
        parts.append(" › ".join(headings))
    return " · ".join(parts) or None


class Chunker:
    def __init__(self, embedding_model: str, max_tokens: int):
        from docling.chunking import HybridChunker
        from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
        from transformers import AutoTokenizer

        tok = HuggingFaceTokenizer(tokenizer=AutoTokenizer.from_pretrained(embedding_model), max_tokens=max_tokens)
        self._chunker = HybridChunker(tokenizer=tok)

    def chunk(self, document) -> list[Chunk]:
        out = []
        for i, c in enumerate(self._chunker.chunk(dl_doc=document)):
            start, end = chunk_pages(c)
            headings = list(getattr(c.meta, "headings", None) or [])
            out.append(Chunk(index=i, text=c.text, embed_text=self._chunker.contextualize(c),
                             page_start=start, page_end=end, headings=headings))
        return out
