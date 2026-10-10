"""Test helpers. Sessions are built directly; there is no demo login."""
from __future__ import annotations

from ridewise.config import settings
from ridewise.contracts import Session
from ridewise import db_scope as ds

DB = settings.db_path


def session_for(customer_id: str) -> Session:
    return Session(role="customer", customer_id=customer_id)


def agent_session() -> Session:
    return Session(role="agent")


def scoped(customer_id: str | None):
    s = session_for(customer_id) if customer_id else agent_session()
    return ds.build(s, DB)
