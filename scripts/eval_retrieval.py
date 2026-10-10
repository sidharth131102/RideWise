"""Retrieval eval: hit@5 / MRR for dense / FTS / hybrid + score distributions
and a cosine-floor recommendation.

Run:  python scripts/eval_retrieval.py
"""
from __future__ import annotations

import statistics as stats
import sys
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ridewise.rag import embed  # noqa: E402
from ridewise.rag.store import LocalStore, tokenize, RRF_K  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "retrieval_eval.yaml"


def _accept(doc, expected) -> bool:
    exp = expected if isinstance(expected, list) else [expected]
    return doc in exp


def _ranks_dense(store, qvec):
    sims = store.embeddings @ qvec
    order = np.argsort(-sims)
    return order, sims


def _ranks_fts(store, query):
    scores = store.bm25.get_scores(tokenize(query))
    order = sorted(range(len(store.chunks)), key=lambda i: -scores[i])
    return order


def _hit_mrr(order_idx, store, expected, k=5):
    for rank, gi in enumerate(order_idx[:k]):
        if _accept(store.chunks[gi]["doc_id"], expected):
            return 1, 1.0 / (rank + 1)
    return 0, 0.0


def _hybrid_order(store, query, qvec, k=5):
    hits = store.search(query, qvec, k=k)
    return [h.doc_id for h in hits], (hits[0].score if hits else 0.0)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    data = yaml.safe_load(FIX.read_text(encoding="utf-8"))
    store = LocalStore().load()
    if store.embeddings is None:
        print("WARNING: no embeddings; dense metrics will be 0 (FTS/BM25 only).")

    methods = {"dense": [0, 0.0], "fts": [0, 0.0], "hybrid": [0, 0.0]}
    covered_top1_cos, uncovered_top1_cos = [], []
    n = len(data["covered"])

    for item in data["covered"]:
        q, exp = item["q"], item["doc"]
        qvec = embed.embed_query(q)
        if store.embeddings is not None and qvec is not None:
            dorder, _ = _ranks_dense(store, qvec)
            h, m = _hit_mrr(dorder, store, exp)
            methods["dense"][0] += h; methods["dense"][1] += m
        forder = _ranks_fts(store, q)
        h, m = _hit_mrr(forder, store, exp)
        methods["fts"][0] += h; methods["fts"][1] += m
        # hybrid
        hits = store.search(q, qvec, k=5)
        hit = any(_accept(hh.doc_id, exp) for hh in hits[:5])
        mrr = next((1.0 / (r + 1) for r, hh in enumerate(hits[:5])
                    if _accept(hh.doc_id, exp)), 0.0)
        methods["hybrid"][0] += hit; methods["hybrid"][1] += mrr
        if hits:
            covered_top1_cos.append(hits[0].score)

    for q in data["uncovered"]:
        qvec = embed.embed_query(q)
        hits = store.search(q, qvec, k=5)
        if hits:
            uncovered_top1_cos.append(hits[0].score)

    print(f"\nRetrieval eval over {n} covered / {len(data['uncovered'])} uncovered\n")
    print(f"{'method':8} {'hit@5':>7} {'MRR':>7}")
    for name, (h, m) in methods.items():
        print(f"{name:8} {h/n:>7.2%} {m/n:>7.3f}")

    print("\nTop-1 cosine distribution:")
    if covered_top1_cos:
        print(f"  covered  : min={min(covered_top1_cos):.3f} "
              f"median={stats.median(covered_top1_cos):.3f} max={max(covered_top1_cos):.3f}")
    if uncovered_top1_cos:
        print(f"  uncovered: min={min(uncovered_top1_cos):.3f} "
              f"median={stats.median(uncovered_top1_cos):.3f} max={max(uncovered_top1_cos):.3f}")

    if covered_top1_cos and uncovered_top1_cos:
        lo_cov = min(covered_top1_cos)
        hi_unc = max(uncovered_top1_cos)
        print(f"\nFloor recommendation: covered-min={lo_cov:.3f}, uncovered-max={hi_unc:.3f}")
        if lo_cov > hi_unc:
            print(f"  -> clean separation; a floor around {(lo_cov + hi_unc) / 2:.2f} works.")
        else:
            print(f"  -> overlap; favour recall, set floor just below covered-min "
                  f"(~{lo_cov - 0.01:.2f}) and warn on low scores.")


if __name__ == "__main__":
    main()
