# Low-Level Design — Personal Finance App (Phase 1: CSV Import + Display)

Companion to `hld_claude.md`. This document covers implementation-level detail for Phase 1: backend structure, schema, parser specs per bank format (based on the actual sample files in `data/`), the import flow, and (§13) the minimal frontend that satisfies CLAUDE.md's "Display transactions" requirement. Phases 2+ are not designed here.

## 1. Backend Project Structure

```
backend/
  app/
    main.py                  # FastAPI app entrypoint
    config.py                 # loads accounts.yaml, .env
    db.py                      # SQLAlchemy engine/session setup
    models.py                  # ORM models (Account, Transaction)
    schemas.py                 # Pydantic response/request models
    routers/
      accounts.py               # GET /accounts
      transactions.py            # GET /transactions
      imports.py                  # POST /imports
    imports/
      accounts.yaml               # account config (see Section 3)
      base.py                     # ParsedRow dataclass + Parser protocol + compute_row_hashes
      chase.py                     # Chase parser
      boa.py                       # Bank of America parser
      us_bank.py                    # US Bank parser
      amex.py                       # American Express parser
      registry.py                   # filename pattern -> parser lookup
      pipeline.py                    # orchestration: read -> parse -> normalize -> dedupe -> insert
  tests/
    fixtures/                    # small, hand-built sample CSVs (no real data)
      chase_sample.csv
      boa_sample.csv
      us_bank_sample.csv
      amex_sample.csv
    test_parsers.py
    test_pipeline.py
    test_api.py
  requirements.txt
  .env.example                  # OPENAI_API_KEY, DATABASE_PATH (copy to .env, unused until Phase 4)

frontend/                        # see Section 13
  src/
    api.ts                        # fetch helpers: accounts, transactions, CSV upload
    App.tsx                       # transaction list + account filter + upload button
```

`data/` (already exists at repo root) holds real downloaded statements and is never committed — see HLD §7. Test fixtures are separate, synthetic, and safe to commit.

## 2. Database Schema

SQLite via SQLAlchemy. Money stored as integer cents to avoid float rounding issues.

```python
# models.py

class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)          # "Chase Sapphire (...3403)"
    institution = Column(String, nullable=False)     # "Chase"
    account_type = Column(String, nullable=False)     # "credit_card" | "checking"
    __table_args__ = (UniqueConstraint("name"),)

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    date = Column(Date, nullable=False)                # transaction date
    posted_date = Column(Date, nullable=True)
    description = Column(String, nullable=False)        # raw, as exported
    amount_cents = Column(Integer, nullable=False)        # negative = expense, positive = income
    raw_category = Column(String, nullable=True)          # bank-provided, unmodified
    memo = Column(String, nullable=True)
    source_row_hash = Column(String, nullable=False)       # sha256 hex digest
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)   # Phase 2
    is_transfer = Column(Boolean, nullable=False, default=False)                 # Phase 2
    __table_args__ = (UniqueConstraint("account_id", "source_row_hash"),)
```

`categories` / `category_rules` tables are not created in Phase 1 — `category_id` stays nullable and unused until Phase 2 to avoid building unused structure early.

## 3. Account Config (`accounts.yaml`)

Maps a filename pattern to one or more account definitions. Matching is "pattern is a substring of the filename," checked in file order, first match wins.

```yaml
- match: "Chase3403"
  parser: chase
  accounts:
    - name: "Chase Sapphire (...3403)"
      institution: "Chase"
      account_type: "credit_card"

- match: "Chase5947"
  parser: chase
  accounts:
    - name: "Chase Freedom (...5947)"
      institution: "Chase"
      account_type: "credit_card"

- match: "ExportData_BOA_1962"
  parser: boa_native_bank
  accounts:
    - name: "BOA Interest Checking"
      institution: "Bank of America"
      account_type: "checking"

- match: "ExportData_BOA_1640"
  parser: boa_native_bank
  accounts:
    - name: "BOA Checking (...1640)"
      institution: "Bank of America"
      account_type: "checking"

- match: "ExportData_BOA_3938"
  parser: boa_native_bank
  accounts:
    - name: "BOA Savings"
      institution: "Bank of America"
      account_type: "savings"

- match: "9837"
  parser: boa_native_card
  accounts:
    - name: "BOA Customized Cash Rewards"
      institution: "Bank of America"
      account_type: "credit_card"

- match: "ExportData_BOA"
  parser: boa
  accounts:
    - name: "BOA Customized Cash Rewards"
      institution: "Bank of America"
      account_type: "credit_card"
      row_filter: {account_name_contains: "Customized Cash Rewards"}
    - name: "BOA Travel Rewards Visa Signature"
      institution: "Bank of America"
      account_type: "credit_card"
      row_filter: {account_name_contains: "Travel Rewards Visa Signature"}
    - name: "BOA Interest Checking"
      institution: "Bank of America"
      account_type: "checking"
      row_filter: {account_name_contains: "Bank - Bofa Interest Checking"}
    - name: "BOA Savings"
      institution: "Bank of America"
      account_type: "savings"
      row_filter: {account_name_contains: "Bank - Credit"}

- match: "US Bank - 8606"
  parser: us_bank
  accounts:
    - name: "US Bank (...8606)"
      institution: "US Bank"
      account_type: "credit_card"

- match: "AmericanExpress_activity"
  parser: amex
  accounts:
    - name: "American Express"
      institution: "American Express"
      account_type: "credit_card"
```

**Why BOA is a list of accounts, not one:** the BOA aggregator export's `Account Name` column mixes rows from multiple real accounts in a single CSV. Chase and US Bank files are one-account-per-file, so their `accounts` list has exactly one entry with no `row_filter`. The BOA parser uses `row_filter.account_name_contains` to split incoming rows to the correct `Account` record.

**Native per-account BOA exports (2026-07-28):** downloading history directly from BofA per account (`ExportData_BOA_1962_6mos.csv`, `_1640_6mos.csv`, `_3938_6mos.csv`, `ExportData_BOA_<Month>2026_9837.csv`) produces a different file per real account, not one combined file — so these entries are single-account, no `row_filter`, same as Chase/US Bank. They match on the account number embedded in the filename (`1962`, `1640`, `3938`, `9837`) rather than the generic `ExportData_BOA` prefix, and are listed **before** the generic `ExportData_BOA` entry since `match()` is first-match-wins on substring and every one of these filenames also contains `"ExportData_BOA"`. `1962` → BOA Interest Checking, `3938` → BOA Savings, `9837` → BOA Customized Cash Rewards (all three confirmed by cross-referencing transfer/payment amounts against the original aggregator file); `1640` is a second checking account the aggregator export never surfaced on its own.

**This was confirmed the hard way, not assumed:** the design was originally written expecting two BOA accounts (one credit card, one checking) based on a partial preview of the file. Running the pipeline against the *complete* real file surfaced two more real accounts the preview never showed — a second credit card (`Travel Rewards Visa Signature`) and a savings account whose export literally labels it `Bank of America - Bank - Credit` (confirmed with the user to be a savings account despite the odd name, paired with the checking account via transfers and interest income). Because `resolve_account_definition` raises on an unrecognized `Account Name` instead of silently defaulting to some account, this showed up as a hard error during verification rather than misattributed transactions — exactly the failure mode Section 8's error handling is meant to produce. The lesson generalized into `.claude/skills/add-bank-source/SKILL.md`: always inspect the *complete* file, not a sample of it, especially for any format where one file can contain multiple accounts.

**Also worth noting:** the original `row_filter` for the first credit card used `account_name_contains: "Credit Card"`, which is a substring of *both* real credit card account names (`Bank of America - Credit Card - Customized Cash Rewards World Mastercard` and `Bank of America - Credit Card - Travel Rewards Visa Signature`). It only "worked" while the second card was unknown. Each `row_filter` must be a substring unique to exactly one real account name — a filter that happens to also match a different account you haven't discovered yet will silently misattribute that account's transactions once it appears, with no error to catch it (unlike a totally unrecognized name, which does raise).

## 4. Parser Interface

```python
# base.py
@dataclass
class ParsedRow:
    date: date
    posted_date: date | None
    description: str
    amount_cents: int        # already sign-normalized: negative = expense
    raw_category: str | None
    memo: str | None
    account_match_key: str | None = None   # used only by multi-account parsers (BOA)

class Parser(Protocol):
    def parse(self, file_bytes: bytes) -> list[ParsedRow]: ...
```

Each bank parser is a plain function/class implementing `parse()`. No shared base-class magic — four formats, four small independent implementations, per CLAUDE.md's "don't over-engineer."

### 4.1 Chase parser (`chase.py`)

Source columns: `Transaction Date, Post Date, Description, Category, Type, Amount, Memo`

| Field | Rule |
|---|---|
| `date` | parse `Transaction Date` as `MM/DD/YYYY` |
| `posted_date` | parse `Post Date` as `MM/DD/YYYY` |
| `description` | `Description`, HTML-unescape (`&amp;` → `&` — seen in sample: `BARNES &amp; NOBLE`) |
| `amount_cents` | `Amount` is already signed (negative = spend); parse as Decimal, multiply by 100, round to int. No sign flip needed. |
| `raw_category` | `Category`, as-is |
| `memo` | `Memo`, empty string → `None` |

`Type` column (`Sale`, `Adjustment`, etc.) is not currently used for anything beyond being ignored — no transaction is dropped based on it. Revisit if a `Type` value implies something the amount sign doesn't already capture.

### 4.2 Bank of America parser (`boa.py`)

Source columns: `Status, Date, Original Description, Split Type, Category, Currency, Amount, User Description, Memo, Classification, Account Name, Simple Description` (file has a UTF-8 BOM — open with `encoding="utf-8-sig"`).

| Field | Rule |
|---|---|
| `date` | parse `Date` as `MM/DD/YYYY` |
| `posted_date` | `None` for `pending` rows; same as `date` for `posted` rows (BOA doesn't give a distinct post date) |
| `description` | `Simple Description` (cleaner than `Original Description`, which has trailing whitespace/padding — e.g. `"THE HOME DEPOT #2401     PORTLAND     ME"`), stripped |
| `amount_cents` | `Amount`, strip thousands-separator commas before Decimal parse (sample has `"-4,284.66"` and `"4,284.66"`) — already signed, no flip |
| `raw_category` | `Category` |
| `memo` | `Memo`, stripped; empty/whitespace-only → `None` |
| `account_match_key` | raw `Account Name` value, used to resolve which config `accounts[]` entry (via `row_filter.account_name_contains`) this row belongs to |

**Pending vs. posted:** both are imported. `Status` is not currently stored as its own column (not in the Phase 1 schema) — a `pending` row and its later `posted` counterpart are two different rows in the export with no shared ID, so no reconciliation is attempted in Phase 1. This is a known limitation, called out in Section 7.

### 4.2b Bank of America native checking/savings parser (`boa_native_bank.py`)

Source columns: a 5-line summary block (`Description,,Summary Amt.` then Beginning/Total credits/Total debits/Ending balance rows), a blank line, then `Date, Description, Amount, Running Bal.`. No BOM. No `Account Name` column — each file is already scoped to one real account, so this parser sets `account_match_key` to `None` and the config entry has exactly one unfiltered account (like Chase/US Bank).

| Field | Rule |
|---|---|
| `date` | find the header line starting with `Date,`, then parse `Date` as `MM/DD/YYYY` for every row after it |
| `posted_date` | `None` (file gives one date only, no pending/posted distinction) |
| `description` | `Description`, stripped |
| `amount_cents` | `Amount`, strip thousands-separator commas before Decimal parse (same as the aggregator BOA parser) — already signed, no flip |
| `raw_category` | `None` (no category column) |
| `memo` | `None` (no memo column) |

**Beginning balance row:** the first data row (`Beginning balance as of ...`) has an empty `Amount` (only `Running Bal.` is populated) — skipped rather than parsed, since it isn't a real transaction.

### 4.2c Bank of America native credit card parser (`boa_native_card.py`)

Source columns: `Posted Date, Reference Number, Payee, Address, Amount`. No BOM.

| Field | Rule |
|---|---|
| `date` | parse `Posted Date` as `MM/DD/YYYY` |
| `posted_date` | `None` (only one date given) |
| `description` | `Payee`, collapse repeated internal whitespace |
| `amount_cents` | `Amount` — negative = charge, positive = payment (same convention as every other BOA source; confirmed against the real sample: a `400.28` payment row matches, to the cent, a `-400.28` "BANK OF AMERICA CREDIT CARD Bill Payment" row in the corresponding checking account's file) |
| `raw_category` | `None` (no category column) |
| `memo` | `None` (no memo column; `Reference Number`/`Address` are not currently stored) |

### 4.3 US Bank parser (`us_bank.py`)

Source columns: `"Date","Transaction","Name","Memo","Amount"` (quoted, comma-delimited).

| Field | Rule |
|---|---|
| `date` | parse `Date` as `YYYY-MM-DD` (already ISO in the sample) |
| `posted_date` | `None` (not provided) |
| `description` | `Name`, collapse repeated internal whitespace (sample: `"PAYMENT   THANK YOU"`) |
| `amount_cents` | `Amount` is unsigned. Sign comes from `Transaction`: `CREDIT` → positive, `DEBIT` → negative. Sample data only contains `CREDIT` rows; `DEBIT` handling is written defensively but untested against a real sample — flagged in Section 7. Any `Transaction` value other than `CREDIT`/`DEBIT` raises rather than silently guessing a sign. |
| `raw_category` | `None` (US Bank export has no category column) |
| `memo` | `Memo`, as-is |

### 4.4 American Express parser (`amex.py`)

Source columns: `Date, Description, Amount` — the simplest format of the five, and the only one whose sign convention is inverted.

| Field | Rule |
|---|---|
| `date` | parse `Date` as `MM/DD/YYYY` |
| `posted_date` | `None` (not provided) |
| `description` | `Description`, collapse repeated internal whitespace (same fixed-width padding artifact as US Bank, e.g. `"AplPay ROOTS CAFE   WESTBROOK           ME"`) |
| `amount_cents` | `Amount` is signed, but **opposite** of every other source: positive = charge, negative = payment/credit (confirmed against the real sample: `AUTOPAY PAYMENT - THANK YOU` is `-243.07`; a hotel charge/refund pair appears as `334.37` then `-334.37`). The parser negates the parsed value before returning it, so the stored sign matches the rest of the system (negative = expense). |
| `raw_category` | `None` (Amex export has no category column) |
| `memo` | `None` (Amex export has no memo column) |

**This source is the reason the sign-flip step isn't shared code:** if Amex's negation were merged into a shared helper, a future bank whose convention matches Chase's would silently get flipped too. Each parser owns its own sign logic for exactly this reason.

## 5. Normalization & Dedupe

### 5.1 Sign convention

Enforced at the end of each parser (not in shared code, to keep each parser's logic self-contained and readable): output `amount_cents` is always negative = money out, positive = money in, no matter the source format's own convention.

### 5.2 Duplicate hash

Confirmed against real data, not just a hypothetical: the Amex sample has two genuinely distinct charges on 2026-03-22, same amount ($7.50), same description (`AplPay NYX=RELAX & R...`) — one per person on a shared card. A hash of just account+date+amount+description would collide and silently drop the second one. The hash includes each row's **occurrence index within the file** (1st, 2nd, 3rd... time this exact combination appears, counted in file order) specifically to keep both:

```python
def compute_row_hashes(account_id: int, rows: list[ParsedRow]) -> list[str]:
    seen_counts: dict[str, int] = {}
    hashes = []
    for row in rows:
        base_key = f"{account_id}|{row.date.isoformat()}|{row.amount_cents}|{row.description.strip().lower()}"
        occurrence = seen_counts.get(base_key, 0)
        seen_counts[base_key] = occurrence + 1
        key = f"{base_key}|{occurrence}"
        hashes.append(hashlib.sha256(key.encode("utf-8")).hexdigest())
    return hashes
```

Hashing is done over the whole file's rows at once (not row-by-row in isolation), since the occurrence index depends on how many identical rows came before it *within that file, in file order*.

Enforced via the `UniqueConstraint("account_id", "source_row_hash")` on `transactions` — re-importing the exact same file reproduces the same occurrence indices in the same order, so it's still a no-op bulk-insert-with-conflict-ignore, not an app-level pre-check.

**Residual known limitation:** this only works because occurrence order is stable across re-imports of the *same* file. If a bank re-exports an overlapping date range with rows in a different order, or a new legitimately-repeated row is inserted mid-sequence in a later re-download, the occurrence-index assignment could shift and produce an incorrect duplicate/insert decision. This is considered acceptable residual risk for Phase 1 — flagged in Section 12, revisit if a real re-download ever reorders rows.

## 6. Import Pipeline (`pipeline.py`)

```
import_file(filename, file_bytes):
    config_entry = registry.match(filename)          # raise if no pattern matches
    rows = config_entry.parser.parse(file_bytes)
    # rows are grouped by resolved account first, since occurrence-index hashing
    # (Section 5.2) is computed per account, in file order
    rows_by_account = group_rows_by_resolved_account(config_entry, rows)
    for account, account_rows in rows_by_account.items():
        account_id = get_or_create_account(account)    # idempotent on Account.name
        row_hashes = compute_row_hashes(account_id, account_rows)
        for row, row_hash in zip(account_rows, row_hashes):
            upsert_transaction(account_id, row, row_hash)   # INSERT ... ON CONFLICT DO NOTHING
    return ImportSummary(filename, rows_seen, rows_inserted, rows_skipped_as_duplicate)
```

`resolve_account` for single-account configs (Chase, US Bank) ignores `account_match_key` and always returns the one configured account. For BOA, it matches `row.account_match_key` against each `row_filter.account_name_contains`; a row matching none of the configured filters raises rather than being silently dropped or mis-assigned.

## 7. API Endpoints (Phase 1)

| Endpoint | Behavior |
|---|---|
| `POST /imports` | multipart file upload; runs the pipeline; returns `ImportSummary` (filename, counts) |
| `GET /accounts` | list all accounts |
| `GET /transactions` | list transactions, filterable by `account_id`, `date_from`, `date_to`; paginated |

No update/delete endpoints for transactions in Phase 1 — manual category editing (which implies a `PATCH`) is Phase 2.

## 8. Error Handling

- Unrecognized filename (no `accounts.yaml` match): reject the import with a clear error naming the filename — never guess an account.
- Unparseable row (bad date, non-numeric amount, unrecognized `Transaction` value in US Bank): the whole file import fails with the offending row number and raw content in the error — no partial/silent-skip import. Accuracy over convenience.
- BOA row whose `Account Name` matches no configured `row_filter`: same — hard failure naming the row, not a silent drop.

## 9. Logging & Privacy

- Log import summaries (filename, row counts) at INFO.
- Never log full transaction rows, descriptions, or amounts — these can contain account fragments (e.g. `xxx-xxx-0204`, `Check xxxxxxx0186`). Log row *numbers* on error, not row *content*, when writing to persistent logs; raw content in an error response to the local UI is fine, since it never leaves the machine.

## 10. Testing Strategy

- Hand-built synthetic fixtures in `tests/fixtures/` mirroring each real format's column structure and known edge cases (HTML entities, comma-in-amount, multi-account rows, BOM, inverted sign convention, same-day repeated rows) — never real statements from `data/`.
- Unit tests per parser: correct sign normalization, correct date parsing, edge cases above.
- Pipeline test: import same fixture twice, assert second import inserts zero new rows.
- Pipeline test: BOA fixture with both account types, assert rows land in two distinct `Account` records.
- Pipeline test: fixture with two genuinely repeated rows (same account/date/amount/description), assert both are inserted on first import and both survive a second, deduped re-import.

## 11. Success Criteria (Phase 1)

Concrete, checkable against the five real files in `data/` — this is what "Phase 1 works" means in practice, mirroring `hld_claude.md` §6 but at the level of an actual test pass:

- Importing `Chase3403_Activity_20260726.csv`, `Chase5947_Activity_20260726.csv`, `ExportData_BOA.csv`, `US Bank - 8606_01-01-2026_06-30-2026.csv`, and `AmericanExpress_activity.csv` each succeeds with zero manual edits to the source files.
- `ExportData_BOA.csv` produces transactions split across exactly four `Account` records (two credit cards, one checking, one savings) — confirmed against the real file, not the two originally assumed from a partial preview.
- Spend rows are negative and income/payment rows are positive in the DB for all five files, verified by spot-checking a handful of rows against the raw CSV (e.g. the `DOORDASH` charge, the `PAYMENT THANK YOU` credit, and the Amex `AUTOPAY PAYMENT` row landing positive despite being negative in the source file).
- The two real, distinct $7.50 Amex charges on 2026-03-22 both appear in the database — not collapsed into one.
- Re-running the same import a second time inserts 0 new rows (`rows_inserted == 0` in the returned `ImportSummary`), including for the Amex file with its repeated-row pair.
- Per-account net totals computed by the app match an independent hand-sum of each account's raw CSV rows exactly, verified for all 8 real accounts across the 5 files (this was actually run, not just asserted — see verification notes for this phase).
- `GET /transactions` returns all imported rows, filterable by account and date range, and the totals a human would hand-add from the raw CSVs match the sums returned by the API.
- Malformed input (e.g. a filename matching no `accounts.yaml` entry, or a BOA row whose `Account Name` matches no configured `row_filter`) fails the import with a clear error — it never creates a guessed account or drops the file silently.
- Automated tests in `tests/` (parsers + pipeline, per Section 10) pass using only synthetic fixtures — no real statement from `data/` is ever read by a test or committed to version control.
- (2026-07-28 follow-up) Native per-account BOA re-downloads for `1962` (checking) and `3938` (savings) cover a date range that overlaps already-imported aggregator data (Apr27–Jul25 for `1962`, May7–Jul25 for `3938`), with different description text than the aggregator export — so the hash-based dedupe in Section 5.2 would not catch the overlap. Handled by trimming those two files to their non-overlapping date range (Jan1 up to, not including, the aggregator's earliest date for that account) before import, rather than importing the full 6-month file and relying on dedupe. `1640` (new account) and the `9837` monthly card files have no overlap and were imported in full.

## 12. Deferred / Known Limitations (carried forward, not solved here)

- Pending → posted reconciliation for BOA (Section 4.2).
- Occurrence-index dedupe assumes stable row order across re-imports of the same file; a re-download with reordered or mid-inserted rows could misassign occurrence indices (Section 5.2, residual limitation).
- US Bank `DEBIT` sign handling is exercised only against a synthetic fixture, not a real US Bank `DEBIT` row (Section 4.3).
- Transfers and credit-card-payment detection (e.g. the BOA `Credit Card Payments` / `Transfers` categories, and Amex `AUTOPAY PAYMENT`, seen in the samples) — Phase 2, per HLD.
- Categories, rules, manual editing — Phase 2.
- Git/version control — deferred by user request.

## 13. Frontend (Display Transactions)

CLAUDE.md's Phase 1 roadmap has five items; the previous sections cover the first four (import, normalize, store, dedupe). This section covers the fifth — "Display transactions" — which needed an actual browser-rendered page, not just an API response.

### 13.1 Structure

```
frontend/
  src/
    api.ts     # typed fetch helpers: fetchAccounts, fetchTransactions, uploadCsv
    App.tsx    # the entire UI: account filter dropdown, CSV upload button, transaction table
```

Deliberately one component, no routing library, no client-side state management library, no design system — a single page with `useState`/`useEffect` and native `fetch`. Anything more is premature for "list your transactions and let me import a file."

### 13.2 CORS

The backend is local-only and has exactly one real caller (the Vite dev server on `http://localhost:5173`), so `CORSMiddleware` in `app/main.py` allow-lists that one origin rather than using a wildcard.

### 13.3 API base URL

`api.ts` hardcodes `http://localhost:8000` as `API_BASE`. No `.env`-driven config layer for this — it's a single local developer running both servers on fixed ports; an env var would be indirection with no current payoff (revisit if the app ever needs to run against a non-default port or a remote backend).

### 13.4 Behavior

- Account filter: a native `<select>` populated from `GET /accounts`, defaulting to "All accounts". Selecting one re-fetches `GET /transactions?account_id=<id>`.
- Transaction table: date, account name (resolved client-side from the accounts list, not repeated per-row from the API), description, category, and amount — amount in red when negative (expense), green when positive (income), formatted via `toLocaleString(..., {style: "currency"})`.
- CSV upload: a styled `<label>` wrapping a hidden `<input type="file">`; on change, `POST /imports` as multipart form data, show the returned `ImportSummary` inline (`"<filename>: N new, M already imported"`), then re-fetch the transaction list. Import errors (e.g. unmatched filename) surface the backend's error `detail` text directly rather than a generic failure message, consistent with Section 8's "no silent failure" principle.
- Transaction list is capped at `limit=1000` (the API's max per Section 7) with no pagination UI yet — acceptable for the current real data volume (654 transactions across 8 accounts); revisit if that grows past 1000.

### 13.5 Verification performed

Not just `npm run build` passing — the actual running app was checked in a real browser against the real data in `data/`:
- All 5 real files imported into a real `backend/finance.db` (via the pipeline directly, not the UI, since the browser automation tool can only upload files explicitly shared with its session — not arbitrary paths from `data/`).
- Loaded `http://localhost:5173` and visually confirmed transactions render with correct signs, real merchant names, and real categories, matching the totals already hand-verified in Section 11.
- Confirmed the account filter actually filters (selected BOA Savings, confirmed every visible row belonged to that account and matched its known interest/transfer pattern).
- Confirmed zero browser console errors on load.
- Separately verified the upload button itself (not just the API) using a small synthetic file named to match the `Chase3403` config pattern (real data wasn't used for this check, per Section 10's rule against real statements in anything test-like) — confirmed the UI showed `"1 new, 0 already imported"` and the row appeared in the table. That synthetic row was deleted from the real database afterward so it doesn't pollute real data going forward.

### 13.6 Known limitations

- No pagination UI (Section 13.4) — fine until transaction count exceeds ~1000.
- No sorting/search beyond the account filter — acceptable for Phase 1; likely to matter more once Phase 3's dashboard exists.
- No loading/error states beyond plain text — fine for a single local user, would need real UX work before this app is ever multi-user (which CLAUDE.md rules out anyway).
