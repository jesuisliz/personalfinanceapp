# Import Overlap Guard - Phase 2 Implementation Plan (pipeline + API wiring)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `POST /imports` hold suspected cross-format duplicates instead of inserting them, report each held row next to its existing partner, and insert a held row when the client re-sends the file with that row's hash in `accept_hashes`.

**Architecture:** `import_file` loads, per account, the existing rows within 3 days of that account's dates in the file (one query per account, before any insert). Rows whose hash is already among them are exact re-imports: skipped, and they claim their row. The rest go through Phase 1's `find_suspected_duplicates`; a paired row is held unless its hash was accepted. The router passes a repeated `accept_hashes` form field through. The frontend gets only a status-line change in this phase (the accept panel is Phase 3).

**Tech Stack:** Python 3.13, FastAPI 0.141, SQLAlchemy, SQLite, pytest; TypeScript + vitest for the status line.

**Spec:** `docs/lld_import_overlap_guard_claude.md` ("Backend changes", "Accepting held rows", "Tests" 7-15, "Live verification plan"). Phase 1 plan: `docs/plan_import_overlap_guard_phase1_claude.md`.

## Global Constraints

- Window: `WINDOW_DAYS = 3` from `app.imports.overlap`, inclusive. Never hard-code a second `3`.
- Existing rows = rows in the DB **before this `import_file` call started**. Rows inserted by this call are never pairing candidates.
- Existing-row query is **per account**, bounds `[that account's min date - 3d, that account's max date + 3d]`, inclusive both ends.
- Rows whose `source_row_hash` already exists are skipped, counted as skipped, and remove their existing row from the pairing pool.
- A paired row is held (not inserted) unless its hash is in `accept_hashes`. Unknown or non-held hashes in `accept_hashes` are ignored.
- `rows_skipped_as_duplicate` = pre-lookup hash matches + inserts whose `rowcount` is 0. Never `len(rows) - rows_inserted`.
- Invariant: `rows_seen == rows_inserted + rows_skipped_as_duplicate + rows_held_as_suspected_duplicate`.
- Each suspect carries exactly: `row_hash, account_name, date, description, amount_cents, existing_id, existing_date, existing_description`.
- `accept_hashes` is a repeated multipart form field, `list[str] = Form(default=[])`. No JSON in form values.
- Merchant/category rule application after insert is unchanged, and so is the partial-success contract.
- Code style: small functions, docstrings, no defensive try/except, no emojis. Match surrounding style.

**Decisions this plan adds (record in the LLD, Task 5):**

1. **Suspect list order:** sorted by `(account_name, date, description, amount_cents, row_hash)`. The spec doesn't give an order; this one is deterministic, independent of file order, and readable in the Phase 3 panel.
2. **Hash lookup without an `IN` list:** a row with the same hash has the same account and date (both are in the hash key), so it is always inside the padded window. The window query already returns it; no separate `WHERE source_row_hash IN (...)` query is needed.
3. **Status line moves into Phase 2 (Task 4).** Without it, a row held by Phase 2 code would not show up anywhere in the UI until Phase 3 ships. A real transaction wrongly held would go missing with no notice. This is one string function plus its test; the panel stays in Phase 3.
4. **Spec correction (found while planning, verified read-only against `finance.db` and `finance.db.bak-2026-10-14-pre-dedupe`):** the LLD's live-check partner list "ids 401-417, 562, 563" has 19 ids for 17 held rows. The correct Cash Rewards partners are 401-408, 410-415 and 417 (15 rows); 409 (+$4,284.66 recurring payment) and 416 (Offside Jersey) had no deleted duplicate. The LLD's "17 held" also spans two files (15 from the 9837 file, 2 from the 3938 file), so step 3's "16 held" must be read per file: 14 for the 9837 file.

## Review Focus

Input classes the spec implies that tests 7-15 don't pin, most likely to bite first:

1. **Re-importing a file that still has held rows**: those rows must stay held, be counted as held, not skipped, and the counts must sum to `rows_seen`. The old `len(rows) - rows_inserted` formula would count them as skipped. -> test 11's second call, Task 1.
2. **Newest-first vs oldest-first file**: reversing the native file must give an identical summary (held set, partners, list order). -> test R2, Task 1.
3. **Existing row exactly 3 days outside the file's date range** (query `<` vs `<=`, or padding on one side only) -> folded into test 10, Task 1.
4. **Accepting a hash that is not held** (already inserted on an earlier accept, or an exact re-import): no double insert, no error, counts unchanged. -> test R1, Task 2.
5. **Response shape with nothing held**: `rows_held_as_suspected_duplicate: 0` and `suspected_duplicates: []` are always present, so the frontend can read them unconditionally. -> test 15, Task 3.

The double-submit race (insert `rowcount` 0) was planned as untestable without concurrency (corrected in close-out review: it is tested by monkeypatching `load_nearby_transactions` to return no rows); it is a one-line `1 - rowcount` on the existing `on_conflict_do_nothing` path, and Task 1's step 3 calls it out for review.

---

## File Structure

- Modify `backend/app/imports/pipeline.py` - `SuspectedDuplicate`, extended `ImportSummary`, per-account window load, hold/accept decision.
- Create `backend/tests/test_import_overlap.py` - tests 7-14, R1, R2 (keeps `test_pipeline.py` focused on parsing/routing).
- Modify `backend/app/schemas.py` - `SuspectedDuplicateOut`, extended `ImportSummaryOut`.
- Modify `backend/app/routers/imports.py` - `accept_hashes` form field.
- Modify `backend/tests/test_api.py` - test 15.
- Modify `frontend/src/api.ts` - `ImportSummary` type + `SuspectedDuplicate` type (no `uploadCsv` change; Phase 3 adds `acceptHashes`).
- Modify `frontend/src/format.ts`, `frontend/src/format.test.ts`, `frontend/src/App.tsx` - `formatImportStatus`.
- Modify `docs/lld_import_overlap_guard_claude.md` - status, decisions 1-4, live results.

Backend commands run from `backend/` with `venv/Scripts/python.exe -m pytest ...`. Frontend commands run from `frontend/` with `npx vitest run ...`. Work on `main` per the standing git routine; commit per task, staging only that task's files.

---

### Task 1: Hold suspected duplicates in `import_file`

**Files:**
- Modify: `backend/app/imports/pipeline.py`
- Create: `backend/tests/test_import_overlap.py`

**Interfaces:**
- Consumes (Phase 1, `app.imports.overlap`): `WINDOW_DAYS`, `NewRow(account_id, date, amount_cents, row_hash)`, `ExistingRow(id, account_id, date, amount_cents)`, `find_suspected_duplicates(new_rows, existing_rows) -> dict[int, int]` (new index -> existing id).
- Produces (Tasks 2-3 rely on these):
  - `@dataclass class SuspectedDuplicate: row_hash: str; account_name: str; date: date; description: str; amount_cents: int; existing_id: int; existing_date: date; existing_description: str`
  - `@dataclass class ImportSummary: filename: str; rows_seen: int; rows_inserted: int; rows_skipped_as_duplicate: int; rows_held_as_suspected_duplicate: int; suspected_duplicates: list[SuspectedDuplicate]`
  - `import_file(session, filename, file_bytes, accept_hashes: frozenset[str] = frozenset()) -> ImportSummary` (Task 1 adds the parameter and ignores it; Task 2 implements it).

- [ ] **Step 1: Write the test file with helpers and tests 7-11 + R2**

`backend/tests/test_import_overlap.py`:

```python
"""Import overlap guard through import_file (LLD tests 7-14, plus R1/R2 from the Phase 2 plan).

Existing rows are always created by a real earlier import, the way they arise in practice.
"""
import hashlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.imports.pipeline import SuspectedDuplicate, import_file
from app.models import Account, Category, MerchantRule, Transaction

CHASE_FILE = "Chase3403_Activity_20260726.csv"
AGGREGATOR_FILE = "ExportData_BOA.csv"
NATIVE_9837_FILE = "ExportData_BOA_Aug2026_9837.csv"

AGGREGATOR_HEADER = (
    "Status,Date,Original Description,Split Type,Category,Currency,Amount,"
    "User Description,Memo,Classification,Account Name,Simple Description"
)
AGGREGATOR_ACCOUNT_NAMES = {
    "cash": "Bank of America - Credit Card - Customized Cash Rewards World Mastercard",
    "checking": "Bank of America - Bank - Bofa Interest Checking",
    "savings": "Bank of America - Bank - Credit",
}


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def chase_csv(*rows: tuple[str, str, str]) -> bytes:
    """Chase export; each row is (MM/DD/YYYY, description, amount)."""
    lines = ["Transaction Date,Post Date,Description,Category,Type,Amount,Memo"]
    lines += [f"{day},{day},{description},Shopping,Sale,{amount}," for day, description, amount in rows]
    return ("\n".join(lines) + "\n").encode()


def aggregator_csv(*rows: tuple[str, str, str, str]) -> bytes:
    """BOA aggregator export; each row is (account key, MM/DD/YYYY, description, amount)."""
    lines = [AGGREGATOR_HEADER]
    lines += [
        f"posted,{day}, {description},,Shopping,USD,{amount}, , ,Personal,"
        f"{AGGREGATOR_ACCOUNT_NAMES[key]}, {description}"
        for key, day, description, amount in rows
    ]
    return ("\n".join(lines) + "\n").encode()


def native_card_csv(*rows: tuple[str, str, str]) -> bytes:
    """BOA native card export; each row is (MM/DD/YYYY, payee, amount)."""
    lines = ["Posted Date,Reference Number,Payee,Address,Amount"]
    lines += [f'{day},0000,"{payee}","",{amount}' for day, payee, amount in rows]
    return ("\n".join(lines) + "\n").encode()


def expected_hash(account_id: int, iso_date: str, amount_cents: int, description: str) -> str:
    """Row hash built by hand from the documented key format, not via compute_row_hashes."""
    key = f"{account_id}|{iso_date}|{amount_cents}|{description.lower()}|0"
    return hashlib.sha256(key.encode()).hexdigest()


def assert_counts(summary, inserted: int, skipped: int, held: int) -> None:
    assert summary.rows_inserted == inserted
    assert summary.rows_skipped_as_duplicate == skipped
    assert summary.rows_held_as_suspected_duplicate == held
    assert summary.rows_seen == inserted + skipped + held
    assert len(summary.suspected_duplicates) == held


def txn(session, description: str, amount_cents: int) -> Transaction:
    return session.query(Transaction).filter_by(description=description, amount_cents=amount_cents).one()


def account_id(session, name: str) -> int:
    return session.query(Account).filter_by(name=name).one().id


# Test 7
def test_reimporting_identical_file_skips_every_row_and_holds_none(session):
    csv = chase_csv(
        ("07/10/2026", "HANNAFORD 1", "-34.50"),
        ("07/11/2026", "HANNAFORD 2", "-34.50"),
        ("07/09/2026", "SHELL", "-40.00"),
    )
    import_file(session, CHASE_FILE, csv)

    summary = import_file(session, CHASE_FILE, csv)

    assert_counts(summary, inserted=0, skipped=3, held=0)


# Test 8
def test_hash_matched_row_claims_its_existing_row(session):
    import_file(session, CHASE_FILE, chase_csv(("07/10/2026", "HANNAFORD", "-34.50")))

    summary = import_file(
        session,
        CHASE_FILE,
        chase_csv(("07/11/2026", "HANNAFORD STORE", "-34.50"), ("07/10/2026", "HANNAFORD", "-34.50")),
    )

    assert_counts(summary, inserted=1, skipped=1, held=0)
    assert session.query(Transaction).filter_by(description="HANNAFORD STORE").count() == 1


# Test 9
def test_rows_in_the_same_file_are_never_paired_with_each_other(session):
    import_file(session, CHASE_FILE, chase_csv(("07/20/2026", "NETFLIX", "-15.49")))  # inside the window

    summary = import_file(
        session,
        CHASE_FILE,
        chase_csv(("07/20/2026", "METRO FARE", "-2.75"), ("07/21/2026", "METRO FARE", "-2.75")),
    )

    assert_counts(summary, inserted=2, skipped=0, held=0)


# Test 10 (+ Review Focus 3: exact 3-day edges)
def test_window_query_is_padded_per_account_inclusive_at_three_days(session):
    import_file(
        session,
        AGGREGATOR_FILE,
        aggregator_csv(
            ("cash", "03/09/2026", "CAFE A", "-12.00"),  # 3 days before cash's earliest new date
            ("checking", "09/21/2026", "UTILITY X", "-80.00"),  # 3 days after checking's latest
            ("savings", "06/15/2026", "TRANSFER S", "250.00"),  # inside the file-wide range only
            ("cash", "03/08/2026", "CAFE B", "-7.00"),  # 4 days before: never pairs
        ),
    )

    summary = import_file(
        session,
        AGGREGATOR_FILE,
        aggregator_csv(
            ("checking", "09/18/2026", "UTILITY X PAYMENT", "-80.00"),
            ("checking", "09/01/2026", "GROCER", "-30.00"),
            ("cash", "03/12/2026", "CAFE A LLC", "-12.00"),
            ("cash", "03/12/2026", "CAFE B LLC", "-7.00"),
            ("cash", "03/30/2026", "BOOKS", "-20.00"),
            ("savings", "01/05/2026", "TRANSFER S2", "250.00"),
            ("savings", "01/02/2026", "INTEREST", "0.35"),
        ),
    )

    assert_counts(summary, inserted=5, skipped=0, held=2)
    partners = {s.description: s.existing_id for s in summary.suspected_duplicates}
    assert partners == {
        "CAFE A LLC": txn(session, "CAFE A", -1200).id,
        "UTILITY X PAYMENT": txn(session, "UTILITY X", -8000).id,
    }


AGGREGATOR_ROWS = (
    ("cash", "07/25/2026", "Olive Garden", "-59.07"),
    ("cash", "07/23/2026", "The Home Depot", "-50.58"),
    ("checking", "07/22/2026", "Payment to Discover Card", "-120.00"),
    ("cash", "07/25/2026", "Barnes & Noble", "-26.92"),
    ("cash", "07/23/2026", "The Home Depot", "29.52"),
    ("cash", "07/20/2026", "IKEA", "-54.65"),
)

NATIVE_ROWS = (  # newest-first, as BOA native card exports are
    ("08/02/2026", "SHELL OIL 57444", "-40.00"),
    ("07/22/2026", "CVS PHARMACY 1234", "-120.00"),  # same amount/date as a checking row
    ("07/27/2026", "OLIVE GARDEN ZK 002143", "-59.07"),  # 2-day shift
    ("07/27/2026", "BARNES & NOBLE #2988", "-26.92"),  # 2-day shift
    ("07/23/2026", "THE HOME DEPOT #2401", "29.52"),
    ("07/23/2026", "THE HOME DEPOT #2401", "-50.58"),
    ("07/20/2026", "IKEA STOUGHTON", "-54.65"),
)


def expected_incident_suspects(session) -> list[SuspectedDuplicate]:
    cash_id = account_id(session, "BOA Customized Cash Rewards")

    def suspect(iso_date, description, cents, existing_description):
        existing = txn(session, existing_description, cents)
        return SuspectedDuplicate(
            row_hash=expected_hash(cash_id, iso_date, cents, description),
            account_name="BOA Customized Cash Rewards",
            date=date.fromisoformat(iso_date),
            description=description,
            amount_cents=cents,
            existing_id=existing.id,
            existing_date=existing.date,
            existing_description=existing_description,
        )

    return [
        suspect("2026-07-20", "IKEA STOUGHTON", -5465, "IKEA"),
        suspect("2026-07-23", "THE HOME DEPOT #2401", -5058, "The Home Depot"),
        suspect("2026-07-23", "THE HOME DEPOT #2401", 2952, "The Home Depot"),
        suspect("2026-07-27", "BARNES & NOBLE #2988", -2692, "Barnes & Noble"),
        suspect("2026-07-27", "OLIVE GARDEN ZK 002143", -5907, "Olive Garden"),
    ]


# Test 11 (+ Review Focus 1: re-import keeps held rows held)
def test_cross_format_incident_holds_every_overlapping_row(session):
    import_file(session, AGGREGATOR_FILE, aggregator_csv(*AGGREGATOR_ROWS))

    first = import_file(session, NATIVE_9837_FILE, native_card_csv(*NATIVE_ROWS))

    assert_counts(first, inserted=2, skipped=0, held=5)
    assert first.suspected_duplicates == expected_incident_suspects(session)
    cash_id = account_id(session, "BOA Customized Cash Rewards")
    inserted = {t.description for t in session.query(Transaction).filter_by(account_id=cash_id)}
    assert {"SHELL OIL 57444", "CVS PHARMACY 1234"} <= inserted
    assert "IKEA STOUGHTON" not in inserted

    second = import_file(session, NATIVE_9837_FILE, native_card_csv(*NATIVE_ROWS))

    assert_counts(second, inserted=0, skipped=2, held=5)
    assert second.suspected_duplicates == first.suspected_duplicates


# R2 (Review Focus 2)
def test_file_order_does_not_change_the_summary(session):
    import_file(session, AGGREGATOR_FILE, aggregator_csv(*AGGREGATOR_ROWS))

    summary = import_file(session, NATIVE_9837_FILE, native_card_csv(*reversed(NATIVE_ROWS)))

    assert_counts(summary, inserted=2, skipped=0, held=5)
    assert summary.suspected_duplicates == expected_incident_suspects(session)
```

Add `from datetime import date` to the imports. (`Category`, `MerchantRule` are used by Task 2's tests; leave them imported now.)

- [ ] **Step 2: Run to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_import_overlap.py -v`
Expected: collection ERROR, `ImportError: cannot import name 'SuspectedDuplicate'`.

- [ ] **Step 3: Implement in `pipeline.py`**

Replace the `ImportSummary` dataclass and `import_file`, and add the helpers. Keep `resolve_account_definition` and `get_or_create_account` unchanged.

```python
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.categories.apply import apply_category_rules, apply_merchant_rules
from app.config import AccountDefinition, ConfigEntry
from app.imports.base import ParsedRow, compute_row_hashes
from app.imports.overlap import WINDOW_DAYS, ExistingRow, NewRow, find_suspected_duplicates
from app.imports.registry import get_parser, match
from app.models import Account, Transaction


@dataclass
class SuspectedDuplicate:
    row_hash: str
    account_name: str
    date: date
    description: str
    amount_cents: int
    existing_id: int
    existing_date: date
    existing_description: str


@dataclass
class ImportSummary:
    filename: str
    rows_seen: int
    rows_inserted: int
    rows_skipped_as_duplicate: int
    rows_held_as_suspected_duplicate: int
    suspected_duplicates: list[SuspectedDuplicate]
```

```python
def load_nearby_transactions(session: Session, account_id: int, rows: list[ParsedRow]) -> list[Transaction]:
    """Existing rows of one account dated within WINDOW_DAYS of that account's rows in the file.

    Includes every exact re-import too: a matching hash means the same account and date.
    """
    dates = [row.date for row in rows]
    start = min(dates) - timedelta(days=WINDOW_DAYS)
    end = max(dates) + timedelta(days=WINDOW_DAYS)
    return list(
        session.execute(
            select(Transaction).where(Transaction.account_id == account_id, Transaction.date.between(start, end))
        ).scalars()
    )


def find_partners(
    account_id: int, rows: list[ParsedRow], row_hashes: list[str], nearby: list[Transaction]
) -> dict[int, Transaction]:
    """Map row index -> the existing transaction it likely duplicates.

    Rows whose hash already exists are left out and take their own existing row out of the pool.
    """
    existing_hashes = {t.source_row_hash for t in nearby}
    file_hashes = set(row_hashes)
    pool = [t for t in nearby if t.source_row_hash not in file_hashes]
    candidate_indices = [i for i, row_hash in enumerate(row_hashes) if row_hash not in existing_hashes]
    new_rows = [
        NewRow(account_id, rows[i].date, rows[i].amount_cents, row_hashes[i]) for i in candidate_indices
    ]
    existing_rows = [ExistingRow(t.id, t.account_id, t.date, t.amount_cents) for t in pool]
    pool_by_id = {t.id: t for t in pool}
    pairs = find_suspected_duplicates(new_rows, existing_rows)
    return {candidate_indices[new_index]: pool_by_id[existing_id] for new_index, existing_id in pairs.items()}
```

Note on the pool filter: an existing row is "claimed" exactly when its hash appears among this file's hashes, which is the same set of rows that are skipped.

```python
def insert_row(session: Session, account_id: int, row: ParsedRow, row_hash: str) -> int:
    """Insert one parsed row; return 1 if inserted, 0 if its hash already existed."""
    stmt = (
        sqlite_insert(Transaction)
        .values(
            account_id=account_id,
            date=row.date,
            posted_date=row.posted_date,
            description=row.description,
            amount_cents=row.amount_cents,
            raw_category=row.raw_category,
            memo=row.memo,
            source_row_hash=row_hash,
        )
        .on_conflict_do_nothing(index_elements=["account_id", "source_row_hash"])
    )
    return session.execute(stmt).rowcount


def import_file(
    session: Session, filename: str, file_bytes: bytes, accept_hashes: frozenset[str] = frozenset()
) -> ImportSummary:
    """Import one CSV, holding rows that look like cross-format duplicates of existing rows.

    A held row is inserted on a later call whose accept_hashes contains its hash.
    See docs/lld_import_overlap_guard_claude.md.
    """
    config_entry = match(filename)
    parser = get_parser(config_entry.parser)
    rows = parser.parse(file_bytes)

    accounts_by_id: dict[int, Account] = {}
    rows_by_account_id: dict[int, list[ParsedRow]] = {}
    for row in rows:
        account_def = resolve_account_definition(config_entry, row.account_match_key)
        account = get_or_create_account(session, account_def)
        accounts_by_id[account.id] = account
        rows_by_account_id.setdefault(account.id, []).append(row)

    rows_inserted = 0
    rows_skipped = 0
    suspects: list[SuspectedDuplicate] = []
    for account_id, account_rows in rows_by_account_id.items():
        row_hashes = compute_row_hashes(account_id, account_rows)
        nearby = load_nearby_transactions(session, account_id, account_rows)
        existing_hashes = {t.source_row_hash for t in nearby}
        partners = find_partners(account_id, account_rows, row_hashes, nearby)
        for index, (row, row_hash) in enumerate(zip(account_rows, row_hashes)):
            if row_hash in existing_hashes:
                rows_skipped += 1
                continue
            partner = partners.get(index)
            if partner is not None and row_hash not in accept_hashes:
                suspects.append(
                    SuspectedDuplicate(
                        row_hash=row_hash,
                        account_name=accounts_by_id[account_id].name,
                        date=row.date,
                        description=row.description,
                        amount_cents=row.amount_cents,
                        existing_id=partner.id,
                        existing_date=partner.date,
                        existing_description=partner.description,
                    )
                )
                continue
            inserted = insert_row(session, account_id, row, row_hash)
            rows_inserted += inserted
            rows_skipped += 1 - inserted  # a concurrent import inserted the same hash first

    session.commit()
    # Merchant rules run first: a specific merchant match (e.g. a utility company)
    # is more accurate than a bank's own generic raw_category, so it should win
    # when both are available for the same transaction.
    apply_merchant_rules(session)
    apply_category_rules(session)

    suspects.sort(key=lambda s: (s.account_name, s.date, s.description, s.amount_cents, s.row_hash))
    return ImportSummary(
        filename=filename,
        rows_seen=len(rows),
        rows_inserted=rows_inserted,
        rows_skipped_as_duplicate=rows_skipped,
        rows_held_as_suspected_duplicate=len(suspects),
        suspected_duplicates=suspects,
    )
```

The `row_hash not in accept_hashes` check is written now so the decision lives in one place; Task 2's tests are what prove it.

Reviewer focus for this step: the `1 - inserted` line (double-submit), and that `nearby` is loaded for an account before any of that account's rows are inserted (rows of other accounts can't be in its pool, since the query filters on `account_id`).

- [ ] **Step 4: Run the new tests and the full suite**

Run: `venv/Scripts/python.exe -m pytest tests/test_import_overlap.py -v` -> 6 passed.
Run: `venv/Scripts/python.exe -m pytest -q` -> all pass (216 before + 6 = 222). `test_pipeline.py` and `test_api.py` import tests must pass unchanged.

- [ ] **Step 5: Mutation check (do not commit the mutants)**

Apply each, run `tests/test_import_overlap.py`, confirm at least one test fails, revert:
1. `rows_skipped_as_duplicate=len(rows) - rows_inserted` -> test 11 second call fails.
2. Drop the `- timedelta(...)` padding on `start` -> test 10 fails.
3. `Transaction.date > start` (exclusive) -> test 10 fails.
4. Pool not filtered by claimed hashes (`pool = nearby`) -> test 8 fails.
5. Move the `load_nearby_transactions` + `find_partners` calls inside the per-row loop (so rows inserted earlier in this call become candidates) -> test 9 fails.
6. Drop the sort -> R2 fails.

Record which test killed each in the commit message body.

- [ ] **Step 6: Commit**

```bash
git add backend/app/imports/pipeline.py backend/tests/test_import_overlap.py
git commit -m "Hold suspected cross-format duplicates on import"
```

---

### Task 2: Accept held rows via `accept_hashes`

**Files:**
- Modify: `backend/tests/test_import_overlap.py`
- Modify: `backend/app/imports/pipeline.py` only if a test below fails (the check was written in Task 1)

**Interfaces:**
- Consumes: `import_file(..., accept_hashes: frozenset[str])`, `ImportSummary`, helpers from Task 1's test file.
- Produces: nothing new.

- [ ] **Step 1: Add tests 12, 13, 14 and R1**

```python
EXISTING_THREE = (
    ("07/10/2026", "HANNAFORD", "-34.50"),
    ("07/12/2026", "SHELL", "-40.00"),
    ("07/15/2026", "NETFLIX", "-15.49"),
)
NEW_THREE = (
    ("07/11/2026", "HANNAFORD #8354", "-34.50"),
    ("07/14/2026", "SHELL OIL", "-40.00"),
    ("07/15/2026", "NETFLIX.COM", "-15.49"),
)


def hold_three(session):
    """Import EXISTING_THREE, then NEW_THREE; return the summary that holds all three."""
    import_file(session, CHASE_FILE, chase_csv(*EXISTING_THREE))
    summary = import_file(session, CHASE_FILE, chase_csv(*NEW_THREE))
    assert_counts(summary, inserted=0, skipped=0, held=3)
    return summary


def hashes_for(summary, *descriptions: str) -> frozenset[str]:
    return frozenset(s.row_hash for s in summary.suspected_duplicates if s.description in descriptions)


# Test 12
def test_accepting_two_of_three_inserts_exactly_those_two(session):
    first = hold_three(session)
    shell_partner = next(s.existing_id for s in first.suspected_duplicates if s.description == "SHELL OIL")

    second = import_file(
        session, CHASE_FILE, chase_csv(*NEW_THREE),
        accept_hashes=hashes_for(first, "HANNAFORD #8354", "NETFLIX.COM"),
    )

    assert_counts(second, inserted=2, skipped=0, held=1)
    assert [(s.description, s.existing_id) for s in second.suspected_duplicates] == [("SHELL OIL", shell_partner)]
    descriptions = {t.description for t in session.query(Transaction)}
    assert descriptions == {"HANNAFORD", "SHELL", "NETFLIX", "HANNAFORD #8354", "NETFLIX.COM"}

    third = import_file(session, CHASE_FILE, chase_csv(*NEW_THREE))
    assert_counts(third, inserted=0, skipped=2, held=1)
    assert third.suspected_duplicates == second.suspected_duplicates


# Test 13
def test_unknown_accept_hash_is_ignored(session):
    first = hold_three(session)

    second = import_file(
        session, CHASE_FILE, chase_csv(*NEW_THREE), accept_hashes=frozenset({"not-a-real-hash"})
    )

    assert_counts(second, inserted=0, skipped=0, held=3)
    assert second.suspected_duplicates == first.suspected_duplicates


# R1 (Review Focus 4)
def test_accepting_an_already_inserted_hash_changes_nothing(session):
    first = hold_three(session)
    accepted = hashes_for(first, "HANNAFORD #8354")
    import_file(session, CHASE_FILE, chase_csv(*NEW_THREE), accept_hashes=accepted)

    again = import_file(session, CHASE_FILE, chase_csv(*NEW_THREE), accept_hashes=accepted)

    assert_counts(again, inserted=0, skipped=1, held=2)
    assert session.query(Transaction).count() == 4


# Test 14
def test_accepted_row_gets_its_category_from_rules(session):
    groceries = Category(name="Groceries")
    session.add(groceries)
    session.flush()
    session.add(MerchantRule(match_pattern="HANNAFORD #8354", clean_name="Hannaford", category_id=groceries.id))
    session.commit()
    first = hold_three(session)

    import_file(
        session, CHASE_FILE, chase_csv(*NEW_THREE), accept_hashes=hashes_for(first, "HANNAFORD #8354")
    )

    assert txn(session, "HANNAFORD #8354", -3450).category_id == groceries.id
```

- [ ] **Step 2: Run them**

Run: `venv/Scripts/python.exe -m pytest tests/test_import_overlap.py -v` -> 10 passed. If any fail, fix `import_file` (not the test) and re-run.

- [ ] **Step 3: Mutation check (revert after each)**

1. Ignore `accept_hashes` -> tests 12, 14, R1 fail.
2. Insert every held row when `accept_hashes` is non-empty -> tests 12, 13 fail.

- [ ] **Step 4: Full suite, then commit**

Run: `venv/Scripts/python.exe -m pytest -q` -> 226 passed.

```bash
git add backend/tests/test_import_overlap.py backend/app/imports/pipeline.py
git commit -m "Accept held import rows via accept_hashes"
```

(Stage `pipeline.py` only if it changed.)

---

### Task 3: API - `accept_hashes` form field and extended response

**Files:**
- Modify: `backend/app/schemas.py:39-43`
- Modify: `backend/app/routers/imports.py`
- Modify: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `import_file(session, filename, file_bytes, accept_hashes: frozenset[str])`.
- Produces: `POST /imports` multipart `file` + optional repeated `accept_hashes`; JSON adds `rows_held_as_suspected_duplicate: int` and `suspected_duplicates: [{row_hash, account_name, date, description, amount_cents, existing_id, existing_date, existing_description}]`, dates as `YYYY-MM-DD`. Task 4 and Phase 3 rely on this shape.

- [ ] **Step 1: Write test 15 in `test_api.py`**

```python
def chase_upload(*rows: tuple[str, str, str]) -> dict:
    lines = ["Transaction Date,Post Date,Description,Category,Type,Amount,Memo"]
    lines += [f"{day},{day},{description},Shopping,Sale,{amount}," for day, description, amount in rows]
    body = ("\n".join(lines) + "\n").encode()
    return {"file": ("Chase3403_Activity_20260726.csv", body, "text/csv")}


def test_import_holds_suspects_and_accepts_repeated_accept_hashes_fields():
    client = make_client()
    first = client.post("/imports", files=chase_upload(("07/10/2026", "HANNAFORD", "-34.50"),
                                                       ("07/12/2026", "SHELL", "-40.00"),
                                                       ("07/15/2026", "NETFLIX", "-15.49")))
    assert first.json()["rows_held_as_suspected_duplicate"] == 0
    assert first.json()["suspected_duplicates"] == []

    new_rows = (("07/11/2026", "HANNAFORD #8354", "-34.50"),
                ("07/14/2026", "SHELL OIL", "-40.00"),
                ("07/15/2026", "NETFLIX.COM", "-15.49"))
    held = client.post("/imports", files=chase_upload(*new_rows)).json()

    assert held["rows_held_as_suspected_duplicate"] == 3
    hannaford = next(s for s in held["suspected_duplicates"] if s["description"] == "HANNAFORD #8354")
    assert set(hannaford) == {"row_hash", "account_name", "date", "description", "amount_cents",
                              "existing_id", "existing_date", "existing_description"}
    assert hannaford["date"] == "2026-07-11"
    assert hannaford["existing_date"] == "2026-07-10"
    assert hannaford["existing_description"] == "HANNAFORD"

    accept = [s["row_hash"] for s in held["suspected_duplicates"] if s["description"] != "SHELL OIL"]
    resp = client.post("/imports", files=chase_upload(*new_rows), data={"accept_hashes": accept})

    assert resp.status_code == 200
    assert resp.json()["rows_inserted"] == 2
    assert [s["description"] for s in resp.json()["suspected_duplicates"]] == ["SHELL OIL"]
```

Two accepted hashes both being inserted proves the repeated field arrived as a list (a single-value binding would insert one).

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_api.py -k accept_hashes -v`
Expected: FAIL, `KeyError: 'rows_held_as_suspected_duplicate'` (the response model drops the field).

- [ ] **Step 3: Implement**

`schemas.py` (add `from datetime import date` if not already imported):

```python
class SuspectedDuplicateOut(BaseModel):
    row_hash: str
    account_name: str
    date: date
    description: str
    amount_cents: int
    existing_id: int
    existing_date: date
    existing_description: str


class ImportSummaryOut(BaseModel):
    filename: str
    rows_seen: int
    rows_inserted: int
    rows_skipped_as_duplicate: int
    rows_held_as_suspected_duplicate: int
    suspected_duplicates: list[SuspectedDuplicateOut]
```

`routers/imports.py`:

```python
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
...
@router.post("/imports", response_model=ImportSummaryOut)
async def create_import(
    file: UploadFile, accept_hashes: list[str] = Form(default=[]), db: Session = Depends(get_db)
):
    file_bytes = await file.read()
    try:
        summary = import_file(db, file.filename, file_bytes, frozenset(accept_hashes))
    ...
```

Style note: FastAPI's docs now prefer `Annotated[list[str], Form()] = []`; the plain-default form is not deprecated and matches this file's existing `Depends` style, so keep the file consistent.

- [ ] **Step 4: Run test 15, then full suite**

Run: `venv/Scripts/python.exe -m pytest tests/test_api.py -v` -> all pass.
Run: `venv/Scripts/python.exe -m pytest -q` -> 227 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas.py backend/app/routers/imports.py backend/tests/test_api.py
git commit -m "Expose held rows and accept_hashes on POST /imports"
```

---

### Task 4: Status line shows held rows

**Files:**
- Modify: `frontend/src/api.ts:38-43`
- Modify: `frontend/src/format.ts`, `frontend/src/format.test.ts`
- Modify: `frontend/src/App.tsx:160-162`

**Interfaces:**
- Consumes: Task 3's response shape.
- Produces: `SuspectedDuplicate` and extended `ImportSummary` TS types (Phase 3 uses them); `formatImportStatus(summary: ImportSummary): string`.

- [ ] **Step 1: Types in `api.ts`**

```ts
export interface SuspectedDuplicate {
  row_hash: string;
  account_name: string;
  date: string;
  description: string;
  amount_cents: number;
  existing_id: number;
  existing_date: string;
  existing_description: string;
}

export interface ImportSummary {
  filename: string;
  rows_seen: number;
  rows_inserted: number;
  rows_skipped_as_duplicate: number;
  rows_held_as_suspected_duplicate: number;
  suspected_duplicates: SuspectedDuplicate[];
}
```

- [ ] **Step 2: Failing test in `format.test.ts`**

```ts
describe("formatImportStatus", () => {
  const base = {
    filename: "x.csv", rows_seen: 55, rows_inserted: 40, rows_skipped_as_duplicate: 0,
    rows_held_as_suspected_duplicate: 15, suspected_duplicates: [],
  };

  it("reports held rows when there are any", () => {
    expect(formatImportStatus(base)).toBe("x.csv: 40 new, 0 already imported, 15 held as possible duplicates");
  });

  it("keeps today's wording when nothing is held", () => {
    expect(formatImportStatus({ ...base, rows_seen: 40, rows_held_as_suspected_duplicate: 0 }))
      .toBe("x.csv: 40 new, 0 already imported");
  });
});
```

(Add `formatImportStatus` to the file's existing import from `./format`.)

Run: `npx vitest run src/format.test.ts` -> FAIL, `formatImportStatus` is not exported.

- [ ] **Step 3: Implement in `format.ts` and use it in `App.tsx`**

```ts
export function formatImportStatus(summary: ImportSummary): string {
  const base = `${summary.filename}: ${summary.rows_inserted} new, ${summary.rows_skipped_as_duplicate} already imported`;
  const held = summary.rows_held_as_suspected_duplicate;
  return held > 0 ? `${base}, ${held} held as possible duplicates` : base;
}
```

(Add `ImportSummary` to the `./api` type import.) In `App.tsx`, replace the template literal with `setUploadStatus(formatImportStatus(summary));` and import it.

- [ ] **Step 4: Run frontend tests and type-check**

Run: `npx vitest run` -> all pass.
Run: `npx tsc -b` (or `npm run build`) -> no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/format.ts frontend/src/format.test.ts frontend/src/App.tsx
git commit -m "Show held import rows in the upload status line"
```

---

### Task 5: Live verification on a DB copy, docs, close-out review

No code changes. The real `backend/finance.db` and any dev server on port 8000 are not touched.

- [ ] **Step 1: Copy the DB and start a second backend on port 8001**

```bash
cp backend/finance.db "$SCRATCH/finance_phase2.db"
cd backend && DATABASE_PATH="$SCRATCH/finance_phase2.db" venv/Scripts/python.exe -m uvicorn app.main:app --port 8001
```

Run the server in the background (no `--reload`). `$SCRATCH` = this session's scratchpad. Confirm with `curl -s localhost:8001/health`.

- [ ] **Step 2: Build the oracle before importing (raw SQL, no app code)**

The rows the guard must hold are the ones deleted on 2026-10-14: rows in `finance.db.bak-2026-10-14-pre-dedupe` whose id is not in the copy. For each, its partner is the kept row of the same account and amount within 3 days. Script in the scratchpad, read-only on both DBs:

```sql
ATTACH 'file:backend/finance.db.bak-2026-10-14-pre-dedupe?mode=ro' AS b;
SELECT d.id, a.name, d.date, d.amount_cents, d.description,
       (SELECT group_concat(k.id) FROM main.transactions k
         WHERE k.account_id = d.account_id AND k.amount_cents = d.amount_cents
           AND abs(julianday(k.date) - julianday(d.date)) <= 3) AS partner_ids
FROM b.transactions d JOIN b.accounts a ON a.id = d.account_id
WHERE d.id NOT IN (SELECT id FROM main.transactions)
ORDER BY a.name, d.date;
```

Expected from the planning check: 41 rows; Cash Rewards partners {401-408, 410-415, 417}; Savings 562 (+$250.00), 563 (+$0.35); 24 Interest Checking rows (backup ids 935-958). Any row with more than one `partner_ids` gets resolved by hand before comparing.

- [ ] **Step 3: Re-import the 2026-10-14 files**

```bash
curl -s -F "file=@data/ExportData_BOA_July2026_9837.csv" localhost:8001/imports  # corrected at run time: the Aug file (Jul 28 - Aug 24) never held these rows
curl -s -F "file=@data/ExportData_BOA_3938_Oct142026.csv" localhost:8001/imports
```

Expect 9837: 0 new, held 15, each `existing_id` equal to the oracle's partner; 3938: 0 new, held 2 (562, 563). Counts sum to `rows_seen`.

- [ ] **Step 4: Accept one held row, confirm by SQL, re-import**

Pick one 9837 suspect's `row_hash` (e.g. the IKEA $127.35 row) and re-send with `-F "accept_hashes=<hash>"`. Expect 1 new, 14 held. Raw SQL on the copy: transaction count went up by exactly 1, and the new row's `source_row_hash` is that hash. Re-import the 9837 file with no accept: 0 new, 14 held, one more skipped than step 3.

- [ ] **Step 5: The 2026-08-05 file**

```bash
curl -s -F "file=@data/ExportData_BOA_1962_July2026.csv" localhost:8001/imports
```

Expect 24 held, the Jul 1-23 Interest Checking rows, partners equal to the oracle's.

- [ ] **Step 6: Tear down**

Stop the port-8001 server (kill the reloader-less process; confirm port free with `netstat -ano | grep 8001`). Delete `$SCRATCH/finance_phase2.db`. Confirm `backend/finance.db` row count is still 1160.

- [ ] **Step 7: Docs**

Update `docs/lld_import_overlap_guard_claude.md`: status line (Phase 2 built + live-verified, date), decisions 1-4 from this plan's Global Constraints section, the corrected partner-id list and per-file live numbers, and the live results. Update memory `overlap_guard_status.md` (Phase 2 done; next = Phase 3 plan). Commit the doc:

```bash
git add docs/lld_import_overlap_guard_claude.md docs/plan_import_overlap_guard_phase2_claude.md
git commit -m "Record Phase 2 import overlap guard results"
```

- [ ] **Step 8: Close-out review**

Fresh no-context Opus subagent, then `codex exec` (second Opus subagent if Codex is out of quota, and say so), reviewing against `git merge-base HEAD origin/main` from before Task 1 (record the SHA before starting). Both run the backend and frontend suites and report the literal output. Both do mutation testing: for each test in `test_import_overlap.py` and test 15, name a wrong implementation that still passes, reading the helpers (`assert_counts`, `hold_three`, `expected_hash`). Verify every finding against the code before acting; fix unambiguous gaps, bring anything High or design-changing to Liz. Then push.
