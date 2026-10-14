# LLD: Fix - Transactions tab silently drops rows beyond 1000

Status: DRAFT, reviewed 2026-10-14 - Opus (9 findings, all verified + applied) and Codex (6 findings; test hardening and a stale doc line applied, pagination-loop redesign rejected - see below). Approved and implemented 2026-10-14. Prerequisite for `lld_transactions_date_sort_claude.md`.

## Bug

The Transactions tab shows at most the newest 1000 transactions. Anything older is silently absent.

### Evidence (live DB `backend/finance.db`, 2026-10-14)

- `SELECT COUNT(*) FROM transactions` = **1044** (dates 2025-12-30 .. 2026-10-12).
- `frontend/src/api.ts` `fetchTransactions` sends `limit=1000`.
- `backend/app/routers/transactions.py` `list_transactions`: `limit: int = Query(default=100, le=1000)`,
  ordered `date DESC`, so the server returns the newest 1000 and the oldest 44
  (2025-12-30 .. 2026-01-10) never reach the browser.

### Impact

Everything on the Transactions tab is computed client-side from that capped array (`allTransactions`
in `App.tsx`):

- the table itself
- every filter (account, category, month, merchant, amount, uncategorized)
- the month dropdown (`availableMonths`). The 44 dropped rows are 6 from Dec 2025 and 38 from
  Jan 2026. December cannot be selected at all; worse, **January 2026 is selectable but shows only
  78 of its 116 rows**, with nothing indicating it is incomplete.
- CSV export (`handleExportCsv` uses `visibleTransactions`)
- Latent: the suggested-transfer review UI (`App.tsx` ~261) silently skips a match whose transaction
  isn't loaded (`if (!txnA || !txnB) return null`). No current effect - the live DB has 0 suggested
  matches (74 confirmed, 23 rejected) - but a future match involving an old row would vanish.

The cut is also nondeterministic: rows 1000 and 1001 (newest-first) both fall on 2026-01-10, which has
8 rows, and the query orders by `date DESC` only, so which of those 8 are dropped is unspecified.

Not affected: Dashboard and chat - they aggregate server-side via `app/dashboard/aggregates.py`
and never call `GET /transactions`.

There is no error or indicator; the UI looks complete. It will get worse with every import.

### Root cause

A hard-coded page size on a screen that is designed around having the full set (all filtering,
the month list, and export are client-side). The 1000 cap was a Phase 1 default that the data has
now outgrown.

## Fix

Return all rows when the caller doesn't ask for a limit.

Backend - `list_transactions`:

```python
limit: int | None = Query(default=None, ge=1),
...
stmt = stmt.order_by(Transaction.date.desc(), Transaction.id.desc()).offset(offset)
if limit is not None:
    stmt = stmt.limit(limit)
```

- `limit` omitted -> all matching rows (behavior change: default was 100).
- `limit` supplied -> honored, no upper bound, must be >= 1 (today `limit=0` or negative is
  accepted; SQLite treats a negative LIMIT as "no limit").
- `offset` unchanged, and still applied when `limit` is omitted (SQLAlchemy 2.0 on SQLite compiles
  this to `LIMIT -1 OFFSET ?`, verified).
- Tie-break on `id DESC` (moved here from the sort spec): makes `limit`/`offset` deterministic and
  test 2 exact. Costs one clause.
- Verified on the installed FastAPI 0.115.6: omitted -> `None`; `0`, `-1`, empty, non-numeric -> 422.

Frontend - `fetchTransactions`: stop sending `limit`.

### Why this and not pagination

- ~1k rows is a few hundred KB of JSON against a local SQLite DB; load time is not a concern at this
  scale, and won't be for years of personal transactions.
- Server-side pagination would require moving every filter, the month list and CSV export to the
  backend - a large change with no user-visible benefit at this size.
- Revisit if the table ever gets slow to render (likely 10k+ rows); that would be a virtualization or
  pagination project of its own.

### Why change the default instead of raising the cap to e.g. 10000

Any fixed cap reproduces this exact bug later, silently. The only consumer of this endpoint is the
Transactions tab, which needs every row.

### Considered and rejected (Codex review)

Codex suggested keeping the server default/max and having the frontend loop `limit=1000&offset=...`
until a short page. Rejected: there are no external callers of this local single-user API to keep
compatible with (callers checked below), and a client paging loop adds code and a new failure mode
(partial loads) for zero benefit at this size. Accepted residual: an absurd explicit `limit` (e.g.
`10**20`) can overflow SQLite's 64-bit integer and return a 500 instead of a 422. Only reachable by
hand-crafting a URL; not worth a bound that reads like a new cap.

### Callers checked

`GET /transactions` callers: `frontend/src/api.ts` `fetchTransactions` (only caller in the frontend),
and `backend/tests/test_api.py` (small fixtures, unaffected by the default change). The chat tools and
dashboard use their own aggregate functions, not this endpoint.

## Tests

Test setup: `make_client()` in `test_api.py` hides its sessionmaker, and the import route would need a
1000-row CSV fixture. Add a sibling helper that returns both the client and the sessionmaker
(`make_client` delegates to it, so existing tests are untouched), and insert rows directly with
`session.add_all` (one account, distinct dates/ids). 1001 inserts into in-memory SQLite is fast.

1. Backend regression (no cap by default): insert 1001 transactions, `GET /transactions` with no
   `limit`, assert `len == 1001` AND the returned ids equal the inserted ids in exact newest-first
   order (catches dropped rows, duplicates, and wrong order). Fails on current code (returns 100).
   Accepted limitation: a larger fixed server cap (e.g. 5000) would still pass; that is a deliberate
   tradeoff vs. inserting arbitrarily many rows. Noted in the test's docstring.
2. Backend: an explicit `limit` above the old 1000 max is accepted - `?limit=1001` on the same
   dataset returns 1001 rows (currently 422).
3. Backend: ordering + tie-break, on a small mixed fixture where insertion/id order deliberately
   differs from date order and two rows share a date. Assert the exact ordered id list for: no params;
   `?limit=3` (the page boundary falls inside the same-date pair); `?offset=2` with no limit;
   `?limit=2&offset=1`. Kills: no `ORDER BY`, `id DESC` only, `date DESC` without tie-break,
   `offset` applied only inside the `limit` branch.
4. Backend: invalid `limit` rejected with 422 - parametrized over `0`, `-1`, empty, `abc`.
5. Backend: `date_from`/`date_to` still filter (no existing test covers them; one combined case on
   the small fixture with an exact id list).
6. Frontend (vitest, node env, Node 24 global fetch): stub `fetch` with `vi.stubGlobal`, call
   `fetchTransactions(null)` and assert `url.searchParams.has("limit") === false` (not "!= 1000", so
   any re-added client cap fails) and `has("account_id") === false`; call `fetchTransactions(7)` and
   assert `account_id === "7"` and still no `limit`. `vi.unstubAllGlobals()` in afterEach. Guards the
   client side, which test 1 cannot catch.

Run: `cd backend && pytest` and `cd frontend && npx vitest run`.

## Docs to update

- `docs/lld_claude.md:341` - endpoint described as "paginated"; update to "optional `limit`/`offset`,
  returns all rows by default".
- `docs/lld_claude.md:417` - the 1000-cap note; replace with the new behavior and this fix's date.
- `docs/lld_claude.md:430` (Known limitations) - "fine until transaction count exceeds ~1000";
  rewrite to the new reality (all rows loaded; revisit at ~10k for render performance).
- `docs/lld_claude.md:414` - already stale independent of this fix: says the account filter re-fetches
  `GET /transactions?account_id=`; filtering is client-side and the frontend always calls
  `fetchTransactions(null)`. Correct it while there.
- `docs/lld_transactions_date_sort_claude.md` - remove the cap-fix and backend tie-break scope it
  duplicates; reference this doc as done.
- Memory: phase1/phase3 status notes.

(No mention in `.claude/skills`; no root README; `frontend/README.md` is the Vite template.)

## Live verification

Independent oracle first: `SELECT COUNT(*), MIN(date) FROM transactions` via raw SQLite.
Then against the running dev server: `GET /transactions` count must equal it. Then in the browser:
Transactions tab row count equals it (check via DOM row count), December 2025 appears in the month
dropdown, and an unfiltered CSV export has that many data rows.

## Verification results (2026-10-14)

- Tests written first and failing for the intended reasons (100-row default, `le=1000` 422, missing
  tie-break, `limit=0`/`-1` accepted, client `limit=1000`). After the fix: backend 190 passed,
  frontend 5 passed, `tsc -b` clean.
- Post-implementation review: Opus (26 mutants, 23 killed; closed 2 of 3 gaps) and Codex (5 gaps, all
  closed - including a schema test asserting `limit` has no default and no maximum, which kills the
  "larger fixed cap" mutant the spec had originally accepted).
- Live, independent oracle: raw SQL 1044 rows, Jan 2026 = 116, Dec 2025 = 6, min date 2025-12-30.
  Running dev server: `GET /transactions` 1044 rows, unique ids, same counts, `date DESC, id DESC`
  order; `limit=1001` 200, `limit=0` 422. Browser: Transactions tab renders 1044 rows (2026-10-12 ..
  2025-12-30), Jan 116 / Dec 6, December 2025 present in the month dropdown.
- CSV export not live-checked (the browser extension errored mid-check, no file was downloaded). Skipped
  on the documented basis: `handleExportCsv` / `transactionsToCsv` are unchanged and unit-tested, and
  they serialize the same `visibleTransactions` array whose 1044-row rendering was verified live.
- Dev-server note: the running backend never hot-reloaded the change (dev_server_gotchas #5/#7). Killing
  its worker made the reloader spawn an orphaned replacement before dying (gotcha #2); that orphan was
  killed and a fresh server started.
