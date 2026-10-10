"""Orchestrator tests run offline (no LLM): heuristic router + template answers."""
from ridewise import orchestrator as orch
from ridewise.contracts import Session
from tests.helpers import scoped, DB


def _ask(session, q):
    sc = scoped(session.customer_id) if session.role == "customer" else scoped(None)
    try:
        return orch.answer(session, sc, q, [])
    finally:
        sc.close()


def test_action_request_refused():
    a = _ask(Session(role="customer", customer_id="CUST0001"), "Cancel B-0001 for me")
    assert "read-only" in a.text.lower()
    assert a.source_types == []


def test_cross_customer_is_not_found():
    a = _ask(Session(role="customer", customer_id="CUST0001"), "details of booking B-0412")
    assert "no record" in a.text.lower() or "b-0412" in a.text.lower()
    # must not reveal CUST0013's data
    assert "CUST0013" not in a.text


def test_refund_question_includes_policy_and_calc():
    a = _ask(Session(role="customer", customer_id="CUST0001"),
             "what refund if I cancel B-0001")
    assert "calc" in a.source_types
    # policy citation attached for the refund rule / schedule
    assert any(c.kind == "policy" for c in a.citations) or "policy" in a.source_types


def test_detect_action_and_refs():
    assert orch.detect_action("cancel my booking") is True
    assert orch.detect_action("what is the refund for B-1709?") is False
    assert orch.extract_refs("see B-0001 and cust13") == ["B-0001", "CUST0013"]


def test_injection_in_record_does_not_leak(monkeypatch):
    # CUST0013 views their own DMG0003 (the planted injection). The answer must
    # not contain any phone number and must not claim to reveal other data.
    a = _ask(Session(role="customer", customer_id="CUST0013"), "what's the damage on B-0412?")
    import re
    assert re.search(r"\b\d{10}\b", a.text) is None
