"""One OK/FAIL line per external service. Run: python scripts/check_services.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ridewise.config import settings  # noqa: E402


def check_llm() -> None:
    from ridewise.llm import get_llm, LLMUnavailable
    llm = get_llm()
    if not llm.configured:
        print("LLM:       SKIP (no LLM_API_KEY set)")
        return
    try:
        out = llm.chat_json("Reply with JSON only.", 'Return {"ok": true}.')
        print(f"LLM:       OK ({settings.llm_model}) -> {out}")
    except LLMUnavailable as e:
        print(f"LLM:       FAIL ({e})")


def check_embeddings() -> None:
    from ridewise.rag import embed
    if not settings.embeddings_enabled:
        print("Embeddings: SKIP (disabled -> FTS/BM25 only)")
        return
    print("Embeddings: OK" if embed.available() else "Embeddings: FAIL (will use FTS/BM25 only)")


def check_index() -> None:
    from ridewise.rag.store import LocalStore
    try:
        s = LocalStore().load()
        print(f"Index:     OK ({len(s.chunks)} chunks, "
              f"{'with embeddings' if s.embeddings is not None else 'FTS only'})")
    except FileNotFoundError:
        print("Index:     FAIL (run: python -m ridewise.rag.ingest)")


def check_web() -> None:
    if not settings.web_search_enabled:
        print("Web search: SKIP (disabled)")
        return
    from ridewise import web_search
    hits, reason = web_search.search("RideWise test")
    print("Web search: OK" if hits else f"Web search: FAIL ({reason})")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    check_llm()
    check_embeddings()
    check_index()
    check_web()


if __name__ == "__main__":
    main()
