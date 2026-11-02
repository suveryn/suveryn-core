"""A light stand-in embedding model, for a development machine that can't reach Hugging Face (e2e/README.md,
"Light mode"): a static (bag-of-tokens) sentence-transformers model with 1,024 dimensions, the size the store
expects of bge-m3, saved to a folder that SUVERYN_EMBEDDING_MODEL then names. Retrieval with it is crude but
deterministic: a passage that shares words with the question ranks first. CI uses the real bge-m3.

    uv run python e2e/light/make_embedder.py e2e/.run/light-embedder
"""

import sys
from pathlib import Path

from sentence_transformers import SentenceTransformer, models
from tokenizers import Tokenizer, models as tok_models, normalizers, pre_tokenizers, trainers

CORPUS = Path(__file__).resolve().parents[2] / "packages" / "rag" / "tests" / "trap_deed.py"


def main(out: Path) -> None:
    tokenizer = Tokenizer(tok_models.WordPiece(unk_token="[UNK]"))
    tokenizer.normalizer = normalizers.Sequence([normalizers.NFD(), normalizers.Lowercase(), normalizers.StripAccents()])
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    trainer = trainers.WordPieceTrainer(vocab_size=8000, special_tokens=["[UNK]", "[PAD]"])
    words = CORPUS.read_text(encoding="utf-8")
    tokenizer.train_from_iterator([words, "wat is de koopprijs huurder kadastraal verkoper koper akte"], trainer)
    static = models.StaticEmbedding(tokenizer, embedding_dim=1024)
    model = SentenceTransformer(modules=[static, models.Normalize()], device="cpu")
    model.save(str(out))
    print(out)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
