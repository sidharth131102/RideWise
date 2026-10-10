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


class SupabaseStore:
    """Postgres + pgvector store with the same hybrid (RRF) search, via the
    match_policy_chunks() SQL function. Poolers reject server-side prepared
    statements, so prepare_threshold is disabled."""

    def __init__(self, dsn: str | None = None, statement_timeout_ms: int = 2000) -> None:
        self.dsn = dsn or settings.supabase_db_url
        self.statement_timeout_ms = statement_timeout_ms
        if not self.dsn:
            raise ValueError("SUPABASE_DB_URL is not set")

    def _connect(self):
        import psycopg
        from pgvector.psycopg import register_vector
        conn = psycopg.connect(
            self.dsn, prepare_threshold=None, connect_timeout=5,
            options=f"-c statement_timeout={self.statement_timeout_ms}")
        register_vector(conn)
        return conn

    def upsert(self, chunks: list[dict], embeddings) -> None:
        if embeddings is None:
            raise ValueError("Supabase store requires embeddings")
        import numpy as np
        rows = []
        for c, vec in zip(chunks, embeddings):
            rows.append((c["id"], c["doc_id"], c["title"],
                         str(c.get("version")) if c.get("version") is not None else None,
                         str(c.get("effective_date")) if c.get("effective_date") else None,
                         int(c.get("page", 0)), c.get("section"), c["content"],
                         c.get("display_text", c["content"]), c.get("source_type", "pdf"),
                         np.asarray(vec, dtype=np.float32)))
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany("""
                insert into policy_chunks
                  (id, doc_id, title, version, effective_date, page, section,
                   content, display_text, source_type, embedding)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict (id) do update set
                  doc_id=excluded.doc_id, title=excluded.title, version=excluded.version,
                  effective_date=excluded.effective_date, page=excluded.page,
                  section=excluded.section, content=excluded.content,
                  display_text=excluded.display_text, source_type=excluded.source_type,
                  embedding=excluded.embedding
            """, rows)
            # delete stale ids for re-ingested docs
            keep = [c["id"] for c in chunks]
            doc_ids = sorted({c["doc_id"] for c in chunks})
            cur.execute(
                "delete from policy_chunks where doc_id = any(%s) and not (id = any(%s))",
                (doc_ids, keep))
            conn.commit()

    def count(self) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("select count(*) from policy_chunks")
            return cur.fetchone()[0]

    def search(self, query: str, qvec, doc_id: str | None = None,
               version: str | None = None, k: int = 5) -> list[Chunk]:
        if qvec is None:
            raise ValueError("Supabase search requires a query embedding")
        import numpy as np
        qv = np.asarray(qvec, dtype=np.float32)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "select id, doc_id, title, version, effective_date, page, section, "
                "content, display_text, source_type, rrf_score, cosine "
                "from match_policy_chunks(%s,%s,%s,%s,%s)",
                (qv, query, doc_id, version, k))
            rows = cur.fetchall()
        out = []
        for r in rows:
            out.append(Chunk(
                id=r[0], doc_id=r[1], title=r[2], version=r[3], effective_date=r[4],
                page=r[5], section=r[6], text=r[7], display_text=r[8],
                source_type=r[9], score=float(r[11] or 0.0)))
        return out
