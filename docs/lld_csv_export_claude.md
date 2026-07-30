# LLD: CSV Export from Transactions Page

**Status: built and verified (2026-07-30)**

Implemented as designed below, with one naming note: the design doc below refers to `filteredTransactions`, but the actual variable in `App.tsx` is `visibleTransactions` — same thing, just the pre-existing name in the codebase. Added `vitest` as the frontend's first unit test runner (zero-config with the existing Vite setup) since no frontend test infra existed yet; `transactionsToCsv` now has 2 passing tests covering CSV escaping (comma/quote in a free-text field) and blank-field rendering (uncategorized, no note). Live-verified in the browser: applied Category=Dining & Drinks + Month=July 2026 filters, clicked Export CSV, confirmed the downloaded file's rows/values matched the filtered table exactly, then deleted the test download. tsc and oxlint clean, no console errors.

## Goal

Let the user export the currently-filtered Transactions table to a CSV file, so they can pull a subset (e.g. one account, one month, one category) into Excel or elsewhere.

## Scope decision (confirmed with user)

Export **visible columns only** — the same 6 columns rendered in the table (`App.tsx` lines 359-364):

| Column | Source field |
|---|---|
| Date | `t.date` |
| Account | `accountById.get(t.account_id)?.name` |
| Description | `t.clean_description ?? t.description` |
| Category | `categoryById.get(t.category_id)?.name` (blank if uncategorized) |
| Note | `t.note` |
| Amount | `formatAmount(t.amount_cents)` — same formatting as the table (signed dollars, e.g. `-$42.10`) |

Explicitly **not** included: internal IDs, raw `amount_cents`, `memo`, transfer-match status, or any field not currently shown in the table. Keeping the export a straight mirror of what's on screen avoids a second "what should the export contain" decision surface, and it's easy to expand later if needed.

## Why this is small

The Transactions tab already loads the full transaction list into React state and applies all filters client-side (`App.tsx` lines 156-164). The export button operates on `filteredTransactions` — the exact same array already driving the table — so:
- No new backend endpoint.
- No new API call.
- No new filter logic to keep in sync with the table.

## Implementation plan

1. **New helper** in `frontend/src/format.ts` (next to the existing `formatAmount`): `transactionsToCsv(transactions, accountById, categoryById)` → returns a CSV string.
   - Header row: `Date,Account,Description,Category,Note,Amount`
   - One row per transaction, same column mapping as the table above.
   - Standard CSV quoting/escaping for any field containing a comma, quote, or newline (descriptions and notes are free text, so this matters).
2. **New button** in the Transactions tab toolbar (near the existing filters in `App.tsx`), e.g. "Export CSV".
   - On click: build the CSV string from `filteredTransactions`, wrap in a `Blob`, create an object URL, and trigger a download via a temporary `<a download>` click — no server round-trip.
   - Filename: `transactions_<YYYY-MM-DD>.csv` using today's date, or optionally reflecting the active month filter if set (e.g. `transactions_2026-07.csv`) — minor, can decide during implementation.
3. **No backend changes.** No new DB migration, no new route.

## Testing

- Frontend: a small unit test for `transactionsToCsv` covering the escaping case (a description containing a comma) and the uncategorized/no-note blank-field case.
- Manual/live verification: apply a few filters, export, open the file, confirm row count and values match what's on screen.

## Out of scope for this pass

- Server-side export (would matter if the transaction list ever stopped being fully loaded client-side, e.g. pagination — not the case today).
- Exporting columns not shown in the table.
- A configurable column picker.
