"""Apply supabase/migrations/*.sql to the Supabase Postgres in SUPABASE_DB_URL.

Run:  python scripts/migrate_supabase.py
(Alternatively, paste the SQL into the Supabase dashboard SQL Editor.)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ridewise.config import settings  # noqa: E402

MIGRATIONS = Path(__file__).resolve().parents[1] / "supabase" / "migrations"


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if not settings.supabase_db_url:
        sys.exit("SUPABASE_DB_URL is not set in .env")
    import psycopg
    files = sorted(MIGRATIONS.glob("*.sql"))
    if not files:
        sys.exit(f"no migrations in {MIGRATIONS}")
    with psycopg.connect(settings.supabase_db_url, prepare_threshold=None,
                         connect_timeout=10) as conn:
        for f in files:
            sql = f.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
            print(f"applied {f.name}")
        with conn.cursor() as cur:
            cur.execute("select count(*) from policy_chunks")
            print(f"policy_chunks rows: {cur.fetchone()[0]}")
    print("migration complete. Now run: python -m ridewise.rag.ingest")


if __name__ == "__main__":
    main()
