"""Per-identity chat history, persisted locally as JSON.

One file per identity (role + customer_id). Each identity owns a list of
conversations; each conversation has a title, timestamps and its messages.
Everything is best-effort: a failure to read/write never breaks the UI.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from .config import settings
from .contracts import Session


def _key(session: Session) -> str:
    who = session.customer_id if session.role == "customer" else "agent"
    return f"{session.role}_{who}"


def _path(session: Session) -> Path:
    settings.chat_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", _key(session))
    return settings.chat_dir / f"{safe}.json"


def new_conversation() -> dict:
    now = time.time()
    return {"id": uuid.uuid4().hex[:12], "title": "New conversation",
            "created_at": now, "updated_at": now, "messages": []}


def load_all(session: Session) -> list[dict]:
    p = _path(session)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        convos = data.get("conversations", [])
        convos.sort(key=lambda c: c.get("updated_at", 0), reverse=True)
        return convos
    except Exception:
        return []


def save_all(session: Session, conversations: list[dict]) -> None:
    try:
        # keep only non-empty conversations, newest 50
        kept = [c for c in conversations if c.get("messages")]
        kept.sort(key=lambda c: c.get("updated_at", 0), reverse=True)
        _path(session).write_text(
            json.dumps({"conversations": kept[:50]}, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass


def title_from(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return (t[:40] + "…") if len(t) > 40 else (t or "New conversation")


def clear_all(session: Session) -> None:
    try:
        p = _path(session)
        if p.exists():
            p.unlink()
    except Exception:
        pass
