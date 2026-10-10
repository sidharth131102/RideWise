"""Build the policy index: chunks.jsonl + embeddings.npy.

Run:  python -m ridewise.rag.ingest
"""
from __future__ import annotations

from dataclasses import asdict

from . import embed
from .chunker import build_all_chunks
from .store import LocalStore


def main() -> None:
    chunks = build_all_chunks()
    dicts = [asdict(c) for c in chunks]
    for d in dicts:
        d.pop("extra", None)
    texts = [c.content for c in chunks]
    vecs = embed.embed_passages(texts)
    store = LocalStore()
    store.write(dicts, vecs)
    n_tr = sum(1 for c in chunks if c.source_type == "transcription")
    print(f"ingested {len(chunks)} chunks "
          f"({n_tr} transcription, {len(chunks)-n_tr} pdf) | "
          f"embeddings: {'yes' if vecs is not None else 'NO (FTS/BM25 only)'}")
    print(f"wrote {store.jsonl}")


if __name__ == "__main__":
    main()
