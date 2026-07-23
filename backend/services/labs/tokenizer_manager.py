"""Custom tokenizer training on top of HF `tokenizers` (Rust-backed).

The library is already pulled in by `transformers`, so training BPE/WordPiece/
Unigram tokenizers costs zero extra dependency. Tokenizers are saved as a
single portable `tokenizer.json` under data/tokenizers/<id>/.
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_SPECIAL_TOKENS = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"]

ALGORITHMS: Dict[str, Dict[str, str]] = {
    "bpe": {
        "name": "BPE (Byte-Pair Encoding)",
        "description": "Fusionne les paires fréquentes. Standard des LLM modernes (GPT, Llama). "
        "En mode byte-level, aucun mot inconnu possible.",
    },
    "wordpiece": {
        "name": "WordPiece",
        "description": "Fusion par vraisemblance (BERT). Bon compromis pour la classification de texte.",
    },
    "unigram": {
        "name": "Unigram",
        "description": "Modèle probabiliste qui élague un grand vocabulaire (SentencePiece/T5). "
        "Souvent meilleur sur corpus multilingues.",
    },
    "wordlevel": {
        "name": "Word Level",
        "description": "Un token = un mot. Simple et interprétable, mais vocabulaire explosif "
        "et mots inconnus fréquents.",
    },
    "char": {
        "name": "Caractères",
        "description": "Un token = un caractère. Vocabulaire minuscule, séquences longues. "
        "Idéal pour comprendre la tokenisation.",
    },
}

_TEXT_COLUMNS = ("text", "sentence", "content", "document", "review", "question")


def _iter_dataset_texts(dataset_path: str, max_texts: int = 200_000) -> Iterator[str]:
    """Yield raw text from a dataset directory.

    Supports HF `save_to_disk` layouts and plain uploaded files
    (.txt, .csv, .tsv, .json, .jsonl).
    """
    path = Path(dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset introuvable: {dataset_path}")

    count = 0
    if (path / "dataset_dict.json").exists() or (path / "dataset_info.json").exists():
        from datasets import load_from_disk

        ds = load_from_disk(str(path))
        splits = ds.values() if hasattr(ds, "values") else [ds]
        for split in splits:
            col = next((c for c in _TEXT_COLUMNS if c in split.column_names), None)
            if col is None:
                continue
            for value in split[col]:
                if value:
                    yield str(value)
                    count += 1
                    if count >= max_texts:
                        return
        if count == 0:
            raise ValueError(
                "Aucune colonne texte trouvée dans le dataset "
                f"(colonnes attendues: {', '.join(_TEXT_COLUMNS)})"
            )
        return

    for file in sorted(path.rglob("*")):
        if not file.is_file():
            continue
        suffix = file.suffix.lower()
        try:
            if suffix in (".txt", ".md"):
                with file.open(encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            yield line
                            count += 1
                            if count >= max_texts:
                                return
            elif suffix in (".csv", ".tsv"):
                import csv

                delim = "\t" if suffix == ".tsv" else ","
                with file.open(encoding="utf-8", errors="ignore", newline="") as fh:
                    for row in csv.reader(fh, delimiter=delim):
                        for cell in row:
                            if cell and len(cell) > 1:
                                yield cell
                                count += 1
                                if count >= max_texts:
                                    return
            elif suffix in (".json", ".jsonl"):
                with file.open(encoding="utf-8", errors="ignore") as fh:
                    records: Iterator[Any]
                    if suffix == ".jsonl":
                        records = (json.loads(line) for line in fh if line.strip())
                    else:
                        data = json.load(fh)
                        records = iter(data if isinstance(data, list) else [data])
                    for rec in records:
                        if isinstance(rec, str):
                            yield rec
                            count += 1
                        elif isinstance(rec, dict):
                            for c in _TEXT_COLUMNS:
                                if isinstance(rec.get(c), str):
                                    yield rec[c]
                                    count += 1
                                    break
                        if count >= max_texts:
                            return
        except Exception:
            logger.warning(f"Fichier corpus ignoré (illisible): {file}", exc_info=True)

    if count == 0:
        raise ValueError("Aucun texte exploitable trouvé dans le dataset")


def _build_tokenizer_and_trainer(
    algorithm: str,
    vocab_size: int,
    min_frequency: int,
    special_tokens: List[str],
    lowercase: bool,
    byte_level: bool,
):
    from tokenizers import Regex, Tokenizer, decoders, models, normalizers, pre_tokenizers, trainers

    norm_steps = [normalizers.NFKC()]
    if lowercase:
        norm_steps.append(normalizers.Lowercase())
    normalizer = normalizers.Sequence(norm_steps)

    if algorithm == "bpe":
        tokenizer = Tokenizer(models.BPE(unk_token="[UNK]"))
        tokenizer.normalizer = normalizer
        if byte_level:
            tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=True)
            tokenizer.decoder = decoders.ByteLevel()
            trainer = trainers.BpeTrainer(
                vocab_size=vocab_size,
                min_frequency=min_frequency,
                special_tokens=special_tokens,
                initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
            )
        else:
            tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
            trainer = trainers.BpeTrainer(
                vocab_size=vocab_size,
                min_frequency=min_frequency,
                special_tokens=special_tokens,
            )
    elif algorithm == "wordpiece":
        tokenizer = Tokenizer(models.WordPiece(unk_token="[UNK]"))
        tokenizer.normalizer = normalizers.Sequence(
            [normalizers.BertNormalizer(lowercase=lowercase)]
        )
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        tokenizer.decoder = decoders.WordPiece(prefix="##")
        trainer = trainers.WordPieceTrainer(
            vocab_size=vocab_size,
            min_frequency=min_frequency,
            special_tokens=special_tokens,
            continuing_subword_prefix="##",
        )
    elif algorithm == "unigram":
        tokenizer = Tokenizer(models.Unigram())
        tokenizer.normalizer = normalizer
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        trainer = trainers.UnigramTrainer(
            vocab_size=vocab_size,
            special_tokens=special_tokens,
            unk_token="[UNK]",
        )
    elif algorithm == "wordlevel":
        tokenizer = Tokenizer(models.WordLevel(unk_token="[UNK]"))
        tokenizer.normalizer = normalizer
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        trainer = trainers.WordLevelTrainer(
            vocab_size=vocab_size,
            min_frequency=min_frequency,
            special_tokens=special_tokens,
        )
    elif algorithm == "char":
        tokenizer = Tokenizer(models.WordLevel(unk_token="[UNK]"))
        tokenizer.normalizer = normalizer
        tokenizer.pre_tokenizer = pre_tokenizers.Split(Regex("."), behavior="isolated")
        trainer = trainers.WordLevelTrainer(
            vocab_size=vocab_size,
            min_frequency=1,
            special_tokens=special_tokens,
        )
    else:
        raise ValueError(f"Algorithme inconnu: {algorithm}")

    return tokenizer, trainer


async def train_tokenizer(
    db_id: str,
    algorithm: str,
    vocab_size: int,
    min_frequency: int,
    special_tokens: Optional[List[str]],
    lowercase: bool,
    byte_level: bool,
    dataset_path: str,
    db_session,
) -> None:
    """Train a tokenizer on a dataset's text and update the DB record."""
    from sqlalchemy import select

    from models.tokenizer_model import TokenizerModel

    tokens = special_tokens or DEFAULT_SPECIAL_TOKENS
    out_dir = settings.tokenizers_dir / db_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "tokenizer.json"

    async def _update(status: str, error: str = "", **fields) -> None:
        async with db_session() as db:
            result = await db.execute(select(TokenizerModel).where(TokenizerModel.id == db_id))
            rec = result.scalar_one_or_none()
            if rec:
                rec.status = status
                if error:
                    rec.error_message = error
                for k, v in fields.items():
                    setattr(rec, k, v)
                await db.commit()

    def _train() -> Dict[str, Any]:
        tokenizer, trainer = _build_tokenizer_and_trainer(
            algorithm, vocab_size, min_frequency, tokens, lowercase, byte_level
        )
        num_texts = 0

        def counting_iterator():
            nonlocal num_texts
            for text in _iter_dataset_texts(dataset_path):
                num_texts += 1
                yield text

        tokenizer.train_from_iterator(counting_iterator(), trainer=trainer)
        tokenizer.save(str(out_path))
        return {
            "actual_vocab_size": tokenizer.get_vocab_size(),
            "num_texts": num_texts,
        }

    try:
        info = await asyncio.get_event_loop().run_in_executor(None, _train)
        await _update(
            "ready",
            local_path=str(out_path),
            actual_vocab_size=info["actual_vocab_size"],
            stats={"num_texts": info["num_texts"]},
        )
    except Exception as exc:
        logger.exception(f"Tokenizer training failed: {exc}")
        await _update("error", error=str(exc))


def encode_preview(tokenizer_path: str, text: str) -> Dict[str, Any]:
    """Encode a text and return tokens + ids for UI preview."""
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(tokenizer_path)
    encoding = tokenizer.encode(text)
    return {
        "tokens": encoding.tokens,
        "ids": encoding.ids,
        "num_tokens": len(encoding.ids),
        "vocab_size": tokenizer.get_vocab_size(),
    }
