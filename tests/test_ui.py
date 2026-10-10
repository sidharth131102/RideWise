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


def test_bad_customer_id_shows_error():
    at = _app().run()
    at.text_input[0].set_value("NOPE").run()
    # click "Start as customer"
    [b for b in at.button if b.label == "Start as customer"][0].click().run()
    assert at.session_state["session"] is None
    assert len(at.error) >= 1


def test_agent_session_starts():
    at = _app().run()
    [b for b in at.button if b.label == "Start as support agent"][0].click().run()
    sess = at.session_state["session"]
    assert sess is not None and sess.role == "agent"
    # sidebar now shows New conversation / Sign out
    labels = [b.label for b in at.button]
    assert any("New conversation" in l for l in labels) and "Sign out" in labels


def test_customer_session_and_new_conversation():
    at = _app().run()
    at.text_input[0].set_value("CUST0001").run()
    [b for b in at.button if b.label == "Start as customer"][0].click().run()
    sess = at.session_state["session"]
    assert sess is not None and sess.role == "customer" and sess.customer_id == "CUST0001"
    # at least one conversation exists (active)
    assert len(at.session_state["conversations"]) >= 1
