"""Grounding checks on composed answers. The last line of defence."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# citation normalisation
_CITE_VARIANTS = [
    (re.compile(r"[【\[]\s*[Ss](\d+)\s*[】\]]"), r"[S\1]"),
    (re.compile(r"［\s*[Ss](\d+)\s*］"), r"[S\1]"),
]
_HYPHENS = dict.fromkeys(map(ord, "‐‑‒–−"), "-")
_NUM_RE = re.compile(r"(?<![A-Za-z0-9-])\d[\d,]*\.?\d*")
_ID_RE = re.compile(r"\b(?:B-\d{3,4}|CUST\d{4}|PAY\d{5}|VEH\d{3}|DMG\d{4})\b")
_CITE_RE = re.compile(r"\[S(\d+)\]")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_INDIC = re.compile(r"[ऀ-ൿ]")

_ACTION_CLAIMS = re.compile(
    r"\bI (?:have |'ve )?(?:cancelled|canceled|refunded|booked|processed|paid|charged|updated)\b",
    re.I)
_PROCESSED_CLAIM = re.compile(r"refund (?:has been |was |is )?(?:processed|paid|credited|issued)", re.I)
_NEGATION = re.compile(r"\b(no|not|hasn't|has not|yet to|pending|awaiting)\b", re.I)


@dataclass
class Grounding:
    ok: bool = True
    errors: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.ok = False
        self.errors.append(msg)


def normalise_answer(text: str) -> str:
    out = text
    for pat, repl in _CITE_VARIANTS:
        out = pat.sub(repl, out)
    out = re.sub(r"\[S(\d+)\s*,\s*S?(\d+)\]", r"[S\1][S\2]", out)
    out = out.translate(_HYPHENS)
    out = out.replace(" ", " ")
    return out


def _numbers(text: str) -> set[str]:
    nums = set()
    for m in _NUM_RE.findall(text):
        nums.add(m.replace(",", ""))
    return nums


def _float_set(text: str) -> set[float]:
    out = set()
    for m in _NUM_RE.findall(text):
        try:
            out.add(round(float(m.replace(",", "")), 2))
        except ValueError:
            pass
    return out


def check(answer: str, evidence_text: str, n_sources: int, *,
          processed_zero: bool = False, language: str = "en") -> tuple[str, Grounding]:
    answer = normalise_answer(answer)
    g = Grounding()
    ev_floats = _float_set(evidence_text)
    ev_ids = set(_ID_RE.findall(evidence_text))

    # numbers (value-based match; allow small ints for list numbering; ignore IDs)
    ans_wo_ids = _ID_RE.sub("", answer)
    for n in _numbers(ans_wo_ids):
        try:
            val = round(float(n), 2)
        except ValueError:
            continue
        if any(abs(val - e) <= 0.01 for e in ev_floats):
            continue
        # a bare integer that is the floor of an evidence value (e.g. 480 vs 480.00)
        if any(abs(val - round(e)) <= 0.01 for e in ev_floats):
            continue
        if val <= 10 and float(n) == int(val):
            continue  # list numbering / small counts
        g.fail(f"number not in evidence: {n}")

    # ids
    for i in set(_ID_RE.findall(answer)):
        if i not in ev_ids:
            g.fail(f"id not in evidence: {i}")

    # citations
    cites = set(_CITE_RE.findall(answer))
    for c in cites:
        if int(c) > n_sources or int(c) < 1:
            g.fail(f"citation out of range: S{c}")
    if n_sources > 0 and not cites:
        g.fail("no citation present though sources exist")

    # language script
    if language in {"hi"} and not _DEVANAGARI.search(answer):
        g.fail("expected Hindi script")
    if language == "en":
        letters = [c for c in answer if c.isalpha()]
        if letters and sum(bool(_INDIC.match(c)) for c in letters) / len(letters) > 0.10:
            g.fail("unexpected non-Latin script for English answer")

    # action claims
    if _ACTION_CLAIMS.search(answer):
        g.fail("answer claims to have performed an action")

    # false 'processed'
    if processed_zero:
        for m in _PROCESSED_CLAIM.finditer(answer):
            window = answer[max(0, m.start() - 40):m.end() + 10]
            if not _NEGATION.search(window):
                g.fail("claims refund processed when processed=0")
                break

    return answer, g
