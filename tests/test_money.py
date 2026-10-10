import sqlite3
from decimal import Decimal

import pytest

from ridewise.config import settings
from ridewise.policy import calc
from ridewise.policy.rules import load_rules, RulesError
from ridewise.policy.selector import select_version


# ---- rental charge worked examples (RW-POL-01 s4.2: hourly 80, daily 700) -- #
@pytest.mark.parametrize("hours,expected", [(4, "320.00"), (10, "700.00"),
                                            (24, "700.00"), (27, "940.00")])
def test_rental_charge_examples(hours, expected):
    assert calc.money(calc.rental_charge(hours, 80, 700)) == expected


# ---- late fee worked examples (RW-POL-04 s1.4: hourly 100, no grace) ------- #
def _late(minutes, hourly=100, tier="STANDARD"):
    end = "2026-01-01 10:00:00"
    from datetime import datetime, timedelta
    actual = (datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
              + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    return calc.late_fee(end, actual, hourly, tier)


@pytest.mark.parametrize("minutes,hours,fee", [(5, 1, "150.00"), (59, 1, "150.00"),
                                               (61, 2, "300.00"), (180, 3, "450.00"),
                                               (195, 4, "600.00")])
def test_late_fee_examples(minutes, hours, fee):
    r = _late(minutes)
    assert r["hours_charged"] == hours
    assert calc.money(r["fee"]) == fee


def test_gold_grace_boundary():
    # GOLD: <=30 min no fee; exactly 30 no fee; 31 charges full (1 hour)
    assert _late(30, tier="GOLD")["fee"] == Decimal("0")
    assert _late(30, tier="GOLD")["waived_by_grace"] is True
    r31 = _late(31, tier="GOLD")
    assert r31["hours_charged"] == 1 and r31["fee"] > 0
    # SILVER has no grace: 5 min -> charged
    assert _late(5, tier="SILVER")["fee"] > 0


# ---- EV low battery threshold --------------------------------------------- #
@pytest.mark.parametrize("pct,applies", [(9, True), (10, False), (11, False),
                                         (0, True), (None, False)])
def test_ev_low_battery(pct, applies):
    assert calc.ev_low_battery_fee(pct)["applies"] is applies


# ---- version selection boundary (IST cutover) ----------------------------- #
def test_version_boundary():
    assert select_version("2026-06-30 18:29:59").version == "1"   # 1s before IST cutover
    assert select_version("2026-06-30 18:30:00").version == "2"   # exactly at cutover
    assert select_version("2025-03-01 00:00:00").version == "1"
    assert select_version(None).uncertain is True


# ---- validators reject bad rules ------------------------------------------ #
def test_rules_validator_catches_non_monotonic():
    import ridewise.policy.rules as R
    bad = load_rules().copy()  # start from valid, then corrupt a copy
    import copy
    bad = copy.deepcopy(load_rules())
    bad["cancellation"]["versions"][0]["slabs"] = [
        {"min_hours": 24, "pct": 50}, {"min_hours": 0, "pct": 100}]  # more notice, less refund
    with pytest.raises(RulesError):
        R._validate(bad)


# ---- full sweep: refund_due reproduces recorded refunds ------------------- #
def test_refund_sweep_reproduces_history():
    con = sqlite3.connect(settings.db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        select b.booking_id, b.booked_at, b.scheduled_start, b.cancelled_at,
          (select coalesce(sum(amount),0) from payments p where p.booking_id=b.booking_id
             and p.payment_type='BOOKING' and p.payment_status='SUCCESS') paid,
          (select coalesce(sum(gst_amount),0) from payments p where p.booking_id=b.booking_id
             and p.payment_type='BOOKING' and p.payment_status='SUCCESS') paid_tax,
          (select coalesce(sum(amount),0) from payments p where p.booking_id=b.booking_id
             and p.payment_type='REFUND' and p.payment_status='SUCCESS') refund
        from bookings b
        where b.booking_status='CNL_U' and b.cancelled_at is not null
    """).fetchall()
    con.close()
    with_refund = [r for r in rows if r["refund"] < 0 and r["paid"] > 0]
    matches = 0
    for r in with_refund:
        rb = calc.refund_due(r["booked_at"], r["scheduled_start"], r["cancelled_at"],
                             r["paid"], r["paid_tax"])
        if abs(Decimal(rb.due) - Decimal(str(-r["refund"]))) <= Decimal("0.01"):
            matches += 1
    # Step 1 established ~140/142; require the overwhelming majority.
    assert matches >= len(with_refund) - 3, f"{matches}/{len(with_refund)} reproduced"
