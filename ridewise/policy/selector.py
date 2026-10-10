"""Select the cancellation policy version from the deciding timestamp.

Never defaults to the newest version: an unknown deciding timestamp is
reported as uncertain.
"""
from __future__ import annotations

from ..contracts import PolicyDecision
from .rules import load_rules


def select_version(decided_by_utc: str | None) -> PolicyDecision:
    rules = load_rules()
    versions = rules["cancellation"]["versions"]
    field = rules["cancellation"]["deciding_field"]
    if not decided_by_utc:
        return PolicyDecision(
            version=None, uncertain=True,
            reason=f"deciding timestamp ({field}) is missing; cannot pick a policy version")
    # pick the latest version whose from_utc <= decided_by_utc (null = -inf)
    chosen = None
    for v in versions:
        f = v["from_utc"]
        if f is None or f <= decided_by_utc:
            chosen = v
    if chosen is None:
        chosen = versions[0]
    return PolicyDecision(
        version=chosen["version"], uncertain=False,
        reason=f"{field}={decided_by_utc} -> policy version {chosen['version']} "
               f"(effective from {chosen['from_utc'] or 'the original policy'})")


def version_entry(version: str) -> dict | None:
    for v in load_rules()["cancellation"]["versions"]:
        if v["version"] == version:
            return v
    return None
