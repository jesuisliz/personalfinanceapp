# LLD: Income breakdown by category (Dashboard)

**Status: built and verified (2026-08-05)**

Implemented as designed below. Live-verified in the browser (card renders, drill-down works including a refund landing in a spending category, month/account scoping, and the true empty state). Independently verified July 2026's income-by-category total via a raw `sqlite3` query against `finance.db` directly (no shared code with `aggregates.py`): six categories summing to $12,242.90, matching `income_breakdown()` exactly. Live-verified the chatbot: "Where does my income come from this July?" correctly called `get_income_breakdown` and narrated all six categories with the same numbers.

## Goal

The Dashboard's "Spending by category" card (`category_breakdown`) answers "where did my money go?" but there was no equivalent for "where did my money come from?" — `monthly_summary` shows a single income total per month, not a category breakdown. Per `PROJECT_CONTEXT.md`'s Definition of Success ("Where does my money come from?"), this was a real gap.

## Scope decision (confirmed with user)

**Mirror `category_breakdown` exactly** rather than restricting to a hardcoded "true income" category allowlist (`Income`, `Interest & Investments`, `RSU/Stock Sales`). Every positive-amount transaction is grouped by whatever category it's actually in, excluding Transfers/Credit Card Payment (same exclusion as spending, via the existing `_load_real_transactions`). This means a refund landing back in an ordinary spending category (e.g. a Travel refund) shows up under "Travel" on the income card too, rather than being hidden or reclassified — confirmed live: July 2026's real data includes exactly this (`Entertainment: $151.96`, `Shopping: $46.99`, `Home: $29.52` alongside `Income`, `RSU/Stock Sales`, `Interest & Investments`).

**Placement**: a third card alongside "Spending by category" and "Top merchants," always visible (not a toggle), ordered Income → Spending → Top merchants.

**Chat tool**: added in this same pass, not deferred — every other Phase 3 breakdown already has a matching Phase 4 tool wrapper.

## Why this is small

`category_breakdown`/`category_transactions` already do the negative-amount half of this; `_load_real_transactions` already loads the full unbounded transaction set per account with transfers/CC-payment excluded. The income-side functions are the same structure with the sign check flipped — no new schema, no new data.

## Implementation

### Backend

1. `backend/app/dashboard/aggregates.py`:
   - `income_breakdown(session, month, account_id) -> list[CategoryBreakdownOut]` — same structure as `category_breakdown`, keeps `t.amount_cents > 0` instead of `< 0`, sums `+t.amount_cents`. Reuses the existing `CategoryBreakdownOut` schema (identical shape).
   - `income_transactions(session, month, account_id, category_id, uncategorized) -> list[Transaction]` — same structure as `category_transactions`, sign check flipped to `> 0`.
   - Kept as separate sibling functions rather than parameterizing `category_breakdown`/`category_transactions` with a sign flag, consistent with this file's existing convention (`category_transactions` vs. `non_spending_category_transactions` are already separate, not parameterized).
2. `backend/app/routers/dashboard.py`: `GET /dashboard/income-categories` → `income_breakdown`, `GET /dashboard/income-categories/transactions` → `income_transactions` (same query params as their spending counterparts).
3. `backend/app/chat/tools.py`: added `get_income_breakdown` and `get_income_transactions` tool schemas + dispatch cases. `get_income_transactions` is a separate tool (not a flag on `get_category_transactions`) because the existing `get_category_transactions` only returns negative-amount rows — asking about an income-only category like "Interest & Investments" through it would silently return nothing. A dedicated tool lets the model pick based on the *question* ("where did this come from" vs. "what did I spend"), not by guessing a category's sign from its name.

### Frontend

1. `frontend/src/api.ts`: `fetchIncomeBreakdown`/`fetchIncomeTransactions`, mirroring `fetchCategoryBreakdown`/`fetchCategoryTransactions` (reuses the existing `CategoryBreakdown` interface — same shape).
2. `frontend/src/Dashboard.tsx`:
   - New `income`/`selectedIncomeCategory`/`incomeTransactions`/`incomeTransactionsLoading` state, folded into the existing month/account-scoped fetch effects alongside the spending equivalents.
   - Breakdown grid widened from `md:grid-cols-2` (2 cards) to `md:grid-cols-3` (3 cards): Income by category, Spending by category, Top merchants.
   - Extracted the drill-down transactions table (previously inline JSX, only used once) into a reusable `CategoryTransactionsTable` component, parameterized by title/transactions/loading/`amountColor`, so it isn't duplicated for the income drill-down. The income variant passes `amountColor="text-good"` (green) since these are inbound amounts, vs. the spending variant's default `text-critical` (red).
   - Empty-state copy: "No income in this period."

### Not changing

- `monthly_summary` and the trend charts are unchanged — this feature only adds a new breakdown card and its drill-down, same scope boundary as the existing "All months" feature (`lld_dashboard_all_months_claude.md`).
- No new schema — `income_breakdown` reuses `CategoryBreakdownOut` since the shape (`category_id`, `category_name`, `total_cents`) is identical to the spending side.

## Testing

Backend: 13 new tests across `test_dashboard.py` (income_breakdown/income_transactions: groups by category, income-only, includes a refund landing in a spending category, excludes transfers, excludes credit card payment, sorted descending, month-scoped, all-time when month omitted, uncategorized flag, sum-matches-breakdown-total consistency, excludes transfers on the transactions side) and `test_chat.py` (`get_income_breakdown`, `get_income_transactions`, all-time when month omitted). Full suite: 162 → 175 passing. `tsc -b` + `oxlint` clean.

Independent verification (raw SQL directly against `finance.db`, zero shared code with `aggregates.py`): July 2026 income-by-category — `Income` $7,309.90, `RSU/Stock Sales` $4,701.80, `Entertainment` $151.96, `Shopping` $46.99, `Home` $29.52, `Interest & Investments` $2.73, total $12,242.90 — matched `income_breakdown()`'s output exactly.

Live browser walkthrough: card renders in the new 3-column grid; clicking a row (e.g. "Fees & Adjustments") opens its drill-down table below with green amounts; clicking a spending category opens a second table below it (both drill-downs can be open simultaneously); switching the month dropdown re-scopes both breakdown cards and any open drill-down; scoping to an account/month with zero income shows "No income in this period." on the card and "No transactions found." on any stale open drill-down.

Live chat walkthrough: "Where does my income come from this July?" correctly invoked `get_income_breakdown` (confirmed by the returned tool-call JSON matching the six July categories exactly) and narrated the same numbers in prose.

Hit `dev_server_gotchas` gotcha #7 during verification: a stale 3-level `uvicorn --reload` process tree was still serving pre-edit code (`/dashboard/income-categories` 404'd) despite the process having started that morning. Killed the full tree (`Get-CimInstance Win32_Process -Filter "Name = 'python.exe'"`, 3 PIDs), confirmed the port was free, started a fresh server, and re-verified with a real request before trusting the browser.
