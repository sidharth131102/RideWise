"""Languages and timezone conversion. UTC->IST happens exactly once, here."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

LANGUAGES = {
    "en": "English",
    "hi": "हिन्दी",
    "kn": "ಕನ್ನಡ",
    "ta": "தமிழ்",
    "ml": "മലയാളം",
}

IST = timezone(timedelta(hours=5, minutes=30))
_FMT = "%Y-%m-%d %H:%M:%S"
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def utc_text_to_ist(text: str | None) -> str | None:
    """'YYYY-MM-DD HH:MM:SS' UTC -> IST display text. Dates/None pass through."""
    if text is None:
        return None
    s = str(text).strip()
    if _TS_RE.match(s):
        dt = datetime.strptime(s, _FMT).replace(tzinfo=timezone.utc).astimezone(IST)
        return dt.strftime("%Y-%m-%d %H:%M") + " IST"
    return s  # dates and other values unchanged


def localize_rows(rows: list[dict], ts_columns: set[str]) -> list[dict]:
    """Return copies of rows with the named timestamp columns converted to IST."""
    out = []
    for r in rows:
        rr = dict(r)
        for c in ts_columns:
            if c in rr and rr[c] is not None:
                rr[c] = utc_text_to_ist(rr[c])
        out.append(rr)
    return out


def is_timestamp_column(name: str) -> bool:
    n = name.lower()
    return n.endswith("_at") or n in {"scheduled_start", "scheduled_end"}
