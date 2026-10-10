"""Validated NL->SQL over the scoped DB, plus fixed parameterised bundles.

The DB handed in is ALREADY scoped and locked read-only. SQL is validated with
sqlglot (one SELECT, no writes, no placeholders) before it ever runs.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlglot
from sqlglot import exp

from .contracts import SqlResult
from .db_scope import ScopedDB, normalise_ref, ref_kind
from .llm import LLMUnavailable, get_llm
from .schema import SchemaInfo

# compact semantics for the prompt (from FINDINGS / data dictionary)
SEMANTICS = """\
Confirmed semantics:
- All timestamps are text 'YYYY-MM-DD HH:MM:SS' in UTC.
- booking_status: UPC=upcoming, ONG=ongoing, CMP=completed, CNL_U=cancelled by customer,
  CNL_S=cancelled by RideWise, NSH=no-show.
- payment_type: BOOKING, DEPOSIT, PENALTY, REFUND. amount EXCLUDES GST; gst_amount is separate.
  REFUND amounts are negative. Collected money = SUCCESS positive rows. FAILED excluded; PENDING separate.
- payment_status: SUCCESS, FAILED, PENDING.
- kyc_status: VERIFIED, PENDING, REJECTED. customer_tier: STANDARD, SILVER, GOLD.
- vehicle_type: BIKE, SCOOTER, EV_SCOOTER, EV_BIKE. vehicles.status: ACTIVE, MAINTENANCE, RETIRED.
- damage_reports.claim_status: OPEN, CHARGED, DISPUTED, WAIVED (customer charged only when CHARGED).
- "upcoming" = booking_status='UPC' (never cancelled). "past/previous" = scheduled_start < current time.
"""

_FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.Command, exp.Pragma, exp.Transaction, exp.Set,
)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def build_prompt(schema: SchemaInfo, role: str) -> str:
    if role == "customer":
        scope = ("The database has ALREADY been filtered to the signed-in customer: every table "
                 "holds only their rows. \"my X\" = all rows in X. NEVER filter by customer id, "
                 "email or phone, and never look the customer up.")
    else:
        scope = ("The database holds all records; personal fields are already masked.")
    return f"""You translate a support question into ONE read-only SQLite SELECT query.
{scope}
Current time (UTC, same format as the data): '{now_utc()}'.
Live schema:
{schema.render()}
{SEMANTICS}
Rules:
- Exactly one SELECT (WITH allowed). No semicolons, PRAGMA or writes.
- Literal values only. NO parameters or placeholders (?, :name, @name, $1): nothing will be bound.
- "how many / count / total / sum / average" -> compute IN SQL with COUNT/SUM/AVG; never return rows to be counted.
- Otherwise include primary-key id columns of the rows you return. At most 200 rows.
Respond with JSON only: {{"sql": "...", "reasoning": "one sentence"}}"""


class SqlValidationError(Exception):
    pass


def validate_sql(sql: str, schema: SchemaInfo) -> str:
    """Return a safe SQL string (LIMIT added) or raise SqlValidationError."""
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise SqlValidationError("empty SQL")
    try:
        statements = sqlglot.parse(sql, read="sqlite")
    except Exception as e:  # noqa: BLE001
        raise SqlValidationError(f"could not parse SQL: {e}")
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise SqlValidationError("exactly one statement is allowed")
    tree = statements[0]

    root = tree
    if not isinstance(root, (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.With)):
        raise SqlValidationError("only SELECT queries are allowed")

    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SqlValidationError(f"forbidden operation: {type(node).__name__}")
        if isinstance(node, (exp.Placeholder, exp.Parameter)):
            raise SqlValidationError(
                "no parameters/placeholders: nothing will be bound; the DB is already "
                "scoped, so don't filter by customer")

    # CTE names are allowed as "tables"
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for tbl in tree.find_all(exp.Table):
        if tbl.catalog or tbl.db:
            raise SqlValidationError("schema-qualified tables are not allowed")
        name = tbl.name.lower()
        if name in cte_names:
            continue
        if not schema.has_table(tbl.name):
            raise SqlValidationError(f"unknown table: {tbl.name}")

    # add LIMIT 200 if absent (only for plain selects)
    if isinstance(tree, exp.Select) and not tree.args.get("limit"):
        tree.limit(200, copy=False)
    return tree.sql(dialect="sqlite")


def run_query(scoped: ScopedDB, sql: str) -> SqlResult:
    try:
        cur = scoped.conn.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:  # noqa: BLE001
        return SqlResult(sql=sql, error=str(e))
    # id columns for grounding
    id_cols = [c for c in cols if c.endswith("_id") or c == "report_id"]
    row_ids = []
    for r in rows:
        for c in id_cols:
            if r.get(c):
                row_ids.append(str(r[c]))
    note = "showing first 200 rows" if len(rows) >= 200 else None
    return SqlResult(sql=sql, columns=cols, rows=rows, row_ids=row_ids,
                     row_count=len(rows), row_count_note=note)


def answer_question(scoped: ScopedDB, english_query: str) -> SqlResult:
    """Generate -> validate -> run. Distinguishes LLM outage from bad SQL."""
    llm = get_llm()
    system = build_prompt(scoped.schema, scoped.session.role)
    try:
        data = llm.chat_json(system, english_query)
    except LLMUnavailable as e:
        return SqlResult(error=f"LLM_UNAVAILABLE: {e}")
    sql = data.get("sql", "")
    try:
        safe = validate_sql(sql, scoped.schema)
    except SqlValidationError as e:
        # one retry with the error
        try:
            data = llm.chat_json(system, f"{english_query}\n\nYour previous SQL was invalid: {e}\nFix it.")
            safe = validate_sql(data.get("sql", ""), scoped.schema)
        except (LLMUnavailable, SqlValidationError) as e2:
            return SqlResult(sql=sql, error=f"invalid SQL: {e2}")
    res = run_query(scoped, safe)
    if res.error:  # one retry on execution error
        try:
            data = llm.chat_json(system, f"{english_query}\n\nSQL error: {res.error}\nFix it.")
            safe = validate_sql(data.get("sql", ""), scoped.schema)
            res = run_query(scoped, safe)
        except (LLMUnavailable, SqlValidationError):
            pass
    return res


# --------------------------------------------------------------------------- #
# Fixed parameterised bundles (no LLM) - main path for transactional questions
# --------------------------------------------------------------------------- #
def _q(scoped: ScopedDB, sql: str, params=()) -> list[dict]:
    cur = scoped.conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def entity_bundle(scoped: ScopedDB, ref: str) -> dict:
    """Everything known about a visible entity, via fixed queries."""
    ref = normalise_ref(ref) or ref
    kind = ref_kind(ref)
    if not scoped.entity_visible(ref):
        return {"found": False, "ref": ref, "kind": kind}

    bundle: dict = {"found": True, "ref": ref, "kind": kind}
    if kind == "booking":
        bundle["booking"] = _q(scoped, "select * from bookings where booking_id=?", (ref,))
        bundle["vehicle"] = _q(scoped,
            "select v.* from vehicles v join bookings b on b.vehicle_id=v.vehicle_id "
            "where b.booking_id=?", (ref,))
        bundle["customer"] = _q(scoped,
            "select c.customer_id, c.customer_tier, c.kyc_status from customers c "
            "join bookings b on b.customer_id=c.customer_id where b.booking_id=?", (ref,))
        bundle["payments"] = _q(scoped,
            "select * from payments where booking_id=? order by paid_at", (ref,))
        bundle["damage_reports"] = _q(scoped,
            "select * from damage_reports where booking_id=?", (ref,))
    elif kind == "customer":
        bundle["customer"] = _q(scoped, "select * from customers where customer_id=?", (ref,))
        bundle["bookings"] = _q(scoped,
            "select * from bookings where customer_id=? order by scheduled_start desc limit 50", (ref,))
    elif kind == "payment":
        bundle["payment"] = _q(scoped, "select * from payments where payment_id=?", (ref,))
        bundle["booking"] = _q(scoped,
            "select b.* from bookings b join payments p on p.booking_id=b.booking_id "
            "where p.payment_id=?", (ref,))
    elif kind == "vehicle":
        bundle["vehicle"] = _q(scoped, "select * from vehicles where vehicle_id=?", (ref,))
    elif kind == "damage":
        bundle["damage"] = _q(scoped, "select * from damage_reports where report_id=?", (ref,))
        bundle["booking"] = _q(scoped,
            "select b.* from bookings b join damage_reports d on d.booking_id=b.booking_id "
            "where d.report_id=?", (ref,))
    return bundle
