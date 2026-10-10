from ridewise import auth
from ridewise.config import settings

DB = settings.db_path


def test_customer_login_success():
    sess, err = auth.start_customer_session("CUST0001", "2345", DB)  # 9845012345
    assert err is None and sess is not None
    assert sess.role == "customer" and sess.customer_id == "CUST0001"


def test_customer_login_wrong_last4():
    sess, err = auth.start_customer_session("CUST0001", "0000", DB)
    assert sess is None and err == auth.GENERIC_ERROR


def test_unknown_customer_same_generic_error():
    sess, err = auth.start_customer_session("CUST9999", "1234", DB)
    assert sess is None and err == auth.GENERIC_ERROR


def test_lowercase_and_spacing_ok():
    sess, err = auth.start_customer_session(" cust0001 ", "2345", DB)
    assert err is None and sess.customer_id == "CUST0001"


def test_lockout_after_repeated_failures():
    # fresh identity to avoid interference
    for _ in range(5):
        auth.start_customer_session("CUST0002", "9999", DB)
    # even the correct last4 is now locked out
    import sqlite3
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    phone = con.execute("select phone from customers where customer_id='CUST0002'").fetchone()[0]
    con.close()
    sess, err = auth.start_customer_session("CUST0002", phone[-4:], DB)
    assert sess is None and err == auth.GENERIC_ERROR


def test_agent_login_success():
    sess, err = auth.agent_login("agent", "test-staff-pass-123")
    assert err is None and sess is not None and sess.role == "agent"


def test_agent_login_wrong_password():
    sess, err = auth.agent_login("agent", "wrong-password-xx")
    assert sess is None and err == auth.GENERIC_ERROR


def test_agent_login_wrong_id():
    sess, err = auth.agent_login("not-agent", "test-staff-pass-123")
    assert sess is None and err == auth.GENERIC_ERROR


def test_password_hash_roundtrip():
    h = auth.hash_password("averylongpassword")
    assert auth.verify_password("averylongpassword", h)
    assert not auth.verify_password("wrong", h)
    assert h.startswith("scrypt:")


def test_agent_session_helper():
    s = auth.start_agent_session()
    assert s.role == "agent" and s.customer_id is None
