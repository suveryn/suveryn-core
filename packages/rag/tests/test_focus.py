"""Narrowing a case's sources to the documents a question is about (suveryn_rag.focus)."""

import uuid

from suveryn_rag import focus

A, B, C, D = (uuid.UUID(int=i) for i in range(1, 5))


def test_a_document_named_by_its_file_name_is_chosen():
    names = {A: "deed-of-sale.pdf", B: "lease-agreement.pdf", C: "care-mandate.docx"}
    assert focus.named("What is the rent in the lease?", names) == [B]
    assert focus.named("Who signed the mandate and the lease?", names) == [B, C]


def test_a_word_every_file_name_has_names_nothing_and_a_vague_question_names_nothing():
    names = {A: "deed-plot-north.pdf", B: "deed-plot-south.pdf", C: "deed-garage.pdf"}
    assert focus.named("What does the deed say about the price?", names) == []  # every file is a deed
    assert focus.named("Which plot is the largest?", names) == [A, B]           # two of three
    assert focus.named("What is the price?", names) == []
    assert focus.named("Mention of 2024 and pdf", {A: "2024.pdf", B: "other.pdf"}) == []  # numbers and extensions don't count


def test_too_many_named_documents_say_nothing():
    names = {A: "sale-one.pdf", B: "sale-two.pdf", C: "sale-three.pdf", D: "sale-four.pdf", uuid.UUID(int=9): "lease.pdf"}
    assert focus.named("Compare the sale deeds", names) == []  # names four: more than MOST


def test_the_best_ranked_document_is_kept_with_those_close_to_it():
    assert focus.choose({A: 1 + 1 / 2 + 1 / 4, B: 1 / 3 + 1 / 5}) == [A]                  # one document clearly
    assert focus.choose({A: 1 + 1 / 3, B: 1 / 2 + 1 / 4 + 1 / 5, C: 1 / 6}) == [A, B]     # two of one transaction
    assert focus.choose({A: 1.0, B: 0.9, C: 0.8, D: 0.7}) == [A, B, C]                     # at most three
    assert focus.choose({}) == []


class FakeStore:
    """The store as Rag.passages uses it, recording which documents were read."""

    def __init__(self, names, weights):
        self.names, self.weights, self.read = names, weights, None
        self.whole = None  # the documents are too large to give whole: their best chunks are read

    def filenames(self, ids):
        return {d: self.names[d] for d in ids}

    def document_weights(self, query, question, ids, top):
        return {d: w for d, w in self.weights.items() if d in ids}

    def document_chunks(self, ids, max_chars, max_chunks):
        self.read = list(ids)
        return self.whole

    def best_chunks(self, query, question, ids, max_chars, max_chunks, k):
        self.read = list(ids)
        return []


class FakeEmbedder:
    def embed(self, texts):
        return [[0.0]]


def rag(store):
    from suveryn_rag.pipeline import Rag

    r = object.__new__(Rag)
    r.store, r.embedder = store, FakeEmbedder()
    return r


def test_a_case_wide_question_reads_only_the_documents_it_is_about():
    store = FakeStore({A: "deed-north.pdf", B: "deed-south.pdf", C: "mandate.pdf"}, {A: 1.5, B: 0.3, C: 0.2})
    rag(store).passages("What is the price?", [A, B, C], 6, focus=True)
    assert store.read == [A]                                # ranked
    rag(store).passages("Who signs the mandate?", [A, B, C], 6, focus=True)
    assert store.read == [C]                                # named, whatever the ranking
    rag(store).passages("What is the price?", [A, B, C], 6)
    assert store.read == [A, B, C]                          # chosen documents: all of them, as before
    rag(store).passages("What is the price?", [B], 6, focus=True)
    assert store.read == [B]                                # one document: nothing to narrow
    rag(FakeStore({A: "a.pdf", B: "b.pdf"}, {})).passages("x", [A, B], 6, focus=True)  # no ranking: all
