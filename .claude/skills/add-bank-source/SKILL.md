---
name: add-bank-source
description: Onboard a new bank/credit card CSV statement format into the personal finance app's import pipeline. Use whenever the user adds a new file to data/ from a bank or card not already supported, or asks to "add" / "support" / "import" a new account/statement type.
---

# Add a New Bank CSV Source

This project imports CSV statements from multiple banks into one SQLite database (see `docs/hld_claude.md` and `docs/lld_claude.md`). Each source gets its own parser module — no shared "generic" parser, because every bank so far has turned out to differ in a way that would make sharing logic dangerous (see Step 2).

Follow these steps in order. Do not skip Step 2 — every source added so far has had at least one accuracy-affecting surprise, and "looks like every other CSV" has been wrong every time.

## 1. Inspect the real file before writing any code

Read the actual CSV in `data/` (headers + at least 10-15 data rows, not just the header). Note:
- Exact column names and delimiter/quoting style.
- Date format(s) — transaction date vs. posted date, if both exist.
- Whether the file encodes a BOM (`open(..., 'rb').read()[:5]` — look for `\xef\xbb\xbf`).

Never guess at a format from a filename or bank name alone — read the actual bytes.

## 2. Determine the sign convention — the step most likely to cause silent financial errors

For every source so far, spend has been negative and income/payments positive — **except American Express, which is fully inverted** (charge = positive, payment/credit = negative). Do not assume any bank matches the others. Confirm by finding at least one payment/credit row and one purchase row in the real file and checking their signs make sense together (e.g. a charge and its later refund should be opposite signs of each other).

If the file has an unsigned amount column plus a separate type/direction column (like US Bank's `Transaction: CREDIT/DEBIT`), the parser must raise on any type value it doesn't recognize — never default a sign guess.

## 3. Check for edge cases seen before (and look for new ones)

Known issues so far, all confirmed in real data, not hypothetical:
- **BOM** (Bank of America) — decode with `utf-8-sig` instead of `utf-8`.
- **Thousands-separator commas in amounts** (`"-4,284.66"`, Bank of America) — strip commas before `Decimal()` parsing. `app/imports/base.py::parse_amount_to_cents` already handles this.
- **HTML entities in descriptions** (`&amp;`, Chase) — run through `html.unescape`.
- **Fixed-width padding / repeated internal whitespace** (US Bank, Amex descriptions) — collapse with `re.sub(r"\s+", " ", ...)`.
- **One file, multiple real accounts** (Bank of America mixes a credit card and a checking account via an `Account Name` column) — needs a `row_filter` in `accounts.yaml` and an `account_match_key` on the `ParsedRow`, not a single account mapping.
- **Genuinely repeated real transactions** (Amex: two identical same-day/amount/description charges, one per cardholder on a shared card) — do NOT assume identical rows are duplicate-import artifacts. The dedupe hash (`compute_row_hashes` in `base.py`) already handles this via occurrence-indexing; don't reintroduce a simpler hash that would collapse these.

Check the new file against every item on this list. If it has a new quirk not listed here, add it to this list once you've handled it — this file should grow with every new source.

## 4. Write the parser

Create `backend/app/imports/<bank>.py` implementing the `Parser` protocol from `app/imports/base.py`:

```python
class Parser(Protocol):
    def parse(self, file_bytes: bytes) -> list[ParsedRow]: ...
```

`ParsedRow` fields: `date`, `posted_date` (`None` if not provided), `description`, `amount_cents` (int, negative = expense, positive = income — normalize the sign here, in this parser, not in shared code), `raw_category` (`None` if not provided), `memo` (`None` if not provided), `account_match_key` (only needed for multi-account files like BOA).

Keep sign-flipping logic local to the new parser, even if it duplicates a line or two from another parser. Sharing it risks silently flipping a future bank that didn't need flipping.

## 5. Add the config entry

Add an entry to `backend/app/imports/accounts.yaml` mapping a filename-substring `match` to a `parser` name and one or more `accounts`. Use the real filename actually seen in `data/`. If the file mixes multiple real accounts (like BOA), give each account a `row_filter.account_name_contains` instead of a single unfiltered account.

## 6. Write a synthetic fixture and tests

Create `backend/tests/fixtures/<bank>_sample.csv` — hand-built, small, and safe to commit (never copy real data from `data/` into a fixture). Include at least one row for each edge case found in Steps 2-3 (a payment/credit row to prove sign direction, a BOM if applicable, a repeated-row pair if plausible for that bank, etc.).

Add tests to `backend/tests/test_parsers.py` covering: date parsing, sign correctness (spot-check a specific dollar amount, not just "is negative"), and every edge case from Step 3 that applies to this source. Run:

```
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_parsers.py -v
```

All tests must pass before moving on.

## 7. Update the design docs

Both docs describe all sources by name — keep them in sync:
- `docs/hld_claude.md` §4.1 — add a row to the source table (columns, sign convention).
- `docs/hld_claude.md` §6 — mention the new source in Phase 1 success criteria if it introduces a new kind of check (e.g. a new sign convention or edge case worth spot-checking).
- `docs/lld_claude.md` §3 — add the `accounts.yaml` entry.
- `docs/lld_claude.md` §4 — add a subsection (`4.N <Bank> parser`) with the same field-by-field table style as the existing parsers, including any edge cases and why they matter.
- `docs/lld_claude.md` §11 — extend success criteria to mention the new file and anything source-specific worth checking (a particular sign flip, a particular repeated row, etc.).

## 8. Flag anything that changes shared behavior

If the new source reveals a problem in shared code (like Amex revealing the dedupe hash could silently drop real transactions), stop and raise it explicitly rather than quietly patching it — per this project's "accuracy over features, never guess financial data" principle (`CLAUDE.md`). Confirm the real-world interpretation with the user (e.g. "is this repeated row actually two different charges, or a duplicate?") before deciding how to fix it.
