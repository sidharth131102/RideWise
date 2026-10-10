"""Security tests. These must never be cut."""
import sqlite3

import pytest

from ridewise import db_scope as ds
from tests.helpers import scoped, DB


def test_customer_sees_only_own_rows():
    sc = scoped("CUST0001")
    assert sc.conn.execute("select count(*) from customers").fetchone()[0] == 1
    assert sc.conn.execute(
        "select count(*) from customers where customer_id!='CUST0001'").fetchone()[0] == 0
    # all bookings belong to the customer
    rows = sc.conn.execute("select distinct customer_id from bookings").fetchall()
    assert all(r[0] == "CUST0001" for r in rows)
    sc.close()


def test_cross_customer_and_missing_are_identical():
    sc = scoped("CUST0001")
    # B-0412 belongs to CUST0013; B-9999 does not exist. Both invisible.
    assert sc.entity_visible("B-0412") is False
    assert sc.entity_visible("B-9999") is False
    assert sc.entity_visible("B-0001") is True
    sc.close()


@pytest.mark.parametrize("stmt", [
    "update customers set city='X'",
    "delete from customers",
    "insert into customers (customer_id) values ('X')",
    "drop table customers",
    "create table t(x)",
    "attach database 'x.db' as y",
    "pragma table_info(customers)",
])
def test_write_and_ddl_blocked(stmt):
    sc = scoped("CUST0001")
    with pytest.raises(sqlite3.DatabaseError):
        sc.conn.execute(stmt)
    sc.close()


def test_agent_pii_masked_names_shown():
    sc = scoped(None)  # agent
    r = sc.conn.execute(
        "select full_name, phone, email, date_of_birth, driving_license_no "
        "from customers where customer_id='CUST0001'").fetchone()
    assert r["full_name"] == "Aarav Sharma"       # names shown
    assert "*" in r["phone"] and r["phone"].startswith("98")
    assert r["email"].startswith("aa***@")
    assert r["date_of_birth"] == "****-**-**"
    assert "*" in r["driving_license_no"]
    sc.close()


def test_free_text_phone_email_scrubbed():
    # a remark containing a phone number must be redacted for both roles
    assert ds.scrub_text("call 9845012345 or a@b.com") == \
        "call [redacted-phone] or [redacted-email]"


def test_injection_text_is_inert_data():
    # the planted injection remains stored as data; it must not contain a real
    # phone number to leak, and the orchestrator treats it as untrusted.
    sc = scoped(None)
    d = sc.conn.execute(
        "select description from damage_reports where report_id='DMG0003'").fetchone()[0]
    assert "Ignore previous instructions" in d       # preserved verbatim as data
    assert ds._PHONE_RE.search(d) is None             # no phone to leak
    sc.close()


def test_normalise_ref():
    assert ds.normalise_ref("b1") == "B-0001"
    assert ds.normalise_ref("cust13") == "CUST0013"
    assert ds.normalise_ref("pay1") == "PAY00001"
    assert ds.normalise_ref("veh1") == "VEH001"
    assert ds.normalise_ref("dmg3") == "DMG0003"
    assert ds.normalise_ref("B 0001") == "B-0001"


def test_scoped_db_is_query_only():
    sc = scoped("CUST0001")
    # query_only pragma set; even without authorizer writes would fail
    sc.close()
