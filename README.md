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

## Features
- **Two roles, enforced in code** — customers see only their own rows; agents
  see all rows with contact/identity PII masked.
- **Authentication** — customers sign in with Customer ID + last 4 digits of
  their phone; agents with a Staff ID + scrypt-hashed password.
- **Grounded, cited answers** with a hard validator and a deterministic
  offline fallback.
- **Deterministic money** (refunds with v1/v2 selection, late fees with tier
  grace, EV low-battery fee, GST) in `Decimal`.
- **Hybrid retrieval** (e5 embeddings + BM25, RRF) over the policy docs, served
  from **Supabase pgvector** when configured, with an automatic **local
  fallback**.
- **Multilingual replies** (English, हिन्दी, ಕನ್ನಡ, தமிழ், മലയാളം) chosen in the UI.
- **Voice input** via hosted Whisper (Groq) — transcription only, editable
  before sending, behind a flag.
- **Persistent per-identity chat history** with a conversation sidebar.
- **LangSmith tracing**, off by default.

## Setup (≤ 10 minutes)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate     |  macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                    # fill in the NeoStats LLM credentials
python scripts/set_agent_password.py    # set the support-agent (staff) password
python -m ridewise.rag.ingest           # build the policy index (first run downloads the embedding model)
streamlit run app.py
```

Optional: to use Supabase pgvector instead of the local store, set
`SUPABASE_DB_URL` in `.env`, then:
```bash
python scripts/migrate_supabase.py      # create the table + hybrid RRF function
python -m ridewise.rag.ingest           # also upserts chunks + vectors to Supabase
```

**Signing in**
- **Customer**: Customer ID + the last 4 digits of the registered phone
  (`python scripts/demo_credentials.py` lists sample IDs with their last-4).
- **Support agent**: Staff ID (default `agent`) + the password you set above.

Sanity checks and evaluation:
```bash
python scripts/check_services.py     # LLM / embeddings / index / web: OK or FAIL
pytest -q                            # 86 offline tests (hermetic: no LLM/network)
python scripts/eval_retrieval.py     # hit@5 / MRR for dense / FTS / hybrid + floor
python scripts/eval_sql.py           # NL->SQL vs gold queries (needs the LLM)
```

## Environment variables (`.env`)

| Variable | Purpose | Default |
|---|---|---|
| `LLM_BASE_URL` | NeoStats OpenAI-compatible endpoint | the event endpoint |
| `LLM_API_KEY` | event API key (**never commit**) | — |
| `LLM_MODEL` | deployment name | `Neo-Hackathon` |
| `LLM_REASONING_EFFORT` | `low` keeps gpt-oss fast | `low` |
| `EMBEDDINGS_ENABLED` / `EMBEDDING_MODEL` | local e5 embeddings | `true` / `intfloat/multilingual-e5-base` |
| `SUPABASE_DB_URL` | optional pgvector store (Session pooler URI) | unset → local store |
| `AGENT_ID` / `AGENT_PW_HASH` | staff login (hash set via the script) | `agent` / — |
| `STT_ENABLED` / `GROQ_API_KEY` / `STT_MODEL` | voice input (Whisper) | `false` / — / `whisper-large-v3` |
| `WEB_SEARCH_ENABLED` / `TAVILY_API_KEY` | optional web search | `false` |
| `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` | tracing | `false` / — / `ridewise-assist` |

The app runs **offline** (no LLM key) too: it composes answers directly from the
retrieved evidence and still enforces all access control; NL→SQL analytics need
the LLM.

## How the LLM credentials are configured
Through environment variables only. `.env` is git-ignored; `.env.example` ships
with the variable names. No key is ever written to the repo, logs, or answers.

## Architecture

```
          ┌──────────────── Streamlit UI (app.py) ────────────────┐
          │ login (id+last4 / staff pw) · chat · history sidebar   │
          │ language select · voice-in · Sources/SQL/Copy popovers │
          └───────────────────────────┬────────────────────────────┘
                                       │  (scoped DB rebuilt per turn)
                            orchestrator.py
       pre-checks → route → gather evidence → compose → validate → fallback
            │          │          │               │          │
            │          │          │               │          └ validate.py (grounding)
            │          │          │               └ compose.py (+ template fallback)
            │          │          ├ db_scope.py → scoped read-only :memory: DB (SECURITY CORE)
            │          │          ├ sql_tool.py → validated NL→SQL + entity bundles
            │          │          ├ policy/     → rules.yaml + selector + calc (Decimal)
            │          │          └ rag/        → chunker + e5 + hybrid RRF (Supabase | local)
            │          └ llm.py (OpenAI-compatible, JSON, retries)   stt.py (Whisper)
            └ action/entity regex pre-checks                         tracing.py (LangSmith)
```

Data sources: `data/ridewise.db` (unmodified) and `data/*.pdf` (+ verified
`data/transcriptions/` for the two scanned tables). The generated index
(`data/index/`) and chat history (`data/chat_history/`) are git-ignored.

## Evaluation results
- **Retrieval** (`eval_retrieval.py`, 27 covered / 10 uncovered): **hit@5 = 100%**
  for dense, FTS and hybrid. Cosine distributions (covered-min 0.810 vs
  uncovered-max 0.841) confirm the **0.80 recall floor**.
- **NL→SQL** (`eval_sql.py`, 20 agent + 7 customer-scoped): **26/27 (96.3%)**.
  The single miss is an ex-GST vs incl-GST definition difference, not an error.

## Known limitations
See `DECISIONS.md`. In short: open-ended analytics depend on the LLM (offline
they degrade to an honest "service unavailable" for NL→SQL while ID lookups
still work); voice/web/Supabase/tracing are behind flags; deposit *returns* are
not in the data (by policy) so they are explained, never asserted.
