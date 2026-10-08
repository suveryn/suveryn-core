"""Split a Docling document into chunks that keep their page numbers and section headings,
without silently losing text (see ``integrity``)."""

from dataclasses import dataclass, field

from .integrity import IntegrityWarning, norm, page_coverage, split_furniture


@dataclass
class Chunk:
    index: int
    text: str            # the chunk's own text, returned as the cited passage
    embed_text: str      # text with section headings prepended, used for the embedding
    page_start: int | None
    page_end: int | None
    headings: list[str]
    origin: str = "chunker"  # "chunker", or "text_recovered" / "furniture_restored" (see integrity)


@dataclass
class ChunkResult:
    chunks: list[Chunk]
    warnings: list[IntegrityWarning] = field(default_factory=list)


def chunk_pages(chunk) -> tuple[int | None, int | None]:
    """First and last page (1-based) of the document items a Docling chunk was built from."""
    pages = sorted({prov.page_no for item in chunk.meta.doc_items for prov in (getattr(item, "prov", None) or [])})
    return (pages[0], pages[-1]) if pages else (None, None)


def location_label(page_start: int | None, page_end: int | None, headings: list[str]) -> str | None:
    """Human-readable position, e.g. 'p. 3-4 · Artikel 2 - Koopprijs'."""
    parts = []
    if page_start is not None:
        parts.append(f"p. {page_start}" if page_end in (None, page_start) else f"p. {page_start}-{page_end}")
    if headings:
        parts.append(" › ".join(headings))
    return " · ".join(parts) or None


def _page(item) -> int | None:
    prov = getattr(item, "prov", None)
    return prov[0].page_no if prov else None


class Chunker:
    def __init__(self, embedding_model: str, max_tokens: int):
        from docling.chunking import HybridChunker
        from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
        from transformers import AutoTokenizer

        tok = HuggingFaceTokenizer(tokenizer=AutoTokenizer.from_pretrained(embedding_model), max_tokens=max_tokens)
        self._chunker = HybridChunker(tokenizer=tok)

    def chunk(self, document, page_texts: list[str]) -> ChunkResult:
        from docling_core.types.doc import ContentLayer

        raw = list(self._chunker.chunk(dl_doc=document))
        chunks: list[Chunk] = []
        for c in raw:
            start, end = chunk_pages(c)
            chunks.append(Chunk(index=len(chunks), text=c.text, embed_text=self._chunker.contextualize(c),
                                page_start=start, page_end=end, headings=list(getattr(c.meta, "headings", None) or [])))

        # 1. Completeness: body text the chunker left out (e.g. a heading with nothing after it).
        covered = {it.self_ref for c in raw for it in c.meta.doc_items}
        used_headings = {norm(h) for c in chunks for h in c.headings}
        leftovers: list[tuple[int | None, str, str]] = []
        for item, _ in document.iterate_items(included_content_layers={ContentLayer.BODY}):
            label = item.label.value
            if item.self_ref in covered or label == "picture":
                continue
            text = item.export_to_markdown(doc=document) if label == "table" else (getattr(item, "text", "") or "")
            if not text.strip() or (label in ("section_header", "title") and norm(text) in used_headings):
                continue
            leftovers.append((_page(item), text, "text_recovered"))

        # 2. Furniture rule: keep header/footer text unless it really repeats.
        furniture = [(_page(it), it.text) for it, _ in document.iterate_items(included_content_layers={ContentLayer.FURNITURE})
                     if getattr(it, "text", None) and _page(it) is not None]
        dropped, restored = split_furniture(furniture, max(len(page_texts), 1))
        leftovers += [(p, t, "furniture_restored") for p, t in restored]

        warnings: list[IntegrityWarning] = []
        for page, text, kind in leftovers:
            chunks.append(Chunk(index=len(chunks), text=text, embed_text=text, page_start=page, page_end=page,
                                headings=[], origin=kind))
            warnings.append(IntegrityWarning(page, kind, f"{len(text)} characters kept as a separate chunk"))

        # 3. Page coverage against the PDF text layer.
        warnings += page_coverage(page_texts, [(c.page_start, c.page_end, c.text + " " + " ".join(c.headings))
                                               for c in chunks], dropped)
        return ChunkResult(chunks, warnings)
