"""Security core: build a private in-memory SQLite copy per session.

Each session (each turn) gets a fresh :memory: DB that physically contains
ONLY the rows that session may see, with PII masked and free text scrubbed,
then locked read-only (PRAGMA query_only + authorizer). LLM-written SQL runs
only here, so a forgotten WHERE clause cannot leak anything that is not there.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from .contracts import Session
from .schema import SchemaInfo, introspect

# ---- reference-id normalisation (only formats confirmed in Step 1) --------- #
_REF_PATTERNS = [
    (re.compile(r"^b[-\s]?0*(\d{1,4})$", re.I), lambda m: f"B-{int(m.group(1)):04d}"),
    (re.compile(r"^cust[-\s]?0*(\d{1,4})$", re.I), lambda m: f"CUST{int(m.group(1)):04d}"),
    (re.compile(r"^pay[-\s]?0*(\d{1,5})$", re.I), lambda m: f"PAY{int(m.group(1)):05d}"),
    (re.compile(r"^veh[-\s]?0*(\d{1,3})$", re.I), lambda m: f"VEH{int(m.group(1)):03d}"),
    (re.compile(r"^dmg[-\s]?0*(\d{1,4})$", re.I), lambda m: f"DMG{int(m.group(1)):04d}"),
]


def normalise_ref(ref: str | None) -> str | None:
    if not ref:
        return None
    s = ref.strip()
    for pat, fmt in _REF_PATTERNS:
        m = pat.match(s)
        if m:
            return fmt(m)
    return s.upper() if re.match(r"^[A-Za-z]+[-\s]?\d+$", s) else s


def ref_kind(ref: str) -> str | None:
    if re.match(r"^B-\d{4}$", ref):
        return "booking"
    if re.match(r"^CUST\d{4}$", ref):
        return "customer"
    if re.match(r"^PAY\d{5}$", ref):
        return "payment"
    if re.match(r"^VEH\d{3}$", ref):
        return "vehicle"
    if re.match(r"^DMG\d{4}$", ref):
        return "damage"
    return None


# ---- masking / scrubbing --------------------------------------------------- #
_PHONE_RE = re.compile(r"\b(\d{10})\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


def mask_phone(v: str | None) -> str | None:
    if not v:
        return v
    d = re.sub(r"\D", "", v)
    if len(d) == 10:
        return d[:2] + "******" + d[-2:]
    return "***"


def mask_email(v: str | None) -> str | None:
    if not v or "@" not in v:
        return v
    local, _, domain = v.partition("@")
    head = local[:2] if len(local) >= 2 else local
    return f"{head}***@{domain}"


def mask_dob(v: str | None) -> str | None:
    return "****-**-**" if v else v


def mask_license(v: str | None) -> str | None:
    if not v:
        return v
    return v[:2] + "*" * max(0, len(v) - 4) + v[-2:]


def scrub_text(v: str | None, customer_name: str | None = None) -> str | None:
    """Redact phones/emails from free text (both roles). Never let free text
    carry PII or instruction payloads through as data."""
    if not v:
        return v
    out = _PHONE_RE.sub("[redacted-phone]", v)
    out = _EMAIL_RE.sub("[redacted-email]", out)
    # redact 'Customer <Name>' references (names other than the viewer's own)
    def _name_sub(m: re.Match) -> str:
        nm = m.group(1)
        if customer_name and nm.lower() == customer_name.lower():
            return m.group(0)
        return "Customer [redacted]"
    out = re.sub(r"Customer ([A-Z][a-z]+(?: [A-Z][a-z]+)+)", _name_sub, out)
    return out


# ---- scoped DB ------------------------------------------------------------- #
@dataclass
class ScopedDB:
    conn: sqlite3.Connection
    schema: SchemaInfo
    session: Session

    def entity_visible(self, ref: str) -> bool:
        """True iff the normalised ref exists in this scoped DB. Because the DB
        holds only visible rows, existence == visibility. 'not found' and
        'not yours' therefore return identically."""
        ref = normalise_ref(ref) or ref
        kind = ref_kind(ref)
        table_col = {
            "booking": ("bookings", "booking_id"),
            "customer": ("customers", "customer_id"),
            "payment": ("payments", "payment_id"),
            "vehicle": ("vehicles", "vehicle_id"),
            "damage": ("damage_reports", "report_id"),
        }.get(kind or "")
        if not table_col:
            return False
        table, col = table_col
        row = self.conn.execute(
            f'select 1 from "{table}" where "{col}"=? limit 1', (ref,)).fetchone()
        return row is not None

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


# authorizer: allow read-only operations only
_ALLOWED = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
for _name in ("SQLITE_RECURSIVE",):  # CTEs
    if hasattr(sqlite3, _name):
        _ALLOWED.add(getattr(sqlite3, _name))


def _authorizer(action, a1, a2, a3, a4):
    return sqlite3.SQLITE_OK if action in _ALLOWED else sqlite3.SQLITE_DENY


def _table_columns(schema: SchemaInfo, table: str) -> list[str]:
    return [c.name for c in schema.tables[table].columns]


def _copy_table(src: sqlite3.Connection, mem: sqlite3.Connection,
                schema: SchemaInfo, table: str, where: str = "", params=()) -> None:
    cols = _table_columns(schema, table)
    collist = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    rows = src.execute(
        f'select {collist} from "{table}" {where}', params).fetchall()
    mem.executemany(
        f'insert into "{table}" ({collist}) values ({placeholders})', rows)


def build(session: Session, db_path) -> ScopedDB:
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    schema = introspect(src)  # capture BEFORE locking

    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    # recreate exact schema (tables only; no indexes needed for tiny scoped copy)
    for (create_sql,) in src.execute(
            "select sql from sqlite_master where type='table' and sql is not null"):
        mem.execute(create_sql)

    if session.role == "customer":
        _build_customer(src, mem, schema, session.customer_id or "__none__")
    else:
        _build_agent(src, mem, schema)

    mem.commit()
    # lock it down
    mem.execute("PRAGMA query_only = ON")
    mem.set_authorizer(_authorizer)
    src.close()
    return ScopedDB(conn=mem, schema=schema, session=session)


def _build_customer(src, mem, schema: SchemaInfo, customer_id: str) -> None:
    # the viewer's own name, so we don't redact it from their own free text
    row = src.execute(
        "select full_name from customers where customer_id=?", (customer_id,)).fetchone()
    name = row["full_name"] if row else None

    _copy_rows(src, mem, schema, "customers",
               "where customer_id=?", (customer_id,), scrub_name=name)
    _copy_rows(src, mem, schema, "bookings",
               "where customer_id=?", (customer_id,), scrub_name=name)
    _copy_rows(src, mem, schema, "payments",
               "where booking_id in (select booking_id from bookings where customer_id=?)",
               (customer_id,), scrub_name=name)
    _copy_rows(src, mem, schema, "damage_reports",
               "where booking_id in (select booking_id from bookings where customer_id=?)",
               (customer_id,), scrub_name=name)
    _copy_rows(src, mem, schema, "vehicles",
               "where vehicle_id in (select vehicle_id from bookings where customer_id=?)",
               (customer_id,), scrub_name=name)


def _build_agent(src, mem, schema: SchemaInfo) -> None:
    # agents see all rows; contact/identity PII masked, names shown
    _copy_rows(src, mem, schema, "customers", mask_pii=True)
    _copy_rows(src, mem, schema, "bookings")
    _copy_rows(src, mem, schema, "vehicles")
    _copy_rows(src, mem, schema, "payments")
    _copy_rows(src, mem, schema, "damage_reports")


def _copy_rows(src, mem, schema: SchemaInfo, table: str,
               where: str = "", params=(), *,
               mask_pii: bool = False, scrub_name: str | None = None) -> None:
    cols = _table_columns(schema, table)
    collist = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    out_rows = []
    for row in src.execute(f'select {collist} from "{table}" {where}', params):
        d = dict(row)
        if table == "customers" and mask_pii:
            d["phone"] = mask_phone(d.get("phone"))
            d["email"] = mask_email(d.get("email"))
            d["date_of_birth"] = mask_dob(d.get("date_of_birth"))
            d["driving_license_no"] = mask_license(d.get("driving_license_no"))
        if table == "payments" and "remarks" in d:
            d["remarks"] = scrub_text(d.get("remarks"), scrub_name)
        if table == "damage_reports" and "description" in d:
            d["description"] = scrub_text(d.get("description"), scrub_name)
        out_rows.append(tuple(d[c] for c in cols))
    mem.executemany(
        f'insert into "{table}" ({collist}) values ({placeholders})', out_rows)
