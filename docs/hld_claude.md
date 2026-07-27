# High-Level Design — Personal Finance App

## 1. Purpose

A local-only personal finance app that imports CSV statements from multiple banks and credit cards into a single SQLite database, normalizes them into a consistent transaction model, and helps answer questions about spending habits, trends, and long-term financial planning.

Source docs: `CLAUDE.md`, `PROJECT_CONTEXT.md`.

Guiding principles carried into every design decision below:
- Accuracy over features. Never guess financial data.
- All calculations happen in application code — the LLM explains, it never computes.
- Keep everything local unless explicitly told otherwise.
- Don't over-engineer. Build for the roadmap phase we're actually on.

## 2. Tech Stack

| Layer | Choice |
|---|---|
| Frontend | React + TypeScript + Vite + Tailwind |
| Backend | FastAPI (Python) |
| ORM / DB | SQLAlchemy + SQLite |
| Charts | Recharts |
| AI | OpenAI API (via `.env` key) — interpretation, categorization suggestions, insight explanations only |

## 3. System Architecture

```
data/*.csv (manual downloads)
        │
        ▼
┌───────────────────────┐
│  Import Pipeline       │
│  - account config       │
│  - per-bank parser       │
│  - normalizer            │
│  - dedupe check          │
└───────────────────────┘
        │
        ▼
┌───────────────────────┐
│  SQLite DB              │
│  accounts, transactions,│
│  categories, rules       │
└───────────────────────┘
        │
        ▼
┌───────────────────────┐        ┌───────────────────────┐
│  FastAPI backend        │◄──────►│  OpenAI API             │
│  - REST endpoints        │        │  (categorize, explain,   │
│  - all calculations       │        │   chat interpretation)   │
└───────────────────────┘        └───────────────────────┘
        │
        ▼
┌───────────────────────┐
│  React frontend         │
│  - transactions table    │
│  - dashboard/charts (phase 3, built) │
│  - chatbot UI (phase 4, built)  │
│  - planning: goals/runway/scenario (phase 5, built) │
└───────────────────────┘
```

The AI layer never sits between the database and the numbers shown to the user — it only annotates (suggested category) or narrates (explains a total the backend already computed).

## 4. CSV Import Pipeline

### 4.1 Known source formats

Five sample statements currently in `data/`, each structurally different:

| Source | Key columns | Sign convention |
|---|---|---|
| Chase (checking/credit, e.g. `Chase3403`, `Chase5947`) | `Transaction Date, Post Date, Description, Category, Type, Amount, Memo` | negative = spend |
| Bank of America (`ExportData_BOA.csv`) | `Status, Date, Original Description, Split Type, Category, Currency, Amount, User Description, Memo, Classification, Account Name, Simple Description` (UTF-8 BOM) | negative = spend |
| US Bank (`US Bank - 8606_...csv`) | `Date, Transaction, Name, Memo, Amount` | unsigned; direction comes from `Transaction` (e.g. `CREDIT`) |
| American Express (`AmericanExpress_activity.csv`) | `Date, Description, Amount` | **inverted**: positive = charge, negative = payment/credit |

Each format gets its own parser module. New banks get a new parser, not a change to existing ones. Amex is the reminder why this matters: its sign convention is the opposite of every other source (a charge is *positive* and a payment is *negative*), so its parser negates the raw amount rather than passing it through — a mistake here would silently flip every dollar amount on that account.

### 4.2 Account mapping (config-driven)

A small config file (`backend/app/imports/accounts.yaml`) maps filename patterns to account metadata. Adding a new statement source means adding one config entry (and a new parser module if the format is new) — no changes to core import logic. The exact schema, and a worked example of why this needed to become a *list* of accounts per file rather than one, is in `lld_claude.md` §3 — kept in one place rather than duplicated here, since a second copy of the literal YAML is exactly what went stale the first time this doc was written (see that section's note on the real BOA file turning out to hold four accounts, not the two originally assumed from a partial preview).

### 4.3 Normalization

All parsers output a common intermediate shape before insert:

```
NormalizedTransaction:
  account_id
  date              # ISO 8601
  posted_date        # optional, ISO 8601
  description         # raw, as exported by bank
  amount              # signed decimal, negative = expense, positive = income
  raw_category         # bank-provided category, kept for reference
  memo
  source_row_hash      # for dedupe
```

Sign convention is normalized at parse time (decision already made): everything becomes negative = expense, positive = income/credit, regardless of how the source bank represents it (US Bank's `CREDIT`/`DEBIT` type column gets translated into a signed amount).

### 4.4 Duplicate prevention

Each imported row gets a deterministic hash (e.g. account_id + date + amount + description) stored as `source_row_hash`, unique per account. Re-importing the same statement — or an overlapping date range from a re-downloaded export — is a no-op rather than a duplicate insert.

## 5. Data Model (initial)

```
accounts
  id, name, institution, account_type

transactions
  id, account_id (FK), date, posted_date, description,
  amount, raw_category, memo, source_row_hash (unique per account),
  category_id (FK, nullable — phase 2), is_transfer (bool, phase 2)

categories                # phase 2
  id, name, parent_id (nullable, for subcategories)

category_rules            # phase 2, merchant cleanup
  id, match_pattern, category_id
```

Kept intentionally minimal for Phase 1. Categories, rules, and transfer detection are added in Phase 2 rather than speculatively now.

## 6. Roadmap Alignment & Success Criteria

Each phase's criteria are written to be checkable against the app, not aspirational — pulled from the "Definition of Success" in `PROJECT_CONTEXT.md` and made concrete per phase. A phase isn't "done" until its own criteria hold; later phases build on that, they don't retroactively fix it.

### Phase 1 — CSV import, normalize, store, dedupe, display

**Status: complete** (2026-07-27). Covered by Sections 3–5 of this doc, `lld_claude.md` in full, and `lld_claude.md` §13 for the frontend. All five criteria below were checked against the running app with real data, not just tests — see `lld_claude.md` §11 and §13 for how.

Success criteria:
- All five known statement formats (Chase, BOA, US Bank, American Express) import without manual data massaging.
- Every imported transaction has a correct, human-verified sign (spend negative, income positive) — spot-checked against the original statement, including Amex, whose source file uses the opposite convention from the others.
- Re-importing the same file (or an overlapping-date re-download) produces zero duplicate rows — while genuinely repeated real transactions (confirmed in the Amex sample: two identical same-day charges from two cardholders on one shared card) are both kept, not collapsed into one.
- Every transaction is traceable to one `Account` — including BOA's multi-account file being split correctly into all four real accounts it contains (two credit cards, checking, savings — confirmed by running the pipeline against the full real file, not assumed from a preview).
- Transactions are visible in a plain list/table in the running app — not just present in the DB.
- No transaction is silently dropped or guessed; malformed rows, and rows belonging to an account the config doesn't yet recognize, fail the import loudly rather than being misattributed (see LLD §8).
- Per-account totals computed by the app match an independent hand-sum of the raw CSVs — actually verified, not just structurally plausible.

### Phase 2 — Categories, manual editing, merchant cleanup, transfers/CC payments

**Status: complete** (2026-07-27). Full design in `lld_phase2_claude.md`. All criteria below verified against the real 654-transaction database (see that doc §9), not just tests.

Success criteria:
- Every transaction can be assigned a category, either automatically (rule-based) or by hand. — confirmed.
- Recategorizing a transaction is a simple, fast manual action — no need to re-import. — confirmed live in the UI.
- A credit card payment made from a checking account nets to zero across the two accounts, not double-counted as an expense in one and ignored in the other. — confirmed via the real BOA $4,284.66 pair.
- Internal transfers between your own accounts are identifiable and excluded from spending totals. — confirmed (`is_transfer` + "Transfers" category, both required — see Phase 3/4 notes below on why category alone isn't sufficient).

### Phase 3 — Dashboard: income vs. expense, spending by category, top merchants, trends, six-month summary

**Status: complete** (2026-07-27), plus two user-requested additions beyond the original scope: an "Uncategorized only" filter on the Transactions tab, and click-to-drill-down from any category in the breakdown to its underlying transactions. No dedicated LLD was written for this phase (a gap the project noted and corrected starting with Phase 4) — see memory `phase3_status` for the full design record: `backend/app/dashboard/aggregates.py` + `backend/app/routers/dashboard.py`, `frontend/src/Dashboard.tsx`.

Success criteria:
- You can answer, from the dashboard alone and without doing mental math: "How much came in this month?" and "How much went out?" — confirmed (six-month summary stat tiles + monthly bar chart).
- You can identify your largest spending categories and top merchants at a glance. — confirmed (ranked bar lists, sorted descending).
- You can see how spending in a category has changed over the last six months. — confirmed (net savings trend chart; per-category month-over-month via Phase 4's `get_category_trends` tool, which reuses this phase's `category_breakdown`).
- Every number on the dashboard is traceable back to the underlying transactions (no black-box totals). — confirmed twice: once via the category drill-down feature itself, and independently via raw SQL directly against `finance.db` (bypassing all app code) matching the displayed totals exactly.

### Phase 4 — Financial chatbot (OpenAI)

**Status: built and unit-verified** (2026-07-27); **live validation with real questions deferred** until a real `OPENAI_API_KEY` is added (the user's explicit choice — the app works fully without one, the Chat tab just shows a clear configuration error). Full design in `lld_phase4_claude.md`.

Success criteria:
- You can ask a natural-language question ("How much did I spend eating out?") and get a correct answer. — **not yet verified live** (needs a real API key); architecture (OpenAI tool-calling) and orchestration logic are unit-tested with a fake client, 92/92 tests passing.
- Every number in a chatbot answer was computed by backend code, never invented or estimated by the model — verified by spot-checking a chatbot answer against the dashboard/raw data. — mechanism is in place (every reply shows its underlying tool-call data in the UI) but the actual spot-check against a real model response is part of the same deferred live validation.
- The chatbot correctly declines or asks for clarification when a question is ambiguous, rather than guessing which numbers to use. — partially covered: an unrecognized category name produces a tool error the model can recover from rather than a crash (unit-tested); true ambiguity-handling in a live conversation is untested until a real key exists.

### Phase 5 — Savings goals, vacation planner, runway, scenario analysis

**Status: complete and independently verified** (2026-07-27), built ahead of Phase 4's live validation being finished (the user's explicit choice — Phase 5 doesn't depend on the chatbot working, only on the dashboard's aggregates, which were already complete). Full design in `lld_phase5_claude.md`. First new persisted data since Phase 1 (`SavingsGoal`, `CurrentBalance`) — everything else so far had been pure aggregation over transactions.

Success criteria (from `PROJECT_CONTEXT.md`'s Definition of Success):
- You can set a savings goal (e.g. vacation cost) and see a realistic timeline based on actual saving patterns, not a guess. — confirmed: a real goal against the actual 6-month history correctly returned `not_on_track` (average net savings independently verified at -$380.18/month via raw SQL) rather than fabricating an on-track timeline — the honest-refusal case, not just the easy positive case.
- You can answer "what does my financial runway look like if I leave my job?" using real historical spending data. — confirmed live: a manually-entered $3,000 balance produced `runway_months = 1.0143263453010318` against a $4,929.38 average monthly expense, both independently reproduced exactly via raw SQL run outside the app entirely.
- Scenario analysis (e.g. "reduce dining by 25%") reflects a real, computed projection — not an LLM estimate. — confirmed: reuses Phase 4's `estimate_category_reduction_savings` unchanged (the $1,256.99/month dining average matched Phase 3/4's already-verified number exactly), composed onto the goal/runway figures via new `apply_scenario_to_*` functions, not a new or duplicated calculation.
- The vacation planner is the same code path as a savings goal, not a separate feature, per the user's explicit scope decision — no vacation-specific code exists.
- Full backend test suite: 114/114 passing; `tsc -b` + `oxlint` clean.

## 7. Explicit Non-Goals (current phase)

- No bank integrations / Plaid.
- No cloud deployment or hosting.
- No multi-user support or auth.
- No git/version control setup yet (deferred by user, revisit later).
- No LLM-driven arithmetic — categorization suggestions and chat explanations only.

## 8. Open Questions / Revisit Later

- ~~Exact file/folder layout for backend~~ — resolved: `app/imports/`, `app/categories/`, `app/transfers/`, `app/dashboard/`, `app/chat/`, `app/routers/`, one business-logic module per domain area, routers stay thin.
- ~~Whether account config lives as YAML or JSON~~ — resolved: YAML (`app/imports/accounts.yaml`).
- Git initialization and `.gitignore` scope (`data/`, `*.db`, `.env`) — still deferred until user asks; still not a git repository as of 2026-07-27.
