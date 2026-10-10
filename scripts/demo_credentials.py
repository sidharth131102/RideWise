"""Print a few real customer IDs from the DB for demoing (read at run time;
no credentials are committed). Run: python scripts/demo_credentials.py"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ridewise.config import settings  # noqa: E402


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    con = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    print("Sample customers to sign in as (enter the customer_id in the UI):\n")
    rows = con.execute("""
        select c.customer_id, c.full_name, c.customer_tier, c.kyc_status,
               (select count(*) from bookings b where b.customer_id=c.customer_id) nb,
               (select count(*) from bookings b where b.customer_id=c.customer_id
                  and b.booking_status='CNL_U') ncnl
        from customers c order by nb desc limit 8
    """).fetchall()
    for r in rows:
        print(f"  {r['customer_id']}  {r['full_name']:20} tier={r['customer_tier']:8} "
              f"kyc={r['kyc_status']:8} bookings={r['nb']:<3} cancellations={r['ncnl']}")
    print("\nFor a support-agent session, just choose 'Support agent' in the UI.")
    con.close()


if __name__ == "__main__":
    main()
