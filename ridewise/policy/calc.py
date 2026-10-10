"""Deterministic money. Every rupee is computed here with Decimal.

eligible / due / processed are always kept as separate fields.
The LLM never does any of this arithmetic.
"""
from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from ..contracts import RefundBreakdown, RuleCitation
from .rules import load_rules
from .selector import select_version, version_entry

_FMT = "%Y-%m-%d %H:%M:%S"
CENT = Decimal("0.01")


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def _round(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


def money(v) -> str:
    return str(_round(_d(v)))


def minutes_between(a_utc: str, b_utc: str) -> float:
    da = datetime.strptime(a_utc, _FMT)
    db = datetime.strptime(b_utc, _FMT)
    return (db - da).total_seconds() / 60.0


# --------------------------------------------------------------------------- #
def gst(amount) -> Decimal:
    rate = Decimal(load_rules()["gst_rate"])
    return _round(_d(amount) * rate)


def rental_charge(hours: int, hourly_rate, daily_rate) -> Decimal:
    """Cheaper combination: full 24h blocks at daily; remaining hours at hourly,
    capped at one daily rate per remaining block (RW-POL-01 s4.1)."""
    hourly, daily = _d(hourly_rate), _d(daily_rate)
    days, rem = divmod(int(hours), 24)
    rem_charge = min(_d(rem) * hourly, daily)
    return _round(_d(days) * daily + rem_charge)


def late_fee(scheduled_end_utc: str, actual_return_utc: str,
             hourly_rate, tier: str) -> dict:
    """ceil(late_min/60) * 1.5 * hourly_rate, with tier grace (RW-POL-04)."""
    rules = load_rules()["late_fee"]
    grace = rules["grace_minutes"].get((tier or "STANDARD").upper(), 0)
    mult = Decimal(rules["multiplier"])
    late_min = minutes_between(scheduled_end_utc, actual_return_utc)
    if late_min <= 0:
        return {"late_minutes": 0, "hours_charged": 0, "fee": Decimal("0"),
                "waived_by_grace": False}
    if late_min <= grace:
        return {"late_minutes": round(late_min, 1), "hours_charged": 0,
                "fee": Decimal("0"), "waived_by_grace": True}
    hours_charged = math.ceil(late_min / 60)   # part-hour rounds up
    fee = _round(_d(hours_charged) * mult * _d(hourly_rate))
    return {"late_minutes": round(late_min, 1), "hours_charged": hours_charged,
            "fee": fee, "waived_by_grace": False}


def ev_low_battery_fee(return_battery_pct) -> dict:
    rules = load_rules()["ev_low_battery"]
    if return_battery_pct is None:
        return {"applies": False, "fee": Decimal("0"),
                "reason": "no return battery level recorded (non-EV or not returned)"}
    below = return_battery_pct < rules["threshold_pct"]
    return {"applies": below, "fee": _d(rules["fee"]) if below else Decimal("0"),
            "reason": f"return battery {return_battery_pct}% "
                      f"({'below' if below else 'at/above'} {rules['threshold_pct']}%)"}


def _canc_citation(v: dict) -> RuleCitation:
    return RuleCitation(doc=v["doc"], version=v["version"], page=v.get("page"),
                        section=v.get("section"), quote=v.get("quote", ""))


def refund_eligible_pct(version: str, hours_before_pickup: float) -> int:
    v = version_entry(version)
    if not v:
        return 0
    for slab in v["slabs"]:
        if hours_before_pickup >= slab["min_hours"]:
            return slab["pct"]
    return 0


def refund_due(booked_at_utc: str, scheduled_start_utc: str, cancelled_at_utc: str,
               amount_paid, tax_paid, processed_amount=0, processed_tax=0) -> RefundBreakdown:
    """Refund eligible/due/processed, kept separate. Version from booked_at."""
    decision = select_version(booked_at_utc)
    notes: list[str] = [decision.reason]
    if decision.uncertain or not decision.version:
        return RefundBreakdown(
            eligible_pct="0", due="0.00", due_tax="0.00",
            amount_paid=money(amount_paid), tax_paid=money(tax_paid),
            processed=money(-_d(processed_amount)), processed_tax=money(-_d(processed_tax)),
            outstanding="0.00", rule_citation=None,
            notes=notes + ["policy version uncertain; refund not computed"])

    v = version_entry(decision.version)
    if not cancelled_at_utc:
        hours_before = None
        notes.append("booking is not cancelled; refund would apply only on customer cancellation")
        pct = 0
    else:
        hours_before = minutes_between(cancelled_at_utc, scheduled_start_utc) / 60.0
        pct = refund_eligible_pct(decision.version, hours_before)
        notes.append(f"cancelled {hours_before:.1f}h before pickup -> {pct}% of rental charge "
                     f"(policy v{decision.version})")

    due = _round(_d(amount_paid) * Decimal(pct) / Decimal(100))
    due_tax = _round(_d(tax_paid) * Decimal(pct) / Decimal(100))
    processed = _round(-_d(processed_amount))      # refunds stored negative -> positive refunded
    processed_tax = _round(-_d(processed_tax))
    outstanding = _round(due - processed)
    if processed > 0 and outstanding > 0:
        notes.append(f"partially refunded; {money(outstanding)} still due")
    elif processed == 0 and due > 0:
        notes.append("eligible but no refund has been processed yet")
    return RefundBreakdown(
        eligible_pct=str(pct), due=money(due), due_tax=money(due_tax),
        amount_paid=money(amount_paid), tax_paid=money(tax_paid),
        processed=money(processed), processed_tax=money(processed_tax),
        outstanding=money(outstanding), rule_citation=_canc_citation(v), notes=notes)


def payments_summary(payment_rows: list[dict]) -> dict:
    """Collected (success positive), refunded, pending, failed, deposits.
    Duplicate transaction_ref counted once. Deposits never claimed as returned."""
    seen_ref = set()
    collected = Decimal("0"); collected_tax = Decimal("0")
    refunded = Decimal("0"); refunded_tax = Decimal("0")
    pending = Decimal("0"); failed_count = 0
    deposit_collected = Decimal("0")
    by_type: dict[str, Decimal] = {}
    for p in payment_rows:
        ref = p.get("transaction_ref")
        if ref and ref in seen_ref:
            continue
        if ref:
            seen_ref.add(ref)
        status = p.get("payment_status")
        ptype = p.get("payment_type")
        amt = _d(p.get("amount")); tax = _d(p.get("gst_amount"))
        if status == "FAILED":
            failed_count += 1
            continue
        if status == "PENDING":
            pending += amt
            continue
        # SUCCESS
        by_type[ptype] = by_type.get(ptype, Decimal("0")) + amt
        if ptype == "REFUND":
            refunded += -amt
            refunded_tax += -tax
        elif ptype == "DEPOSIT":
            deposit_collected += amt
        else:  # BOOKING, PENALTY
            collected += amt
            collected_tax += tax
    return {
        "collected_ex_gst": money(collected),
        "collected_gst": money(collected_tax),
        "collected_incl_gst": money(collected + collected_tax),
        "refunded": money(refunded),
        "refunded_gst": money(refunded_tax),
        "pending": money(pending),
        "failed_count": failed_count,
        "deposit_collected": money(deposit_collected),
        "deposit_note": "deposit returns are not recorded in payment data (RW-POL-01 s5.3)",
        "by_type": {k: money(val) for k, val in by_type.items()},
    }


def jsonable(obj):
    """Decimals -> 2dp strings, recursively, for the composer."""
    if isinstance(obj, Decimal):
        return money(obj)
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    return obj
