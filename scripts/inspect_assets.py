"""Step 1 - Discover and verify the assets (no app code).

Prints:
  - schema (tables, FKs, row counts, samples)
  - categorical value distributions
  - timestamp ranges / formats
  - payment sign conventions, statuses, duplicates, GST rate check
  - free-text PII and injection-like text scan
  - login-identity uniqueness (email / phone)
  - PDF per-page text/headings + flagged image regions (rendered to PNG)
  - RULE SWEEPS: which timestamp decides the cancellation version,
    cutover timezone, late-fee reproduction, rounding convention.

Run:  python scripts/inspect_assets.py
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "ridewise.db"
DOCS = ROOT / "data"
IMG_OUT = ROOT / "data" / "image_regions"

# IST = UTC + 5:30. The v2 cutover is "1 July 2026 00:00 IST".
IST_OFFSET_SECONDS = 5 * 3600 + 30 * 60
V2_CUTOVER_IST = "2026-07-01 00:00:00"
V2_CUTOVER_UTC = "2026-06-30 18:30:00"  # same instant, UTC

LINE = "=" * 78


def h(title: str) -> None:
    print(f"\n{LINE}\n{title}\n{LINE}")


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
def inspect_db(con: sqlite3.Connection) -> None:
    cur = con.cursor()
    tables = [r[0] for r in cur.execute(
        "select name from sqlite_master where type='table' order by name")]

    h("SCHEMA")
    for t in tables:
        n = cur.execute(f'select count(*) from "{t}"').fetchone()[0]
        print(f"\n-- {t} ({n} rows) --")
        for cid, name, ctype, notnull, dflt, pk in cur.execute(
                f'PRAGMA table_info("{t}")'):
            flags = []
            if pk:
                flags.append("PK")
            if notnull:
                flags.append("NOT NULL")
            print(f"   {name:20} {ctype:14} {' '.join(flags)}")
        fks = list(cur.execute(f'PRAGMA foreign_key_list("{t}")'))
        for fk in fks:
            print(f"   FK: {fk[3]} -> {fk[2]}.{fk[4]}")
        print("   sample rows:")
        cols = [d[0] for d in cur.execute(f'select * from "{t}" limit 3').description]
        for row in cur.execute(f'select * from "{t}" limit 3'):
            print("     ", dict(zip(cols, row)))

    h("CATEGORICAL VALUES")
    cat_cols = {
        "customers": ["city", "kyc_status", "customer_tier"],
        "vehicles": ["vehicle_type", "hub_name", "status"],
        "bookings": ["booking_status"],
        "payments": ["payment_type", "payment_method", "payment_status"],
        "damage_reports": ["reported_by", "damage_category", "severity", "claim_status"],
    }
    for t, cols in cat_cols.items():
        for c in cols:
            dist = dict(cur.execute(
                f'select "{c}", count(*) from "{t}" group by "{c}" order by 2 desc'))
            print(f"   {t}.{c}: {dist}")

    h("TIMESTAMPS (min / max)")
    ts_cols = {
        "customers": ["created_at", "date_of_birth"],
        "vehicles": ["commissioned_on"],
        "bookings": ["booked_at", "scheduled_start", "scheduled_end",
                     "actual_return_at", "cancelled_at"],
        "payments": ["paid_at"],
        "damage_reports": ["reported_at"],
    }
    for t, cols in ts_cols.items():
        for c in cols:
            lo, hi = cur.execute(
                f'select min("{c}"), max("{c}") from "{t}"').fetchone()
            print(f"   {t}.{c}: {lo}  ..  {hi}")

    h("PAYMENTS: sign conventions, statuses, duplicates, GST check")
    print("   amount sign by payment_type:")
    for ptype, mn, mx, avg in cur.execute(
            "select payment_type, min(amount), max(amount), round(avg(amount),2) "
            "from payments group by payment_type"):
        print(f"     {ptype:10} min={mn:>10} max={mx:>10} avg={avg}")
    print("   status x type counts:")
    for row in cur.execute(
            "select payment_type, payment_status, count(*) from payments "
            "group by 1,2 order by 1,2"):
        print("     ", row)
    dup = cur.execute(
        "select transaction_ref, count(*) c from payments "
        "where transaction_ref is not null group by 1 having c>1").fetchall()
    print(f"   duplicate transaction_ref groups: {len(dup)}")
    # GST rate check (expect ~18% of amount for positive, success rows)
    gst_rows = cur.execute(
        "select amount, gst_amount from payments "
        "where amount>0 and gst_amount is not null and payment_status='SUCCESS'"
    ).fetchall()
    exact18 = sum(1 for a, g in gst_rows
                  if a and abs(Decimal(str(g)) - (Decimal(str(a)) * Decimal("0.18"))
                              .quantize(Decimal("0.01"), ROUND_HALF_UP)) <= Decimal("0.01"))
    print(f"   GST=18% half-up within ₹0.01: {exact18}/{len(gst_rows)} rows")
    # deposit refund presence
    dep = cur.execute("select count(*) from payments where payment_type='DEPOSIT'").fetchone()[0]
    print(f"   DEPOSIT rows: {dep}  (note: deposit *returns* are NOT in payments per policy 5.3)")

    h("FREE-TEXT: PII + injection scan (payments.remarks, damage_reports.description)")
    phone_re = re.compile(r"\b\d{10}\b")
    email_re = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    inj_re = re.compile(r"ignore (previous|above)|system prompt|you are now|disregard",
                        re.I)
    for t, c in [("payments", "remarks"), ("damage_reports", "description")]:
        texts = [r[0] for r in cur.execute(f'select "{c}" from "{t}" where "{c}" is not null')]
        phones = sum(bool(phone_re.search(x)) for x in texts)
        emails = sum(bool(email_re.search(x)) for x in texts)
        injs = [x for x in texts if inj_re.search(x)]
        print(f"   {t}.{c}: {len(texts)} values | phones~{phones} emails~{emails} "
              f"injection-like={len(injs)}")
        for x in injs[:5]:
            print(f"       INJECTION-LIKE: {x!r}")
    # distinct remark templates
    rem = Counter(r[0] for r in cur.execute(
        "select remarks from payments where remarks is not null"))
    print("   top remarks:", rem.most_common(8))

    h("LOGIN IDENTITY uniqueness")
    for col in ["email", "phone"]:
        total, distinct = cur.execute(
            f"select count({col}), count(distinct {col}) from customers").fetchone()
        print(f"   customers.{col}: {distinct} distinct / {total} -> "
              f"{'UNIQUE' if total == distinct else 'NOT UNIQUE'}")


# --------------------------------------------------------------------------- #
# Rule sweeps  (the single most valuable check)
# --------------------------------------------------------------------------- #
def to_ist(utc_text: str) -> str:
    """Shift a 'YYYY-MM-DD HH:MM:SS' UTC string by +5:30, text-only."""
    from datetime import datetime, timedelta
    dt = datetime.strptime(utc_text, "%Y-%m-%d %H:%M:%S") + timedelta(seconds=IST_OFFSET_SECONDS)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def hours_between(a_utc: str, b_utc: str) -> float:
    from datetime import datetime
    da = datetime.strptime(a_utc, "%Y-%m-%d %H:%M:%S")
    db = datetime.strptime(b_utc, "%Y-%m-%d %H:%M:%S")
    return (db - da).total_seconds() / 3600.0


# refund % schedules (from the PDFs; v2 table is the scanned Annexure 1)
V1 = [(24, 100), (6, 50), (0, 0)]
V2 = [(48, 100), (12, 75), (2, 25), (0, 0)]


def refund_pct(schedule, hours_before_pickup: float) -> int:
    for threshold, pct in schedule:
        if hours_before_pickup >= threshold:
            return pct
    return 0


def rule_sweeps(con: sqlite3.Connection) -> None:
    cur = con.cursor()
    h("RULE SWEEP 1: which timestamp decides the cancellation VERSION?")
    # Customer-cancelled bookings that actually had a REFUND payment.
    rows = cur.execute("""
        select b.booking_id, b.booked_at, b.scheduled_start, b.cancelled_at,
               (select coalesce(sum(amount),0) from payments p
                  where p.booking_id=b.booking_id and p.payment_type='BOOKING'
                        and p.payment_status='SUCCESS') as rental_paid,
               (select coalesce(sum(amount),0) from payments p
                  where p.booking_id=b.booking_id and p.payment_type='REFUND'
                        and p.payment_status='SUCCESS') as refund_amt
        from bookings b
        where b.booking_status='CNL_U' and b.cancelled_at is not null
    """).fetchall()

    candidates = {"booked_at": 1, "scheduled_start": 2, "cancelled_at": 3}
    # For each candidate "deciding timestamp", test both cutover interpretations.
    for cutover_label, cutover_utc in [("IST-correct (2026-06-30 18:30 UTC)", V2_CUTOVER_UTC),
                                       ("naive UTC midnight (2026-07-01 00:00)", "2026-07-01 00:00:00")]:
        print(f"\n  -- cutover = {cutover_label} --")
        for cand, idx in candidates.items():
            matches = mism = usable = 0
            for bid, booked, sched, canc, paid, refund in rows:
                if not paid or paid <= 0 or refund >= 0 and refund == 0:
                    pass
                deciding = {"booked_at": booked, "scheduled_start": sched,
                            "cancelled_at": canc}[cand]
                if deciding is None:
                    continue
                schedule = V2 if deciding >= cutover_utc else V1
                hrs = hours_between(canc, sched)
                exp_pct = refund_pct(schedule, hrs)
                exp_refund = (Decimal(str(paid)) * Decimal(exp_pct) / Decimal(100)
                              ).quantize(Decimal("0.01"), ROUND_HALF_UP)
                actual_refund = Decimal(str(-refund))  # refunds negative
                if paid and paid > 0:
                    usable += 1
                    if abs(exp_refund - actual_refund) <= Decimal("0.01"):
                        matches += 1
                    else:
                        mism += 1
            print(f"     deciding={cand:16} matches={matches:4}  mismatches={mism:4}  (of {usable})")

    h("RULE SWEEP 2: distribution of bookings each side of the cutover")
    for label, cutoff in [("IST-correct cutover", V2_CUTOVER_UTC),
                          ("naive UTC midnight", "2026-07-01 00:00:00")]:
        v1n = cur.execute("select count(*) from bookings where booked_at < ?", (cutoff,)).fetchone()[0]
        v2n = cur.execute("select count(*) from bookings where booked_at >= ?", (cutoff,)).fetchone()[0]
        print(f"   {label}: v1(before)={v1n}  v2(on/after)={v2n}")
    # Bookings in the 18:30-wide UTC gap that flip between the two interpretations
    gap = cur.execute(
        "select count(*) from bookings where booked_at >= ? and booked_at < ?",
        (V2_CUTOVER_UTC, "2026-07-01 00:00:00")).fetchone()[0]
    print(f"   bookings in the IST/UTC gap (would be misclassified by naive UTC): {gap}")

    h("RULE SWEEP 3: late-fee reproduction vs recorded PENALTY rows")
    # late fee = ceil(late_hours) * 1.5 * hourly_rate ; GOLD gets 30 min grace.
    import math
    rows = cur.execute("""
        select b.booking_id, b.scheduled_end, b.actual_return_at,
               v.hourly_rate, c.customer_tier,
               (select coalesce(sum(amount),0) from payments p
                  where p.booking_id=b.booking_id and p.payment_type='PENALTY'
                        and p.payment_status='SUCCESS') as penalty_paid
        from bookings b
        join vehicles v on v.vehicle_id=b.vehicle_id
        join customers c on c.customer_id=b.customer_id
        where b.actual_return_at is not null and b.scheduled_end is not null
          and b.actual_return_at > b.scheduled_end
    """).fetchall()
    repro = off = 0
    examples = []
    for bid, sched_end, actual, rate, tier, penalty in rows:
        late_min = hours_between(sched_end, actual) * 60
        grace = 30 if tier == "GOLD" else 0
        if late_min <= grace:
            exp_fee = Decimal("0")
        else:
            late_hours = math.ceil(late_min / 60)  # part-hour rounds up
            exp_fee = (Decimal(late_hours) * Decimal("1.5") * Decimal(str(rate))
                       ).quantize(Decimal("0.01"), ROUND_HALF_UP)
        # penalty rows may bundle damage + low-battery; so only flag when fee>penalty
        if penalty and penalty > 0:
            if abs(Decimal(str(penalty)) - exp_fee) <= Decimal("0.01"):
                repro += 1
            else:
                off += 1
                if len(examples) < 6:
                    examples.append((bid, round(late_min, 1), tier, float(exp_fee), penalty))
    print(f"   late penalties exactly reproduced by late-fee alone: {repro}")
    print(f"   penalties that differ (likely bundle damage/low-battery): {off}")
    for e in examples:
        print(f"       {e[0]}: late_min={e[1]} tier={e[2]} exp_latefee={e[3]} recorded_penalty={e[4]}")

    h("RULE SWEEP 4: rounding convention on GST (round() vs half-up)")
    rows = cur.execute(
        "select amount, gst_amount from payments "
        "where amount>0 and gst_amount is not null limit 2000").fetchall()
    halfup = pybank = 0
    for a, g in rows:
        a, g = Decimal(str(a)), Decimal(str(g))
        hu = (a * Decimal("0.18")).quantize(Decimal("0.01"), ROUND_HALF_UP)
        bk = (a * Decimal("0.18")).quantize(Decimal("0.01"))  # banker's/half-even default
        if abs(hu - g) <= Decimal("0.005"):
            halfup += 1
        if abs(bk - g) <= Decimal("0.005"):
            pybank += 1
    print(f"   half-up matches: {halfup}/{len(rows)}   half-even matches: {pybank}/{len(rows)}")


# --------------------------------------------------------------------------- #
# PDFs
# --------------------------------------------------------------------------- #
def inspect_pdfs() -> None:
    import pymupdf  # noqa
    h("PDFs: pages, headings, version lines, IMAGE REGIONS")
    IMG_OUT.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(DOCS.glob("*.pdf"))
    ver_re = re.compile(r"(Version|v)\s*[\d.]+|Effective\s+\d|RW-POL-\d+", re.I)
    for pdf in pdfs:
        doc = pymupdf.open(pdf)
        print(f"\n-- {pdf.name} ({doc.page_count} pages) --")
        for pno in range(doc.page_count):
            page = doc[pno]
            text = page.get_text()
            pw, ph = page.rect.width, page.rect.height
            page_area = pw * ph
            # image regions
            flagged = []
            for img in page.get_image_info():
                x0, y0, x1, y1 = img["bbox"]
                w, hgt = x1 - x0, y1 - y0
                area_frac = (w * hgt) / page_area
                # ignore small top-of-page logos
                is_logo = y1 < 90 and w < 220
                if (w >= 300 or area_frac >= 0.15) and not is_logo:
                    flagged.append((round(x0), round(y0), round(x1), round(y1),
                                    round(area_frac, 2)))
            ver = [m.group(0) for m in ver_re.finditer(text)]
            headings = [ln.strip() for ln in text.splitlines()
                        if re.match(r"^\s*(\d+\.|Annexure|Appendix)", ln.strip())][:8]
            print(f"   p{pno+1}: chars={len(text):4} ver_lines={sorted(set(ver))[:4]}")
            if headings:
                print(f"        headings: {headings}")
            if flagged:
                print(f"        *** IMAGE REGIONS: {flagged}")
                for i, (x0, y0, x1, y1, af) in enumerate(flagged):
                    clip = pymupdf.Rect(x0, y0, x1, y1)
                    pm = page.get_pixmap(dpi=150, clip=clip)
                    out = IMG_OUT / f"{pdf.stem}_p{pno+1}_{i}.png"
                    pm.save(out)
                    print(f"            rendered -> {out.relative_to(ROOT)}")
        doc.close()


def main() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if not DB.exists():
        sys.exit(f"DB not found: {DB}")
    con = sqlite3.connect(DB)
    inspect_db(con)
    rule_sweeps(con)
    con.close()
    inspect_pdfs()
    print("\nDONE.")


if __name__ == "__main__":
    main()
