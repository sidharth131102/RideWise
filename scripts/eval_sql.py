"""NL->SQL eval vs gold queries, on the SAME scoped DB. LLM outage => SKIP.

Compares results, not SQL text: scalar (first numeric cell) or idset (the set
of id-like values). Run:  python scripts/eval_sql.py [--delay 1.0]
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ridewise import db_scope as ds  # noqa: E402
from ridewise.config import settings  # noqa: E402
from ridewise.contracts import Session  # noqa: E402
from ridewise.sql_tool import answer_question, run_query, validate_sql  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sql_eval.yaml"
_ID_RE = re.compile(r"\b(?:B-\d{3,4}|CUST\d{4}|PAY\d{5}|VEH\d{3}|DMG\d{4})\b")


def _first_number(rows: list[dict]):
    for r in rows:
        for v in r.values():
            if isinstance(v, (int, float)):
                return round(float(v), 2)
    return None


def _id_set(rows: list[dict]) -> set[str]:
    out = set()
    for r in rows:
        for v in r.values():
            if isinstance(v, str) and _ID_RE.fullmatch(v):
                out.add(v)
    return out


def _compare(kind: str, gold_rows, pred_rows) -> bool:
    if kind == "scalar":
        g, p = _first_number(gold_rows), _first_number(pred_rows)
        return g is not None and p is not None and abs(g - p) <= 0.01
    if kind == "idset":
        return _id_set(gold_rows) == _id_set(pred_rows) and len(_id_set(gold_rows)) > 0
    return False


def _session(scope: str) -> Session:
    if scope == "agent":
        return Session(role="agent")
    return Session(role="customer", customer_id=scope)


def run_block(name: str, cases: list[dict], default_scope: str, delay: float):
    passed = failed = skipped = 0
    fails = []
    for c in cases:
        scope = c.get("scope", default_scope)
        sc = ds.build(_session(scope), settings.db_path)
        try:
            gold_rows = run_query(sc, validate_sql(c["gold"], sc.schema)).rows
            res = answer_question(sc, c["q"])
            if res.error and res.error.startswith("LLM_UNAVAILABLE"):
                skipped += 1
                print(f"  SKIP  [{scope}] {c['q']}  (LLM unavailable)")
                continue
            ok = not res.error and _compare(c["kind"], gold_rows, res.rows)
            if ok:
                passed += 1
            else:
                failed += 1
                fails.append((scope, c["q"], res.sql, res.error))
        finally:
            sc.close()
        if delay:
            time.sleep(delay)
    print(f"\n[{name}] passed={passed} failed={failed} skipped={skipped} "
          f"of {len(cases)}")
    for scope, q, sql, err in fails:
        print(f"  FAIL [{scope}] {q}\n       sql: {sql}\n       err: {err}")
    return passed, failed, skipped


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between calls (rate limit)")
    args = ap.parse_args()

    data = yaml.safe_load(FIX.read_text(encoding="utf-8"))
    tp = tf = tsk = 0
    for block, default_scope in [("agent", "agent"), ("customer", "customer")]:
        p, f, s = run_block(block, data[block], default_scope, args.delay)
        tp += p; tf += f; tsk += s
    total = tp + tf + tsk
    print(f"\n==== TOTAL: {tp}/{total} passed, {tf} failed, {tsk} skipped ====")
    if tp + tf:
        print(f"accuracy on answered: {tp/(tp+tf):.1%}")


if __name__ == "__main__":
    main()
