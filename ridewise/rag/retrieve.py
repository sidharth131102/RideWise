"""Search the policy index on the English rewrite. Hybrid RRF; cosine floor."""
from __future__ import annotations

from functools import lru_cache

from ..contracts import Chunk
from . import embed
from .store import LocalStore

# calibrated on the retrieval eval; English covered questions must pass.
DEFAULT_FLOOR = 0.80


@lru_cache(maxsize=1)
def _store() -> LocalStore:
    return LocalStore().load()


def search(english_query: str, doc_id: str | None = None, version: str | None = None,
           k: int = 5, floor: float | None = None) -> list[Chunk]:
    store = _store()
    qvec = embed.embed_query(english_query)
    hits = store.search(english_query, qvec, doc_id=doc_id, version=version, k=k)
    # cosine floor only when we actually have dense scores
    if qvec is not None and floor is not None:
        kept = [h for h in hits if h.score >= floor]
        # keep at least nothing if clearly unrelated; but exact-term BM25 hits
        # may have score 0 cosine, so only drop when ALL are below floor
        if kept:
            return kept
        if all(h.score < floor for h in hits):
            return []
    return hits
