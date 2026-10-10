"""Local hybrid store: numpy cosine + BM25, fused with RRF.

This is the default (no external service). A SupabaseStore with the same
hybrid interface can be added later; retrieval falls back here if it is slow.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from ..config import settings
from ..contracts import Chunk

RRF_K = 60
_STOP = set("a an the of to for and or is are be on in at by with from this that your you "
            "what how where when which do does can could will would it its as".split())
_TOK = re.compile(r"[a-z0-9%]+")


def tokenize(text: str) -> list[str]:
    return [t for t in _TOK.findall(text.lower()) if t not in _STOP and len(t) > 1]


class LocalStore:
    def __init__(self) -> None:
        self.chunks: list[dict] = []
        self.embeddings: np.ndarray | None = None
        self.bm25: BM25Okapi | None = None

    @property
    def jsonl(self) -> Path:
        return settings.index_dir / "chunks.jsonl"

    @property
    def npy(self) -> Path:
        return settings.index_dir / "embeddings.npy"

    def write(self, chunks: list[dict], embeddings: np.ndarray | None) -> None:
        settings.index_dir.mkdir(parents=True, exist_ok=True)
        with open(self.jsonl, "w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        if embeddings is not None:
            np.save(self.npy, embeddings)
        elif self.npy.exists():
            self.npy.unlink()

    def load(self) -> "LocalStore":
        if not self.jsonl.exists():
            raise FileNotFoundError(f"index not found: {self.jsonl} (run ingest)")
        self.chunks = [json.loads(ln) for ln in self.jsonl.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.embeddings = np.load(self.npy) if self.npy.exists() else None
        self.bm25 = BM25Okapi([tokenize(c["content"]) for c in self.chunks])
        return self

    def search(self, query: str, qvec: np.ndarray | None,
               doc_id: str | None = None, version: str | None = None,
               k: int = 5) -> list[Chunk]:
        idxs = [i for i, c in enumerate(self.chunks)
                if (doc_id is None or c["doc_id"] == doc_id)
                and (version is None or str(c.get("version")) == str(version))]
        if not idxs:
            idxs = list(range(len(self.chunks)))

        # dense ranks
        dense_rank: dict[int, int] = {}
        cosine: dict[int, float] = {}
        if qvec is not None and self.embeddings is not None:
            sub = self.embeddings[idxs]
            sims = sub @ qvec
            order = np.argsort(-sims)
            for rank, pos in enumerate(order):
                gi = idxs[pos]
                dense_rank[gi] = rank
                cosine[gi] = float(sims[pos])

        # sparse ranks (BM25 over the filtered subset)
        sparse_rank: dict[int, int] = {}
        if self.bm25 is not None:
            q_tokens = tokenize(query)
            scores = self.bm25.get_scores(q_tokens)
            order = sorted(idxs, key=lambda gi: -scores[gi])
            for rank, gi in enumerate(order):
                sparse_rank[gi] = rank

        # RRF fuse
        fused: dict[int, float] = {}
        for gi in set(dense_rank) | set(sparse_rank):
            s = 0.0
            if gi in dense_rank:
                s += 1.0 / (RRF_K + dense_rank[gi])
            if gi in sparse_rank:
                s += 1.0 / (RRF_K + sparse_rank[gi])
            fused[gi] = s
        top = sorted(fused, key=lambda gi: -fused[gi])[:k]

        out: list[Chunk] = []
        for gi in top:
            c = self.chunks[gi]
            out.append(Chunk(
                id=c["id"], doc_id=c["doc_id"], title=c["title"],
                version=str(c.get("version")) if c.get("version") is not None else None,
                effective_date=c.get("effective_date"), page=c.get("page", 0),
                section=c.get("section"), text=c["content"],
                display_text=c.get("display_text", c["content"]),
                score=cosine.get(gi, 0.0), source_type=c.get("source_type", "pdf")))
        return out
