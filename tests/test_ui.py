"""UI smoke tests via Streamlit AppTest (no chat turn -> no model load)."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _app():
    return AppTest.from_file(APP, default_timeout=30)


def test_login_renders():
    at = _app().run()
    assert at.exception is None or str(at.exception) == "ElementList()"
    labels = [b.label for b in at.button]
    assert "Start as customer" in labels and "Start as support agent" in labels


def test_bad_customer_login_shows_error():
    at = _app().run()
    at.text_input[0].set_value("CUST0001").run()
    at.text_input[1].set_value("0000").run()   # wrong last4
    [b for b in at.button if b.label == "Start as customer"][0].click().run()
    assert at.session_state["session"] is None
    assert len(at.error) >= 1


def test_agent_session_starts():
    at = _app().run()
    # customer tab inputs are [0],[1]; agent tab Staff ID / Password are [2],[3]
    at.text_input[2].set_value("agent").run()
    at.text_input[3].set_value("test-staff-pass-123").run()
    [b for b in at.button if b.label == "Start as support agent"][0].click().run()
    sess = at.session_state["session"]
    assert sess is not None and sess.role == "agent"
    # sidebar now shows New conversation / Sign out
    labels = [b.label for b in at.button]
    assert any("New conversation" in l for l in labels) and "Sign out" in labels


def test_agent_wrong_password_shows_error():
    at = _app().run()
    at.text_input[2].set_value("agent").run()
    at.text_input[3].set_value("nope").run()
    [b for b in at.button if b.label == "Start as support agent"][0].click().run()
    assert at.session_state["session"] is None
    assert len(at.error) >= 1


def test_customer_session_and_new_conversation():
    at = _app().run()
    at.text_input[0].set_value("CUST0001").run()
    at.text_input[1].set_value("2345").run()    # last4 of 9845012345
    [b for b in at.button if b.label == "Start as customer"][0].click().run()
    sess = at.session_state["session"]
    assert sess is not None and sess.role == "customer" and sess.customer_id == "CUST0001"
    # at least one conversation exists (active)
    assert len(at.session_state["conversations"]) >= 1
