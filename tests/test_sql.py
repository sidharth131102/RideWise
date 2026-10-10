import pytest

from ridewise import sql_tool as st
from ridewise.sql_tool import SqlValidationError
from tests.helpers import scoped


@pytest.fixture
def agent():
    sc = scoped(None)
    yield sc
    sc.close()


def test_valid_select_gets_limit(agent):
    out = st.validate_sql("select vehicle_id from vehicles", agent.schema)
    assert "LIMIT" in out.upper()


@pytest.mark.parametrize("bad", [
    "select 1; drop table vehicles",
    "update vehicles set status='X'",
    "delete from vehicles",
    "insert into vehicles(vehicle_id) values('X')",
    "select * from customers where customer_id = ?",
    "select * from customers where customer_id = :cid",
    "pragma table_info(vehicles)",
    "select * from main.vehicles",
    "select * from does_not_exist",
])
def test_rejects_unsafe(agent, bad):
    with pytest.raises(SqlValidationError):
        st.validate_sql(bad, agent.schema)


def test_count_runs(agent):
    sql = st.validate_sql("select count(*) c from vehicles where status='ACTIVE'", agent.schema)
    res = st.run_query(agent, sql)
    assert res.error is None and res.rows[0]["c"] == 50


def test_entity_bundle_scoped():
    sc = scoped("CUST0001")
    b = st.entity_bundle(sc, "B-0001")
    assert b["found"] and b["booking"][0]["booking_status"] == "CMP"
    # cross-customer booking is invisible -> not found
    assert st.entity_bundle(sc, "B-0412")["found"] is False
    sc.close()
