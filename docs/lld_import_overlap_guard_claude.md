# LLD: Import overlap guard - hold likely cross-format duplicates

Status: DRAFT 2026-10-14. Direction (hold, 3-day window, account+amount only) approved by user 2026-10-14. Opus review 2026-10-14: findings verified and applied, one sub-claim rejected (see Review log). Codex review 2026-10-14: findings verified and applied; pairing algorithm (High) resolved by user choosing cluster search, 2026-10-14. Ready for phase planning. Phase 1 (pairing function, `backend/app/imports/overlap.py`) built 2026-10-14.

## Problem

Hash dedupe (`compute_row_hashes` in `backend/app/imports/base.py`) keys on
`account | date | amount | description | occurrence`. That catches re-importing the same file, but
not the same transaction arriving in a *different export format*. Bank of America provides two
formats for the same account:

| | Aggregator export (`ExportData_BOA.csv`) | Native export (`ExportData_BOA_*_<acct>.csv`) |
|---|---|---|
| Description | cleaned: `The Home Depot` | raw: `THE HOME DEPOT #2401 PORTLAND ME` |
| Date | sometimes ~2 days earlier | statement date |
| raw_category | present | absent |

So when a native file's date range overlaps data already imported from the aggregator, every
overlapping transaction is inserted a second time. The only guard today is a manual "overlap check"
step in the import runbook, and it has been skipped twice:

- **2026-08-05**: `ExportData_BOA_1962_July2026.csv` duplicated 24 Interest Checking rows
  (Jul 1-23). July income was overstated by $7,309.90 for ~10 weeks before anyone noticed.
  The same day, a 9837 file duplicated 15 Cash Rewards rows (caught and fixed that day).
- **2026-10-14**: 15 Cash Rewards + 2 Savings duplicates, 4 of them dated 2 days apart from the
  original.

All 41 were removed 2026-10-14 (see `phase1_status` memory). This doc makes the import itself
catch the next one.

## Design

### Rule

A newly parsed row is a **suspected duplicate** when, after hash dedupe, there is an
existing transaction (already in the DB before this import started) with:

1. the same `account_id`, and
2. the same `amount_cents`, and
3. `date` within **3 days** either way.

No description comparison - descriptions are exactly what differs across formats.

Amounts are compared signed: a -$20 charge never pairs with a +$20 refund.

**One-to-one pairing, independent of file order.** Each existing row can explain at most one new
row, and each new row is held for at most one existing row. If a file has two `-$0.42 GRAB` rows and
the DB has one nearby, only one is held.

APPROVED by user 2026-10-14 (option A; resolves the Codex High finding). Pairing is solved per *cluster*: the new and
existing rows of one account and amount that are linked by candidate pairs. Within a cluster, pick
the assignment that:

1. holds the **most** rows (safety: never let a duplicate in because a neighbour took its partner);
2. then has the **smallest total date gap**;
3. then is earliest by (new row date, new row hash) - a content key, never file position.

Clarified in Phase 1 (2026-10-14): criterion 3 alone does not choose between two assignments that
hold the same new rows with the same total gap but different partners. The full key is the sorted
tuple of `(new date, new hash, existing date, existing id)` per pair, compared lexicographically;
existing id is a DB identity, not file position, so order independence holds. In the oversized
fallback each held row is shown against its closest candidate by `(gap, existing date, existing id)`,
so two held rows may show the same existing row.

Clusters are tiny: across all 1201 pre-dedupe rows, same-account same-amount chains within 3 days
had sizes 1 (1054), 2 (68), 3 (2) and 5 (1). Exhaustive search over a
cluster is therefore cheap for real data. At the threshold it is not by itself: a dense 8x8 cluster
took 3.9-5.1 s unpruned (Phase 1 review). The search skips branches that can no longer hold as many
rows as the best found so far (rank criterion 1 is compared first, so they can never win); that
brings the worst dense shape at the threshold to about 0.3 s, with identical results on 3000 random
clusters against the unpruned version. A
cluster with more than 8 new or 8 existing rows (never seen) skips the search and holds every new
row that has any candidate, leaving the call to the user.

Rejected alternatives: (a) closest-pair-first greedy (the Opus-review version) - Codex example
below shows it can hold fewer rows than possible; (b) earliest-deadline two-pointer matching - holds
the maximum number but ignores date gaps, so with one existing row it can hold the farther new row
and insert the real duplicate.

Why file order must not matter: native card exports are newest-first
(`ExportData_BOA_Aug2026_9837.csv`) while native bank exports are oldest-first
(`ExportData_BOA_1962_July2026.csv`).

Existing rows that a new row *hash-matched* (an exact re-import) are taken by that match before
pairing and are not available to other rows.

Rows within the same file are never compared to each other: "existing" means rows in the DB
before this import call started. Genuine same-amount repeats inside
one statement (two transfers, two transit fares) are unaffected.

**Why 3 days:** the observed aggregator/native shift is 2 days (Olive Garden, Barnes & Noble,
Kilwins on 2026-10-14). 3 gives one day of margin, and the replay below found no difference
between 2, 3 and 4 days. Wider windows raise false positives on
recurring same-amount charges (weekly $1,224.65 Prudential deposits are 7 days apart - outside 3,
so they are safe).

### What happens to suspects: held, not inserted

Suspected rows are **not inserted**. Everything else in the file imports as today. The response
lists each held row next to the existing row it matched, and the UI lets the user import any of
them anyway.

Why hold rather than insert-and-warn: a warning after the fact leaves wrong totals in the DB until
someone acts, which is exactly how the 2026-08-05 duplicates sat unnoticed for 10 weeks. Holding
makes the safe outcome the default; a false positive costs one click.

Why not a full preview/confirm step for every import: it adds a second round-trip to every import
when the overwhelming majority have zero suspects.

### Accepting held rows

Stateless: the client re-sends the same file with the hashes it wants accepted.

```
POST /imports            multipart: file, accept_hashes (optional, repeated form field)
```

FastAPI declares this as `accept_hashes: list[str] = Form(default=[])`; the frontend calls
`formData.append("accept_hashes", hash)` once per hash. A repeated field avoids parsing JSON out of
a form value (and `json.loads`'s permissive edge cases).

On the second call, rows already inserted by the first call hash-dedupe to no-ops. Pairing then
runs exactly as on the first call; any held row whose `source_row_hash` is in `accept_hashes` is
inserted instead of held. Running pairing unchanged keeps the remaining held rows' partners stable
between calls. Unknown
hashes are ignored (e.g. a stale browser tab). Nothing is stored server-side between the calls.

### Backend changes

`backend/app/imports/pipeline.py`:

- `import_file(session, filename, file_bytes, accept_hashes: frozenset[str] = frozenset())`
- Per account (min/max computed over that account's rows only; the aggregator file spans four
  accounts): load existing rows with `date` in `[account_min - 3d, account_max + 3d]` once, before
  inserting anything. Look up which of the file's hashes already exist (those rows are re-imports:
  skipped, and they claim their existing row). For each remaining row, try to pair it (rule above);
  if paired and its hash is not in `accept_hashes`, hold it; otherwise insert as today.
- Pairing logic as a small pure function, e.g.
  `find_suspected_duplicates(new_rows, existing_rows) -> dict[row_index, existing_row]`, so it can be
  unit-tested without a DB.
- Failure behaviour is unchanged from today and stays a documented partial-success contract: rows
  are committed before `apply_merchant_rules`/`apply_category_rules`, each of which commits
  (`pipeline.py:92`, `apply.py:48`, `apply.py:93`). If a rule step fails after insert, a retry
  converges: inserted rows hash-skip, and both rule functions re-scan every uncategorized row.
  Making import + rules one transaction is out of scope.
- `ImportSummary` gains `rows_held_as_suspected_duplicate: int` and
  `suspected_duplicates: list[SuspectedDuplicate]`, where each entry carries
  `row_hash, account_name, date, description, amount_cents` and the matched
  `existing_id, existing_date, existing_description`.
- `rows_skipped_as_duplicate` keeps its meaning (exact hash matches only), but is counted
  explicitly (pre-lookup hash matches, plus any insert whose rowcount is 0, e.g. a double-submit)
  instead of today's `len(rows) - rows_inserted` (`pipeline.py:103`), which would swallow held rows.
  `rows_seen = inserted + skipped + held`.

`backend/app/routers/imports.py`: accept the optional `accept_hashes` form field; `ImportSummaryOut`
schema updated to match.

Merchant/category rule application after insert is unchanged.

### Frontend changes

`frontend/src/App.tsx` upload flow:

- Status line becomes `file.csv: 40 new, 0 already imported, 15 held as possible duplicates`.
- When `rows_held_as_suspected_duplicate > 0`, show a panel under the upload control: one row per
  held transaction, new vs existing side by side (date, description, amount), each with an
  unchecked "import anyway" checkbox, plus **Import selected** and **Dismiss** buttons.
- Today `handleFileUpload` keeps the `File` only in a local variable. Add a `pendingImport` state
  `{ file, summary }`, set when a response has held rows. The `File` stays readable after the
  input's `value` is reset in `finally` (it would only fail if the file changed on disk).
- **Import selected** re-sends `pendingImport.file` with the checked hashes, then replaces the panel
  with the new response's held list (closing it if none remain). **Dismiss** clears
  `pendingImport`; held rows stay out.
- Starting any upload clears `pendingImport` and the checked set immediately, and the panel's
  buttons are disabled while a request is in flight, so a stale panel or a double-submit can't
  happen. The panel state transitions live in a small pure reducer so they can be unit-tested.

`frontend/src/api.ts`: `uploadCsv(file, acceptHashes?)` and the extended `ImportSummary` type.

### Out of scope

- The second proposal from 2026-10-14 (offer a merchant rule when a category is edited by hand) -
  separate doc.
- Scanning existing data for old duplicates. The DB was cleaned 2026-10-14 and verified to have zero
  cross-format pairs within 2 days on BOA accounts.
- Persisting import history (an `imports` table). Would allow "which file did this come from", but
  nothing here needs it.

## Known false negative

Aggregator rows can be *pending* (e.g. Olive Garden -$59.07 on 07/25). If the posted amount
differs (a tip added at posting), the native row's amount won't match and the duplicate is
inserted. Not seen in the replay; accepted as a limitation of exact-amount matching.

## Known false positives

A genuinely new transaction with the same account and amount as one already imported from a
*previous* file, within 3 days. Realistic cases in this data: the $250 scheduled transfers to
savings and to 1640 that land on consecutive days, and small repeated transit fares, when a monthly
file boundary falls between them. These get held and need one click to accept.

### Measured against real import history (2026-10-14)

Replay method (read-only, `backend/scripts/replay_overlap_guard.py`): re-parse every file in `data/` with the
app's own parsers and `compute_row_hashes`; each row in the pre-dedupe DB backup is attributed to
the earliest file (by mtime) that produces its hash (all 1201 rows were traceable). Files are then
replayed in mtime order; a file's rows that actually entered the DB are paired by the rule above
against rows from earlier files. A held row still in today's cleaned DB is a false positive; a held
row among the 41 deleted is a true positive. Re-run 2026-10-14 against the real implementation
(`find_suspected_duplicates`): the table below is its output. The 2, 3, 4 and 7-day rows are
identical to the earlier closest-first greedy prototype. At 14 days greedy found 8 false positives
and the cluster search finds 9: two -$250 1962 transfers (Apr 23, Apr 24) each pair with an
existing May 7 / May 8 transfer 14 days away, where greedy paired Apr 24 to May 7 and stranded
Apr 23. That is rule 1 (most held) working as designed. An earlier draft of this section said
file-order and closest-first greedy gave identical results; the committed greedy script gives 8 at
14 days, not 9, so that claim was not accurate for the 14-day row.

| Window | Duplicates held (of 41) | Missed | False positives |
|---|---|---|---|
| 2 days | 41 | 0 | 0 |
| **3 days** | **41** | **0** | **0** |
| 4 days | 41 | 0 | 0 |
| 7 days | 41 | 0 | 1 (weekly Prudential deposit) |
| 14 days | 41 | 0 | 9 (biweekly transfers) |

The 7/14-day rows show the harness does detect false positives when they exist, so the zero at 3
days is a real result, not a blind spot. Caveat: this history has never had a monthly file boundary
fall between two same-amount transactions in the 3-day window; the consecutive-day $250 transfers
remain a plausible future false positive.

## Tests (backend, pytest)

Fixture rule for all of them: ids, dates and file order are deliberately *not* aligned (the
date-sort review found a rising-id fixture let a wrong sort pass), and every pairing test has at
least two candidates so order effects are visible.

Pure pairing function:

1. Same account + amount, different description, same date -> held.
2. Window, both directions: new at existing +3 and -3 days -> held; +4 and -4 -> inserted.
3. Different account, same amount/date -> inserted.
4. Amount differs by one cent -> inserted. Opposite sign (-$20 existing, +$20 new) -> inserted.
5. One existing row, two new rows; the **farther** new row is listed **first** in the file -> the
   closer one is held, the farther one inserted. Run with the file order reversed -> same result.
6. One new row, two existing candidates where the closer one has the **higher** id -> paired to the
   closer one.
6a. Most-held beats closest (Codex example): existing Jan 1 and Jan 4, new Jan 3 and Jan 7 -> both
    new rows held (Jan 3 -> Jan 1, Jan 7 -> Jan 4).
6b. Exact tie: existing Jan 2, new Jan 1 and Jan 3 -> the Jan 1 row is held, in both file orders.
6c. Oversized cluster (9 new rows, 9 existing, same amount, all within window) -> every new row
    held.

Through `import_file` against a test DB:

7. Re-importing an identical file -> all rows skipped by hash, zero held.
8. Hash-matched rows are claimed: existing E on day D; file has A (exact re-import of E) and B (new,
   same amount, D+1) -> A skipped, B inserted, nothing held.
9. Same-file rows are never compared: DB holds an unrelated row; file has two same-amount rows a
   day apart -> both inserted.
10. Window query padding, per account: a multi-account (aggregator-style) file whose accounts have
    widely separated date ranges; for one account an existing row 2 days *before* its earliest file
    date, for another an existing row 2 days *after* its latest -> both matching new rows held, and
    an existing row of a third account that falls inside the *file-wide* range but outside its own
    account's padded range does not cause a hold.
11. Cross-format incident fixture (modelled on 2026-10-14: aggregator-style rows first, then
    native-style rows including 2-day-shifted ones) -> every overlapping row held with the expected
    `existing_id`, the non-overlapping tail inserted; each suspect's full serialized object
    (row_hash, account_name, date, description, amount_cents, existing_id, existing_date,
    existing_description) asserted; `rows_inserted`, `rows_skipped_as_duplicate`
    and `rows_held_as_suspected_duplicate` each asserted, and they sum to `rows_seen`.
12. Accepting: fixture with three held rows; second call accepting two hashes -> exactly those two
    inserted, the third still held with an unchanged `existing_id`.
13. Unknown hash in `accept_hashes` -> ignored, no error.
14. An accepted row gets its category from rules run after insert (fixture seeds a MerchantRule and
    its category explicitly, since the pipeline test session seeds none).

Through the API (`make_client` in `test_api.py`):

15. Multipart upload with repeated `accept_hashes` fields reaches `import_file` as a list; response
    includes the new summary fields.

Frontend (vitest):

16. `uploadCsv(file, ["h1", "h2"])` builds FormData with `file` and two repeated `accept_hashes`
    entries (fetch stubbed); with no hashes, no `accept_hashes` entry.
17. The panel reducer: response with held rows opens the panel; toggling selects/deselects;
    a retry response replaces the held list (and closes at zero); dismiss clears; starting a new
    upload clears panel and selection; a failed retry keeps the panel and selection.

The rendered panel itself is verified live.

## Live verification plan

On a **copy** of `finance.db` (backend started with `DATABASE_PATH` pointing at the copy, so the real
DB is never touched):

1. Copy the current (cleaned) DB and re-import the real 2026-10-14 native 9837 and Savings files
   through the UI. The rows we kept hash-match and are skipped; the 17 rows we deleted by hand are
   no longer in the DB, so they are exactly what the guard must hold. Expect: 0 new, N skipped,
   17 held - each paired with the aggregator row we kept for it (ids 401-417, 562, 563).
2. Accept one held row via the panel; confirm by raw SQL it is the only new row.
3. Re-import the same file; expect 0 new and 16 held (the accepted row now hash-matches).
4. Repeat step 1 for the 2026-08-05 file `data/ExportData_BOA_1962_July2026.csv`: expect its 24
   Jul 1-23 rows held.

The 2026-10-14 files are in `data/` (`ExportData_BOA_Aug2026_9837.csv`,
`ExportData_BOA_3938_Oct142026.csv`, and others).

## Review log

Opus, 2026-10-14 (read-only, against the code):

- High - file-order greedy pairing contradicted the closer-wins test and depended on export format.
  Verified (card files newest-first, bank files oldest-first). Applied: closest-first global assignment (since superseded, see Codex High below).
- Medium - untested: window query padding, hash-match claiming, router form contract; Test 11
  half-vacuous; stale "CSVs not in data/" line. All applied (tests 8, 10, 14, 15; repeated form
  field instead of JSON).
- Low - pairing on accept, explicit skipped count, signed amounts, pending-row false negative,
  File not in state today. All applied.
- Rejected sub-claim: "the August originals probably weren't aggregator rows". The 17 rows deleted
  on 2026-10-14 pair with ids 401-417/562/563, all aggregator rows (they carry the aggregator's
  raw_category); verified by SQL.

Codex, 2026-10-14 (read-only, against the code):

- High - closest-first greedy can hold fewer rows than possible (example in test 6a). Verified by
  hand. Fixed: cluster search (most held, then smallest gap), approved by user.
- Medium - file-index tie-break contradicted "independent of file order". Applied: tie-break on
  (date, row hash), tests 5 and 6b run both file orders.
- Medium - upper padding and per-account bounds untested. Applied: test 10 rewritten.
- Medium - partial-success on rule failure undefined. Applied: documented as today's contract with
  retry convergence; not changed.
- Medium - suspect fields and panel behaviour untested. Applied: test 11 asserts full objects;
  frontend tests 16-17 with a pure reducer.
- Medium - mutation gaps: "only first accepted hash" (test 12 now accepts two of three); "same-file
  rule only when DB empty" (test 9 now has a non-empty DB); "frontend never sends repeated fields"
  (test 16). The remaining per-test notes describe single tests in isolation, which the suite covers
  together.
- Low - stale panel / double-submit. Applied.
- Confirmed sound: occurrence hashing + unique constraint, transfer detection does not interact.

Phase 1 implementation review, 2026-10-14 (Opus subagent + Codex, both ran the tests: 18 / 208 passed;
Codex needed `-s` under its read-only sandbox). No correctness defect in `overlap.py`. Applied:

- Important (both) - surviving mutants: total gap untested across several pairs (squared-gap rank),
  test 5's farther row was also the later date ("skip only if forced"), no existing-id tie or
  same-date new-row tie test, oversized fallback partner choice unpinned, same-list rule untested
  with two rows, month-boundary partition. Added tests R7-R13; each named mutant verified killed.
- Important (both) - dense 8x8 search 3.9-5.1 s. Added count-bound pruning (above); test R14 pins
  it under 1 s. Lowering `MAX_CLUSTER_SIDE` was the alternative, rejected because it changes which
  rows are paired.
