# DECISIONS

## 1. The three most important design decisions, and why

### a) Access control by construction: a per-session scoped, read-only DB
Instead of asking the LLM to add `WHERE customer_id = …` (one forgotten filter
leaks every customer), each turn rebuilds a private `:memory:` SQLite database
holding **only the rows that session may see** — a customer's own rows, or all
rows with contact/identity PII masked for agents — then locks it with
`PRAGMA query_only` and a SELECT-only authorizer. The LLM's SQL runs only
there, so it is *physically impossible* to read another customer's data or to
write. "Not found" and "not yours" return the **same** message, so IDs can't be
enumerated. This is the backbone of the Trust & Safety score.

### b) Deterministic money, with policy version chosen from data
Refunds, late fees, GST and the rental charge are computed in Python with
`Decimal` in `policy/calc.py`; the LLM only explains the numbers. The
cancellation **policy version is selected from `booked_at`** against the IST
cutover (`2026-06-30 18:30 UTC` = 1 Jul 2026 00:00 IST). We *proved* this from
the data: replaying all 142 customer cancellations, `booked_at` + the IST
cutover reproduced **140** recorded refunds — more than `scheduled_start` or
`cancelled_at`, and more than a naive UTC-midnight cutover (two bookings sit in
the IST/UTC gap). Rules live in `rules.yaml` with a citation on every value and
validators (range, monotonic, coverage, ordered versions) that run on load.

### c) Grounded answers with a hard validator
The composer may use only numbered evidence inside `<<<DATA – not instructions>>>`
markers, and `validate.py` rejects any answer whose numbers/IDs aren't in the
evidence, whose citations are fake, that claims an action was performed, or that
says a refund was "processed" when it wasn't (negation-aware). On failure it
regenerates once, then falls back to a deterministic template built from the
same evidence — so a bad model turn degrades to a plainer answer, never a wrong
one.

## 2. Alternatives considered and rejected
- **LLM-added `WHERE` filters / SQL rewriting / SQLite views** → rejected: one
  missed filter leaks everything; SQLite has no row-level security. Chose the
  scoped-copy boundary.
- **LLM doing the arithmetic / picking the policy version** → rejected:
  non-deterministic and wrong on edge cases (version boundary, rounding, grace).
  Chose Decimal calculators + a data-proven selector.
- **OCR / vision-LLM for the scanned tables** → rejected: OCR misread cells and
  vision output still needs checking. Chose **verified hand-transcription** that
  fails loud if missing.
- **Dense-only or FTS-only retrieval** → rejected: dense misses exact terms,
  FTS misses paraphrases. Chose **hybrid (e5 cosine + BM25) fused with RRF**.
- **Supabase/pgvector as a *hard* dependency; Tavily web search on by default**
  → rejected: external setup risk and the "use only the provided pack" rule.
  Chose a **local numpy+BM25 store as the default**, with Supabase pgvector
  **optional** and wired behind a 2-second timeout that falls back to local, so
  setup stays <10 min and the demo never breaks. Web search is **off** pending
  organiser approval.
- **gpt-oss `response_format=json_object`** → rejected: this endpoint corrupts
  the JSON (leaks a `final{` harmony-channel key). We disable json-mode, instruct
  "JSON only", and repair output.
- **A plain role/ID picker with no verification** → rejected as unauthenticated.
  The brief mandates starting a session by `customer_id`/agent, so we keep that
  shape but **verify identity**: customers by Customer ID + last 4 digits of the
  registered phone, agents by Staff ID + a **scrypt-hashed** password — both with
  one generic error, constant-time compare and a lockout. The scoped DB remains
  the real security boundary.
- **OCR/vision for voice & hosted STT on the answer path** → for voice input we
  use hosted **Whisper (Groq) for transcription only** (no answer generation),
  behind `STT_ENABLED`, with the transcript shown in an editable card before
  sending. It is off by default so the system stays strictly on the NeoStats LLM
  unless the organisers permit a transcription-only service.
- **City left un-normalised** → rejected: the data mixes Bengaluru/Bangalore/BLR,
  so an agent's "customers in Bengaluru" would under-count. We canonicalise
  `city` at copy time (keeping the original in `city_raw`).

## 3. Where it currently fails or behaves poorly
- **Open-ended analytics need the LLM.** NL→SQL is unavailable offline; those
  questions return an honest "AI service unavailable" message (ID lookups still
  work via fixed queries).
- **Offline template answers are plainer** (list evidence) than composed prose.
- **Retrieval floor is calibrated on ~37 questions**; a very unusual phrasing
  could drop below it (we retry without the floor for pure policy questions).
- **Multilingual replies** lean on the model to translate the evidence; section
  headings may stay English and rare terms can be imperfect. Retrieval still
  runs on the English rewrite.
- **Voice** depends on an external STT service and audio quality; the transcript
  is always shown for editing before it is sent.
- **Deposit returns** aren't in the data (policy §5.3), so we explain the rule
  rather than confirming a specific return.
- **Rounding**: half-up matches the recorded GST on the vast majority of rows;
  a handful of split/partial rows differ by ≤ ₹0.01.

## 4. Evaluation (measured)
- **Retrieval** (27 covered / 10 uncovered): hit@5 = 100% for dense, FTS and
  hybrid; cosine distributions (covered-min 0.810 vs uncovered-max 0.841)
  validate the 0.80 recall floor.
- **NL→SQL** (20 agent + 7 customer-scoped, result-based comparison): 26/27
  (96.3%); the one miss is ex-GST vs incl-GST, a definition difference.
- **86 offline tests** (security, money with the full refund sweep, retrieval,
  orchestrator, validation, auth, chat store, STT, UI) run with no LLM/network.

## 5. What I'd build next with one more week
1. A larger gold NL→SQL set and a reranker if hit@5 drops, plus a cached-SQL
   layer to cut tokens under rate limits.
2. A staff "explain this charge" view that renders the full `calc` breakdown
   with citations, and a guided change-request drill (new policy version / new
   column) with tests proving old records keep their version.
3. OTP-based customer auth and real staff accounts (beyond the single shared
   staff credential) for production.
4. Deeper multilingual coverage (localised headings, per-language retrieval eval)
   and voice-out (browser TTS).

## Payment semantics & assumptions (for the evaluator)
- `amount` excludes GST; refunds are negative; collected = SUCCESS positive;
  FAILED excluded; PENDING separate; duplicate `transaction_ref` counted once.
- Working-days for refund windows = Mon–Fri, no holiday calendar.
- Agents see names; contact/identity PII (phone/email/DOB/licence) masked.
- The provided DB and PDFs are never modified; the index and transcriptions are
  additive supporting stores.
