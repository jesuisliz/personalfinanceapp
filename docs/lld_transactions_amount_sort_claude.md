# LLD: Transactions tab - sort by amount

Status: IMPLEMENTED and verified (2026-10-14). Approved with the signed-value sort.

## Request

After the date sort (`lld_transactions_date_sort_claude.md`), also be able to sort the Transactions tab
by amount.

## Current behavior

- The Date header toggles newest/oldest first via `sortTransactionsByDate` in `frontend/src/sort.ts`,
  applied client-side after filtering in `App.tsx`. State: `dateSortDirection`.
- The Amount header is plain text.

## Design

One active sort column at a time (date or amount), plus a direction. Same client-side approach.

- State in `App.tsx` becomes `sort: { key: "date" | "amount"; direction: "asc" | "desc" }`,
  default `{ key: "date", direction: "desc" }` (today's behavior).
- Both headers are buttons. Clicking the **active** column flips its direction. Clicking the
  **inactive** column makes it active in its default direction:
  - Date: newest first (desc).
  - Amount: ascending, which means **biggest expenses first**.
- Only the active column shows an arrow and gets `aria-sort`; the other has `aria-sort="none"`.

### Amount sorts by the signed value (decision to confirm)

Sort on `amount_cents` as stored: expenses negative, income positive.

- Ascending: -$4,000 rent ... -$3 coffee ... +$50 refund ... +$5,000 paycheck.
- Descending: the reverse, biggest income first.

Why signed rather than by size (absolute value): it matches the existing Min/Max amount filter, which
is already signed ("expenses are negative"), so the two controls agree. And it keeps expenses and
income apart instead of mixing a $4,000 rent payment next to a $4,000 paycheck. The cost: "biggest
expenses first" lives under ascending, which is less intuitive to name. The tooltip spells it out.
Alternative if you'd rather have it: sort by size, so the biggest transactions in either direction
come first.

### Ties

- Amount ties (e.g. repeated $15.99 subscriptions) fall back to date, then id, in the **same direction**
  as the amount sort. Deterministic, and reverses cleanly. (Same rule as date-then-id today.)

### Unchanged from the date sort

- Applied after filtering. CSV export follows the on-screen order.
- "Clear filters" doesn't reset the sort. Not persisted across reloads.

## Code changes

| Change | File |
|---|---|
| Replace `sortTransactionsByDate(list, direction)` with `sortTransactions(list, key, direction)` | `frontend/src/sort.ts` |
| `sort` state, `toggleSort(key)` handler, Amount header button | `frontend/src/App.tsx` |

Why replace instead of adding a second function: one comparator with an ordered key list
(amount: amount, date, id; date: date, id) keeps the tie-break rule in one place. `sortTransactionsByDate`
has one caller, so nothing else changes.

## Tests

- vitest, `sort.test.ts`: the existing three date tests rewritten against `sortTransactions(..., "date", ...)`,
  plus:
  - amount asc and desc on a fixture mixing expenses and income, whose ids and dates don't follow amount
    order (so a date- or id-only sort fails);
  - amount tie falls back to date then id in the same direction.
- Mutation check: confirm an absolute-value comparator and a no-tie-break comparator each fail.
- Live: raw SQL oracle (`ORDER BY amount_cents, date, id`) for the first/last rows; toggle Amount in the
  app and match; switch back to Date and confirm it resets to newest first; CSV in amount order
  (blob captured in-page).

## Verification (2026-10-14)

- `frontend/src/sort.test.ts`: 7 tests (12 in the frontend suite), tsc and oxlint clean.
- Mutation check: eight wrong versions each fail at least one test: in-place sort, year-only and
  month-only date compare, whole-dollar amounts, absolute value, no amount tie-break, amount ties by id
  only, tie-breaks always ascending. The Codex review found four of these passing the first fixtures
  (shared fixture reordered before the no-mutation snapshot; ids rising with dates within a year; no
  cents-only amount pair; tie dates all on the 15th). Fixed by fixture changes only.
- Independent oracle (raw SQL on `finance.db`): `ORDER BY amount_cents, date, id` gives -$20,000,
  -$15,000, -$8,000 first; descending gives $20,000, $18,820.80, $15,000. The 11 rows at exactly
  -$1,000 run 01-05 ... 07-01, with the 06-01 pair as id 519 (Xoom) before 571.
- Live in the running app: all of the above matched on screen. Clicking the other column switches to
  its default direction (Date newest first, Amount biggest expenses first), clicking the active one
  flips it, and only the active column has an arrow and a non-"none" `aria-sort`. With Min = -1000,
  flipping Amount exactly reverses the -$1,000 group. CSV export (blob captured in-page, no download)
  matched all 1018 filtered rows in order, after collapsing whitespace: the CSV keeps raw descriptions
  like `IC* COSTCO BY IN   CAR` while the browser collapses repeated spaces on screen.
