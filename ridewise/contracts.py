"""Typed contracts. Every tool returns one of these; none raises to the UI."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Role = Literal["customer", "agent"]
Intent = Literal["db", "policy", "hybrid", "web", "clarify", "out_of_scope", "smalltalk"]


class Session(BaseModel):
    role: Role
    customer_id: Optional[str] = None
    language: str = "en"


class RouteDecision(BaseModel):
    intent: Intent
    entity_ref: Optional[str] = None
    english_query: str
    language: str = "en"
    clarify_question: Optional[str] = None


class SqlResult(BaseModel):
    sql: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[dict] = Field(default_factory=list)
    row_ids: list[str] = Field(default_factory=list)
    row_count: int = 0
    row_count_note: Optional[str] = None
    error: Optional[str] = None


class Chunk(BaseModel):
    id: str
    doc_id: str
    title: str
    version: Optional[str] = None
    effective_date: Optional[str] = None
    page: int = 0
    section: Optional[str] = None
    text: str = ""
    display_text: str = ""
    score: float = 0.0
    source_type: str = "pdf"


class RuleCitation(BaseModel):
    doc: str
    version: Optional[str] = None
    page: Optional[int] = None
    section: Optional[str] = None
    quote: str = ""


class PolicyDecision(BaseModel):
    version: Optional[str] = None
    reason: str = ""
    uncertain: bool = False


class RefundBreakdown(BaseModel):
    eligible_pct: str
    due: str
    due_tax: str
    amount_paid: str
    tax_paid: str
    processed: str
    processed_tax: str
    outstanding: str
    rule_citation: Optional[RuleCitation] = None
    notes: list[str] = Field(default_factory=list)


class WebHit(BaseModel):
    title: str
    url: str
    date: Optional[str] = None
    snippet: str = ""


class Citation(BaseModel):
    kind: str           # db | policy | calc | web
    ref: str            # e.g. "S1"
    label: str


class ExecutedQuery(BaseModel):
    sql: str
    row_count: int = 0
    error: Optional[str] = None


class Answer(BaseModel):
    text: str = ""
    language: str = "en"
    source_types: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)
    summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    queries: list[ExecutedQuery] = Field(default_factory=list)
