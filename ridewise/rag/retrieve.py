"""Search the policy index on the English rewrite. Hybrid RRF; cosine floor."""
from __future__ import annotations

from functools import lru_cache

from .. import tracing
from ..config import settings
from ..contracts import Chunk
from . import embed
from .store import LocalStore, SupabaseStore

# calibrated on the retrieval eval; English covered questions must pass.
DEFAULT_FLOOR = 0.80


@lru_cache(maxsize=1)
def _store() -> LocalStore:
    return LocalStore().load()


@lru_cache(maxsize=1)
def _supabase() -> SupabaseStore | None:
    if not settings.supabase_db_url:
        return None
    try:
        return SupabaseStore()
    except Exception:  # noqa: BLE001
        return None


@tracing.traceable(name="policy_retrieval", run_type="retriever")
def search(english_query: str, doc_id: str | None = None, version: str | None = None,
           k: int = 5, floor: float | None = None) -> list[Chunk]:
    qvec = embed.embed_query(english_query)
    hits = None
    sb = _supabase()
    if sb is not None and qvec is not None:
        try:
            hits = sb.search(english_query, qvec, doc_id=doc_id, version=version, k=k)
        except Exception as e:  # noqa: BLE001  (timeout / network) -> local fallback
            print(f"WARNING: Supabase retrieval failed ({e}); using local store")
            hits = None
    if hits is None:
        hits = _store().search(english_query, qvec, doc_id=doc_id, version=version, k=k)
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
