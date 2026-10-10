"""Session identity.

Per the hackathon brief (Minimum Requirement 2), a session starts as a
specific customer (by customer_id) or as a support agent. The real security
boundary is the per-session scoped DB (db_scope.py), not this step.

Also provides optional stronger auth (customer email+last4, staff scrypt) as a
documented upgrade; these never write to the DB and run in constant time.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field

from .contracts import Session

GENERIC_ERROR = "We could not sign you in. Check your details and try again."
_CUST_RE = re.compile(r"^CUST\d{4}$")


# ---- primary path: role / customer_id selection --------------------------- #
def start_customer_session(customer_id: str, db_path, language: str = "en") -> tuple[Session | None, str | None]:
    cid = (customer_id or "").strip().upper()
    if not _CUST_RE.match(cid):
        return None, "Enter a customer ID like CUST0001."
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = con.execute(
            "select 1 from customers where customer_id=? limit 1", (cid,)).fetchone()
    finally:
        con.close()
    if not row:
        return None, GENERIC_ERROR  # same message as a wrong id (no enumeration)
    return Session(role="customer", customer_id=cid, language=language), None


def start_agent_session(language: str = "en") -> Session:
    return Session(role="agent", customer_id=None, language=language)


# ---- optional stronger auth ------------------------------------------------ #
@dataclass
class _Lockout:
    window_s: int = 15 * 60
    max_attempts: int = 5
    _hits: dict[str, list[float]] = field(default_factory=dict)

    def locked(self, key: str) -> bool:
        now = time.time()
        hits = [t for t in self._hits.get(key, []) if now - t < self.window_s]
        self._hits[key] = hits
        return len(hits) >= self.max_attempts

    def record(self, key: str) -> None:
        self._hits.setdefault(key, []).append(time.time())

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


_lock = _Lockout()


def customer_login(email: str, last4: str, db_path) -> tuple[Session | None, str | None]:
    key = (email or "").strip().lower()
    if _lock.locked(key):
        return None, GENERIC_ERROR
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = con.execute(
            "select customer_id, phone from customers where lower(trim(email))=?",
            (key,)).fetchone()
    finally:
        con.close()
    # constant-time-ish compare even when email unknown
    real_last4 = (row[1][-4:] if row and row[1] else "0000")
    ok = hmac.compare_digest(str(last4).strip(), real_last4)
    if row and ok:
        _lock.reset(key)
        return Session(role="customer", customer_id=row[0]), None
    _lock.record(key)
    return None, GENERIC_ERROR


# scrypt password helpers (format: scrypt:N:r:p:salt_hex:hash_hex)
def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must be at least 12 characters")
    n, r, p = 2 ** 14, 8, 1
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt:{n}:{r}:{p}:{salt.hex()}:{dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        tag, n, r, p, salt_hex, hash_hex = stored.split(":")
        assert tag == "scrypt"
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                            n=int(n), r=int(r), p=int(p), dklen=len(hash_hex) // 2)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def agent_login(staff_id: str, password: str) -> tuple[Session | None, str | None]:
    key = f"staff:{(staff_id or '').strip()}"
    if _lock.locked(key):
        return None, GENERIC_ERROR
    stored = os.getenv("AGENT_PW_HASH", "")
    ok = verify_password(password or "", stored) if stored else False
    if ok:
        _lock.reset(key)
        return Session(role="agent", customer_id=None), None
    _lock.record(key)
    return None, GENERIC_ERROR
