"""Load rules.yaml and validate it on every load."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

RULES_PATH = Path(__file__).with_name("rules.yaml")


class RulesError(Exception):
    pass


def _validate(rules: dict) -> None:
    canc = rules["cancellation"]
    versions = canc["versions"]
    # unique, ordered by from_utc (first is null)
    if versions[0]["from_utc"] is not None:
        raise RulesError("first cancellation version must have from_utc: null")
    seen = set()
    last = None
    for v in versions:
        if v["version"] in seen:
            raise RulesError(f"duplicate version {v['version']}")
        seen.add(v["version"])
        f = v["from_utc"]
        if f is not None:
            if last is not None and f <= last:
                raise RulesError("versions must be strictly ordered by from_utc")
            last = f
        # slabs: percentages 0-100; monotonic (more notice never refunds less);
        # coverage down to min_hours 0; thresholds strictly descending
        slabs = v["slabs"]
        prev_hours = None
        prev_pct = None
        for s in slabs:
            if not (0 <= s["pct"] <= 100):
                raise RulesError(f"pct out of range in v{v['version']}: {s}")
            if prev_hours is not None:
                if s["min_hours"] >= prev_hours:
                    raise RulesError("slab min_hours must strictly descend")
                if s["pct"] > prev_pct:
                    raise RulesError("refund must not increase as notice shrinks (monotonic)")
            prev_hours, prev_pct = s["min_hours"], s["pct"]
        if slabs[-1]["min_hours"] != 0:
            raise RulesError(f"v{v['version']} slabs must cover down to 0 hours")

    for tier, g in rules["late_fee"]["grace_minutes"].items():
        if g < 0:
            raise RulesError(f"negative grace for {tier}")
    if not (0 <= rules["ev_low_battery"]["threshold_pct"] <= 100):
        raise RulesError("ev threshold out of range")


@lru_cache(maxsize=1)
def load_rules() -> dict:
    with open(RULES_PATH, encoding="utf-8") as f:
        rules = yaml.safe_load(f)
    _validate(rules)
    return rules
