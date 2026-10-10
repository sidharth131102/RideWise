# RideWise Assist

A **read-only** conversational support assistant for RideWise (two-wheeler & EV
rentals, Bengaluru). It answers questions from two sources — the operational
**SQLite database** and the **policy PDFs** — for two roles (**customer** and
**support agent**), respecting each role's entitlements. It never books,
cancels, pays or refunds; it explains and shows.

## Why it is built this way (one paragraph)
Correctness and access control come first. Every session gets a **private,
in-memory copy of the database containing only the rows it may see**, locked
read-only — so the LLM's SQL cannot leak anything that isn't there. All money
(refunds, late fees, GST) is computed by **deterministic Python**, not the LLM,
with the cancellation **policy version chosen from `booked_at`** against the
IST cutover. The two **scanned policy tables** are brought in as verified
transcriptions. Answers are **grounded**: the composer may only use numbered
evidence, and a validator rejects ungrounded numbers, fake citations, and
action claims before the answer is shown.

## Setup (≤ 10 minutes)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate     |  macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # then fill in the NeoStats LLM credentials
python -m ridewise.rag.ingest   # build the policy index (first run downloads the embedding model)
streamlit run app.py
```

Optional sanity checks:
```bash
python scripts/check_services.py     # LLM / embeddings / index / web: OK or FAIL
python scripts/demo_credentials.py   # sample customer_ids to sign in as
pytest -q                            # 65 offline tests
```

## Environment variables (`.env`)

| Variable | Purpose | Default |
|---|---|---|
| `LLM_BASE_URL` | NeoStats OpenAI-compatible endpoint | the event endpoint |
| `LLM_API_KEY` | event API key (**never commit**) | — |
| `LLM_MODEL` | deployment name | `Neo-Hackathon` |
| `LLM_REASONING_EFFORT` | `low` keeps gpt-oss fast | `low` |
| `EMBEDDINGS_ENABLED` | local e5 embeddings for retrieval | `true` |
| `EMBEDDING_MODEL` | sentence-transformers model | `intfloat/multilingual-e5-base` |
| `SUPABASE_DB_URL` | optional pgvector store | unset → local store |
| `WEB_SEARCH_ENABLED` / `TAVILY_API_KEY` | optional web search | `false` |

The app runs **offline** (no LLM key) too: it composes answers directly from the
retrieved evidence and still enforces all access control; NL→SQL analytics need
the LLM.

## How the LLM credentials are configured
Through environment variables only. `.env` is git-ignored; `.env.example` ships
with the variable names. No key is ever written to the repo, logs, or answers.

## Architecture

```
          ┌──────────── Streamlit UI (app.py) ────────────┐
          │  role/customer_id login · chat · Sources/SQL   │
          └───────────────────────┬────────────────────────┘
                                   │  (session rebuilt per turn)
                        orchestrator.py
   pre-checks → route → gather evidence → compose → validate → fallback
        │           │          │               │         │
        │           │          │               │         └ validate.py  (grounding)
        │           │          │               └ compose.py (+ template fallback)
        │           │          ├ db_scope.py  → scoped read-only :memory: DB  (SECURITY CORE)
        │           │          ├ sql_tool.py  → validated NL→SQL + entity bundles
        │           │          ├ policy/      → rules.yaml + selector + calc (Decimal money)
        │           │          └ rag/         → chunker + e5 embeddings + hybrid RRF retrieval
        │           └ llm.py (OpenAI-compatible, JSON, retries)
        └ action/entity regex pre-checks
```

Data sources: `data/ridewise.db` (unmodified) and `data/*.pdf` (+ verified
`data/transcriptions/` for the two scanned tables). Generated index lives in
`data/index/` (git-ignored).

## Known limitations
See `DECISIONS.md`. In short: NL→SQL analytics depend on the LLM; web search and
Supabase are off by default; multilingual/voice are not built; deposit *returns*
are not in the data (by policy) so they are explained, never asserted.
