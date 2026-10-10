"""LangSmith tracing. OFF by default; a no-op unless LANGSMITH_TRACING=true
and an API key is present. Traces carry evidence, so keep it off for the demo.

Usage:
  from . import tracing
  @tracing.traceable(name="turn", run_type="chain")
  def answer(...): ...
  client = tracing.wrap_openai(client)
"""
from __future__ import annotations

import os

from .config import settings

_configured = False


def enabled() -> bool:
    return bool(settings.langsmith_tracing and os.getenv("LANGSMITH_API_KEY"))


def configure() -> None:
    """Point the LangChain/LangSmith SDK at the project (idempotent)."""
    global _configured
    if _configured or not enabled():
        return
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_API_KEY", os.getenv("LANGSMITH_API_KEY", ""))
    os.environ.setdefault("LANGCHAIN_PROJECT",
                          os.getenv("LANGSMITH_PROJECT", "ridewise-assist"))
    _configured = True


def traceable(name: str | None = None, run_type: str = "chain", **kwargs):
    """Decorator: real LangSmith span when enabled, identity otherwise.
    The decision is made once, at import time, so there is zero overhead off."""
    def deco(fn):
        if not enabled():
            return fn
        try:
            configure()
            from langsmith import traceable as _t
            return _t(name=name or fn.__name__, run_type=run_type, **kwargs)(fn)
        except Exception:
            return fn
    return deco


def wrap_openai(client):
    if not enabled():
        return client
    try:
        configure()
        from langsmith.wrappers import wrap_openai as _w
        return _w(client)
    except Exception:
        return client


def drop() -> None:
    """Best-effort flush so traces are sent before the process exits."""
    if not enabled():
        return
    try:
        from langsmith import Client
        Client().flush()
    except Exception:
        pass
