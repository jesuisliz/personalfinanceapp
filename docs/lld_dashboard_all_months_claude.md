# LLD: "All months" option for Dashboard category/merchant breakdowns

**Status: built and verified (2026-07-30)**

Implemented as designed below. Live-verified in the browser after a dev-server restart (the `--reload` watcher silently missed the initial edit — see `dev_server_gotchas` memory). Independently verified two all-time totals via raw `sqlite3` queries against `finance.db` directly (no shared code with `aggregates.py`): "Dining & Drinks" category ($9,011.10, 210 txns) and "Xoom Transfer" merchant ($7,543.18, 11 txns) both matched the API exactly.

## Goal

The Dashboard's "Spending by category" and "Top merchants" cards are driven by a single "Month" dropdown (`Dashboard.tsx` lines 270-283) that currently only offers the trailing 6 months (whatever `fetchMonthlySummary(6, ...)` returned). Add an "All months" option to that dropdown.

## Scope decision (confirmed with user)

**"All months" means true all-time** — every transaction ever imported for the selected account(s), not bounded to the 6-month window that drives the trend charts above it. This means the category/merchant totals can be larger than, and won't visually reconcile with, the "Monthly income vs. expenses" / "Net savings trend" charts directly above — that's expected, since those two charts stay fixed at a 6-month trailing window (`MONTHS_HISTORY = 6`, unchanged by this feature).

## Why this is small

`backend/app/dashboard/aggregates.py::category_transactions()` already accepts `month: str | None` and skips the month filter entirely when `None` — built for the chatbot's `get_category_transactions` tool (see [[phase4-status]]). `category_breakdown()` and `top_merchants()` don't have this yet; they take `month: str` and hard-filter `_month_key(t.date) != month`. Extending the exact same optional-month pattern to these two is a small, low-risk change — `_load_real_transactions()` already loads the full unbounded transaction history for the account, so "skip the month filter" is genuinely all we need for true all-time totals.

## Implementation plan

### Backend
1. `aggregates.py::category_breakdown(session, month: str | None, account_id)` — skip the `_month_key(t.date) != month` check when `month is None`.
2. `aggregates.py::top_merchants(session, month: str | None, account_id, limit)` — same change.
3. `routers/dashboard.py`:
   - `GET /dashboard/categories`: `month: str` → `month: str | None = None`.
   - `GET /dashboard/merchants`: `month: str` → `month: str | None = None`.
   - (`/dashboard/categories/transactions` already supports `month: str | None` — no change needed there, but see frontend note below.)

### Frontend
1. `api.ts`: widen `fetchCategoryBreakdown`, `fetchTopMerchants`, and `fetchCategoryTransactions` to accept `month: string | null`, omitting the `month` query param entirely when `null` (matches the existing `account_id` omit-when-null pattern already used in these same functions).
2. `Dashboard.tsx`:
   - Add an `"All months"` option to the Month `<select>` (a sentinel value, e.g. `""`, mapped to `selectedMonth === null`).
   - Update the two `useEffect`s that fetch categories/merchants and category-transactions to pass `selectedMonth` straight through (already typed as `string | null`, so this mostly just relaxes the API layer to match).
   - Drill-down header (`{selectedCategory.category_name} transactions — {monthLabel(selectedMonth!)}`) needs a branch for the all-months case, e.g. `selectedMonth ? monthLabel(selectedMonth) : "All time"`.
   - Card empty-state copy ("No spending this month.") should read "No spending in this period." or similar so it doesn't say "month" when "All months" is selected — minor copy tweak.

### Not changing
- `monthly_summary()` / the two trend charts stay exactly as they are (trailing 6 months, no "all months" toggle) — this feature only touches the category breakdown and top-merchants cards and their shared dropdown.

## Testing

- Backend: extend existing `category_breakdown`/`top_merchants` tests with an all-time case (`month=None`) — e.g. seed transactions across 3+ months, assert the all-time total equals the sum of the per-month totals.
- Manual/live verification: select "All months", confirm the category list sums to more than any single visible month, spot-check one category's total against a raw SQL sum with no month filter (per [[feedback-independent-verification]] — don't just re-call `aggregates.py` to check itself).

## Out of scope for this pass

- Adding "All months" to the trend charts or the top-level stat tiles (Income/Expenses/Net/Savings rate) — those are a separate, larger change (they'd need to stop assuming a fixed 6-month window) and weren't asked for.
- A custom date-range picker — "All months" is the only new option, not an arbitrary range.
