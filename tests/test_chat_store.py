import os
import tempfile
from pathlib import Path

from ridewise import chat_store
from ridewise.config import settings
from ridewise.contracts import Session


def _tmp(monkeypatch):
    d = Path(tempfile.mkdtemp())
    monkeypatch.setattr(settings, "chat_dir", d)
    return d


def test_roundtrip_per_identity(monkeypatch):
    _tmp(monkeypatch)
    s1 = Session(role="customer", customer_id="CUST0001")
    s2 = Session(role="agent")
    c = chat_store.new_conversation()
    c["title"] = chat_store.title_from("What is my refund for B-0001?")
    c["messages"] = [{"role": "user", "content": "hi"},
                     {"role": "assistant", "text": "hello"}]
    chat_store.save_all(s1, [c])
    # separate identity sees nothing
    assert chat_store.load_all(s2) == []
    back = chat_store.load_all(s1)
    assert len(back) == 1 and back[0]["title"].startswith("What is my refund")


def test_empty_conversations_not_persisted(monkeypatch):
    _tmp(monkeypatch)
    s = Session(role="customer", customer_id="CUST0002")
    empty = chat_store.new_conversation()
    chat_store.save_all(s, [empty])
    assert chat_store.load_all(s) == []


def test_title_truncation():
    long = "x" * 80
    assert chat_store.title_from(long).endswith("…") and len(chat_store.title_from(long)) <= 41
    assert chat_store.title_from("  ") == "New conversation"


def test_clear(monkeypatch):
    _tmp(monkeypatch)
    s = Session(role="customer", customer_id="CUST0003")
    c = chat_store.new_conversation()
    c["messages"] = [{"role": "user", "content": "q"}]
    chat_store.save_all(s, [c])
    assert chat_store.load_all(s)
    chat_store.clear_all(s)
    assert chat_store.load_all(s) == []
