"""Cached e5 embedding model. Degrades to None if unavailable (FTS-only)."""
from __future__ import annotations

import os

import numpy as np

from ..config import settings

_model = None
_tried = False


def _get_model():
    global _model, _tried
    if _tried:
        return _model
    _tried = True
    if not settings.embeddings_enabled:
        return None
    try:
        os.environ.setdefault("HF_HUB_OFFLINE", "0")
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(settings.embedding_model)
    except Exception as e:  # noqa: BLE001
        print(f"WARNING: embedding model unavailable ({e}); using FTS/BM25 only")
        _model = None
    return _model


def available() -> bool:
    return _get_model() is not None


def embed_passages(texts: list[str]) -> np.ndarray | None:
    m = _get_model()
    if m is None:
        return None
    vecs = m.encode([f"passage: {t}" for t in texts], normalize_embeddings=True,
                    show_progress_bar=False)
    return np.asarray(vecs, dtype=np.float32)


def embed_query(text: str) -> np.ndarray | None:
    m = _get_model()
    if m is None:
        return None
    v = m.encode([f"query: {text}"], normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(v, dtype=np.float32)[0]
