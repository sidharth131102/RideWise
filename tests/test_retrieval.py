"""Retrieval tests. Requires a built index (python -m ridewise.rag.ingest)."""
import pytest

from ridewise.rag import retrieve
from ridewise.rag.store import LocalStore


@pytest.fixture(scope="module")
def store():
    try:
        return LocalStore().load()
    except FileNotFoundError:
        pytest.skip("index not built; run python -m ridewise.rag.ingest")


def test_index_has_both_transcriptions(store):
    tr = [c for c in store.chunks if c["source_type"] == "transcription"]
    assert len(tr) == 2
    blob = " ".join(c["display_text"] for c in tr)
    assert "75%" in blob and "48 hours" in blob      # v2 refund schedule
    assert "30 minutes" in blob                       # GOLD grace


def test_v2_refund_schedule_retrieved(store):
    hits = retrieve.search("version 2 cancellation refund schedule percentages", k=5)
    joined = " ".join(h.display_text for h in hits)
    assert "75%" in joined or "48 hours" in joined


def test_gold_grace_retrieved(store):
    hits = retrieve.search("late return grace period for gold tier customers", k=5)
    assert any("30 minutes" in h.display_text for h in hits)


def test_version_filter_does_not_leak(store):
    v1 = retrieve.search("cancellation refund schedule", version="1", k=5)
    v2 = retrieve.search("cancellation refund schedule", version="2", k=5)
    assert all(h.version in (None, "1") for h in v1)
    assert all(h.version in (None, "2") for h in v2)


def test_hubs_question(store):
    hits = retrieve.search("where are your hubs located", k=5)
    joined = " ".join(h.display_text for h in hits).lower()
    assert "koramangala" in joined or "hub" in joined


def test_unrelated_drops_with_floor(store):
    hits = retrieve.search("do you rent cars or sell airline tickets",
                           k=5, floor=retrieve.DEFAULT_FLOOR)
    # clearly unrelated -> should be empty (or at least not confidently matched)
    assert hits == [] or all(h.score < 0.85 for h in hits)
