"""Set the support-agent (staff) login password.

Stores only a salted scrypt hash in .env as AGENT_PW_HASH (never the password).

Usage:
  python scripts/set_agent_password.py                 # hidden prompt
  python scripts/set_agent_password.py --generate      # random strong password (printed once)
  python scripts/set_agent_password.py --password '...' # non-interactive
  python scripts/set_agent_password.py --id ops_lead    # also set AGENT_ID
"""
from __future__ import annotations

import argparse
import getpass
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ridewise.auth import hash_password  # noqa: E402

ENV = Path(__file__).resolve().parents[1] / ".env"


def _upsert_env(updates: dict[str, str]) -> None:
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    keys = set(updates)
    out, seen = [], set()
    for ln in lines:
        k = ln.split("=", 1)[0].strip() if "=" in ln and not ln.strip().startswith("#") else None
        if k in keys:
            out.append(f"{k}={updates[k]}")
            seen.add(k)
        else:
            out.append(ln)
    for k in keys - seen:
        out.append(f"{k}={updates[k]}")
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--password", default=None)
    ap.add_argument("--id", default=None, help="staff id (AGENT_ID)")
    args = ap.parse_args()

    if args.generate:
        pw = secrets.token_urlsafe(12)
        print(f"Generated staff password (store it now, it is not saved): {pw}")
    elif args.password:
        pw = args.password
    else:
        pw = getpass.getpass("New staff password (min 12 chars): ")
        if pw != getpass.getpass("Confirm: "):
            sys.exit("passwords do not match")

    if len(pw) < 12:
        sys.exit("password must be at least 12 characters")

    updates = {"AGENT_PW_HASH": hash_password(pw)}
    if args.id:
        updates["AGENT_ID"] = args.id
    _upsert_env(updates)
    print(f"Updated .env: {', '.join(updates)}")
    print(f"Staff ID is '{args.id or 'agent'}'. Sign in on the Support agent tab.")


if __name__ == "__main__":
    main()
