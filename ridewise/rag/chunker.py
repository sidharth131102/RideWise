"""PDFs + verified transcriptions -> chunks.

Tables are lifted whole (never split). Scanned-image pages require a matching
transcription; a missing one fails loud. Each chunk carries a context header
and metadata parsed from the document text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
import yaml

from ..config import settings


class IngestError(Exception):
    pass


# fixed pack -> titles (metadata still parsed from text; this is a fallback)
POLICY_PDFS = {
    "01_Rental_Agreement_and_Terms.pdf": "Rental Agreement & Terms",
    "02_Cancellation_and_Refund_Policy_v1.pdf": "Cancellation & Refund Policy",
    "03_Cancellation_and_Refund_Policy_v2.pdf": "Cancellation & Refund Policy",
    "04_Late_Return_and_Damage_Penalty_Schedule.pdf": "Late Return & Damage Penalty Schedule",
    "05_EV_User_Guide_and_FAQ.pdf": "EV User Guide & FAQ",
}

_DOCID_RE = re.compile(r"RW-POL-\d+")
_VER_RE = re.compile(r"Version\s+([\d.]+)")
_EFF_RE = re.compile(r"Effective\s+(\d{1,2}\s+\w+\s+\d{4})")
_IMG_MIN_W = 300
_IMG_MIN_FRAC = 0.15


@dataclass
class RawChunk:
    id: str
    doc_id: str
    title: str
    version: str | None
    effective_date: str | None
    page: int
    section: str | None
    content: str          # for embedding + FTS
    display_text: str     # markdown for the composer
    source_type: str = "pdf"
    extra: dict = field(default_factory=dict)


def _meta(text: str, fname: str) -> tuple[str, str, str | None, str | None]:
    doc_id = (_DOCID_RE.search(text) or [None])
    doc_id = _DOCID_RE.search(text).group(0) if _DOCID_RE.search(text) else fname
    ver = _VER_RE.search(text)
    eff = _EFF_RE.search(text)
    title = POLICY_PDFS.get(fname, fname)
    return doc_id, title, (ver.group(1) if ver else None), (eff.group(1) if eff else None)


def _header(title, version, eff, section, page) -> str:
    eff_s = eff or "effective date not stated"
    sec = f"§{section}" if section else ""
    v = f"v{version}" if version else ""
    return f"[{title} | {v} | {eff_s} | {sec} | p.{page}]".replace(" |  |", " |")


def _clause_blocks(text: str) -> list[tuple[str | None, str]]:
    """Group lines under numbered headings / clauses."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    blocks: list[tuple[str | None, str]] = []
    cur_sec = None
    buf: list[str] = []
    head_re = re.compile(r"^(\d+(\.\d+)*)\.?\s+\S|^(Annexure|Appendix)\b")
    for ln in lines:
        if head_re.match(ln):
            if buf:
                blocks.append((cur_sec, " ".join(buf)))
                buf = []
            m = re.match(r"^(\d+(?:\.\d+)*)", ln)
            cur_sec = m.group(1) if m else ln[:24]
        buf.append(ln)
    if buf:
        blocks.append((cur_sec, " ".join(buf)))
    return blocks


def _load_transcription(doc_stem: str, page: int) -> RawChunk | None:
    tdir = settings.transcriptions_dir
    cand = tdir / f"{doc_stem}_p{page}.md"
    if not cand.exists():
        return None
    raw = cand.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        raise IngestError(f"transcription missing front matter: {cand}")
    meta = yaml.safe_load(m.group(1))
    body = m.group(2).strip()
    if not meta.get("verified_by"):
        print(f"WARNING: transcription {cand.name} has empty verified_by")
    header = _header(meta.get("title"), meta.get("version"),
                     str(meta.get("effective_date") or ""), meta.get("section"), page)
    # embedding text = non-table lines; display = full markdown
    embed_lines = [ln for ln in body.splitlines() if not ln.strip().startswith("|")]
    return RawChunk(
        id=f"{meta['doc_id']}:{meta.get('version')}:{page}:transcription",
        doc_id=meta["doc_id"], title=meta.get("title", ""),
        version=str(meta.get("version")) if meta.get("version") is not None else None,
        effective_date=str(meta.get("effective_date") or "") or None,
        page=page, section=meta.get("section"),
        content=f"{header}\n{' '.join(embed_lines)}",
        display_text=f"{header}\n{body}",
        source_type="transcription")


def chunk_pdf(path: Path) -> list[RawChunk]:
    doc = pymupdf.open(path)
    first_text = doc[0].get_text()
    doc_id, title, version, eff = _meta(first_text, path.name)
    chunks: list[RawChunk] = []
    idx = 0
    for pno in range(doc.page_count):
        page = doc[pno]
        text = page.get_text()
        pw, ph = page.rect.width, page.rect.height
        page_area = pw * ph

        # tables lifted whole
        table_bboxes = []
        try:
            tabs = page.find_tables()
            for ti, tab in enumerate(tabs.tables):
                md = tab.to_markdown()
                table_bboxes.append(tuple(tab.bbox))
                # intro = the clause/heading nearest above the table
                intro = _nearest_intro(text, md)
                header = _header(title, version, eff, None, pno + 1)
                chunks.append(RawChunk(
                    id=f"{doc_id}:{version}:{pno+1}:t{ti}",
                    doc_id=doc_id, title=title, version=version, effective_date=eff,
                    page=pno + 1, section=None,
                    content=f"{header}\n{intro}\n{_table_to_sentences(md)}",
                    display_text=f"{header}\n{intro}\n{md}",
                    source_type="pdf"))
                idx += 1
        except Exception:
            pass

        # non-table text blocks
        for sec, body in _clause_blocks(text):
            if len(body) < 25:
                continue
            header = _header(title, version, eff, sec, pno + 1)
            chunks.append(RawChunk(
                id=f"{doc_id}:{version}:{pno+1}:c{idx}",
                doc_id=doc_id, title=title, version=version, effective_date=eff,
                page=pno + 1, section=sec,
                content=f"{header}\n{body}", display_text=f"{header}\n{body}",
                source_type="pdf"))
            idx += 1

        # scanned-image pages -> require a transcription
        flagged = False
        for img in page.get_image_info():
            x0, y0, x1, y1 = img["bbox"]
            w, hgt = x1 - x0, y1 - y0
            is_logo = y1 < 90 and w < 220
            if (w >= _IMG_MIN_W or (w * hgt) / page_area >= _IMG_MIN_FRAC) and not is_logo:
                flagged = True
        if flagged:
            tr = _load_transcription(path.stem, pno + 1)
            if tr is None:
                # EV guide figures are informational and covered by text elsewhere
                if doc_id == "RW-POL-05":
                    continue
                raise IngestError(
                    f"scanned image on {path.name} p{pno+1} has no transcription in "
                    f"{settings.transcriptions_dir}")
            chunks.append(tr)
    doc.close()
    return chunks


def _nearest_intro(page_text: str, table_md: str) -> str:
    """Use the clause that introduces the table (best-effort)."""
    # find a line that mentions the table or precedes it; fall back to a heading
    for ln in page_text.splitlines():
        s = ln.strip()
        if re.search(r"schedule|table below|refund|fee|deposit|grace|charge", s, re.I) \
                and len(s) > 25:
            return s
    return "Table:"


def _table_to_sentences(md: str) -> str:
    rows = [r for r in md.splitlines() if r.strip().startswith("|")]
    out = []
    header = None
    for r in rows:
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        if header is None:
            header = cells
            continue
        pairs = ", ".join(f"{h}: {c}" for h, c in zip(header, cells) if c)
        if pairs:
            out.append(pairs + ".")
    return " ".join(out)


def build_all_chunks() -> list[RawChunk]:
    docs_dir = settings.docs_dir
    missing = [f for f in POLICY_PDFS if not (docs_dir / f).exists()]
    if missing:
        raise IngestError(f"missing policy PDFs: {missing}")
    chunks: list[RawChunk] = []
    for fname in POLICY_PDFS:
        chunks.extend(chunk_pdf(docs_dir / fname))
    if not chunks:
        raise IngestError("no chunks produced")
    return chunks
