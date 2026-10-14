# LLD: Transactions tab - sort by date

Status: DRAFT, awaiting approval (2026-10-14)

## Request

Be able to sort the Transactions tab by date.

## Current behavior (after the cap fix, 2026-10-14)

- `GET /transactions` returns every row ordered `date DESC, id DESC` (196 dates in the live DB have
  more than one transaction, hence the tie-break).
- The frontend loads all of them and does all filtering client-side in `App.tsx`
  (`visibleTransactions`).
- The table header "Date" is plain text; there is no way to change the order.

## Prerequisite (done)

The 1000-row fetch cap that hid the oldest rows, and the backend `date DESC, id DESC` tie-break, were
fixed separately first - see `lld_transactions_fetch_cap_fix_claude.md`. The frontend now holds every
transaction, so a client-side sort is complete.

## Design

Sort client-side, after filtering, in `App.tsx`.

- New state: `dateSortDirection: "desc" | "asc"`, default `"desc"` (matches today).
- The "Date" header becomes a button; clicking toggles direction. It shows an arrow
  (down = newest first, up = oldest first) and sets `aria-sort` on the `<th>`.
- Tie-break on `id` in the same direction, so same-day rows have a stable, deterministic order
  that reverses cleanly when toggled (matches the backend's `date DESC, id DESC`).
- CSV export uses `visibleTransactions`, so it follows the on-screen order automatically. That's
  intended: export what you see.
- "Clear filters" does not reset sort (sort isn't a filter).
- Not persisted across reloads. Easy to add with localStorage later if wanted.

Why client-side: all rows are already in memory and every other filter is client-side; a server
round trip per click buys nothing.

### Out of scope (say if you want them)

- Sorting by other columns (amount, description, account, category). The design generalizes
  (`sortKey` + direction), and amount is the obvious next one - but not building it unasked.

## Size

Small. Roughly:

| Change | File |
|---|---|
| Sort state, comparator, clickable header | `frontend/src/App.tsx` |
| Pure `sortTransactionsByDate` helper (testable) | `frontend/src/format.ts` or new `sort.ts` |

## Tests

- Frontend (vitest): `sortTransactionsByDate` asc/desc, same-date tie-break by id, does not mutate
  its input.
- Live check: toggle to oldest
  first and confirm the first row is 2025-12-30 (matches `SELECT MIN(date)`); export CSV in asc
  order and confirm row count and order.
