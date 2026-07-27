# Low-Level Design — Personal Finance App (Phase 2: Categories, Merchant Cleanup, Transfers)

**Status: complete** (2026-07-27), verified against the real 654-transaction database, not just synthetic tests — see §9 and §11.

Companion to `hld_claude.md` and `lld_claude.md` (Phase 1). Covers categories, manual editing, merchant cleanup, and transfer/credit-card-payment detection — the four items in CLAUDE.md's Phase 2 list.

## 1. Category Taxonomy (approved, grounded in real data)

Seed categories, and the default mapping from every raw bank category actually observed in `data/` (see conversation for the frequency counts this was derived from):

| Category | Maps from |
|---|---|
| Dining & Drinks | Chase `Food & Drink`, BOA `Restaurants/Dining` |
| Groceries | Chase `Groceries`, BOA `Groceries` |
| Shopping | Chase `Shopping`, BOA `General Merchandise`, `Clothing/Shoes`, `Electronics`, `Hobbies` |
| Travel | Chase `Travel`, BOA `Travel` |
| Automotive & Gas | Chase `Automotive`, `Gas` |
| Home | Chase `Home`, BOA `Home Improvement` |
| Bills & Utilities | Chase `Bills & Utilities`, BOA `Utilities`, `Telephone Services`, `Online Services` |
| Entertainment | Chase `Entertainment`, BOA `Entertainment` |
| Health | Chase `Health & Wellness`, BOA `Healthcare/Medical` |
| Personal Care | BOA `Personal Care` |
| Education | Chase `Education` |
| Child/Dependent | BOA `Child/Dependent Expenses` |
| Fees & Adjustments | Chase `Fees & Adjustments`, BOA `Refunds/Adjustments`, `Other Expenses` |
| Income | BOA `Paychecks/Salary` |
| Interest & Investments | BOA `Interest`, `Securities Trades`, `Rewards` |
| Transfers | BOA `Transfers`, `Savings`, `Credit Card Payments`, `Loans`, `Checks`, `ATM/Cash Withdrawals`, **Chase `Payment` (synthesized, see §2)** |

US Bank and American Express provide no raw category at all — their transactions start uncategorized (`category_id = NULL`) until a rule or manual edit assigns one. This is correct behavior, not a gap: we never guess a category from nothing.

## 2. Chase `Type=Payment` → synthesized raw category

Confirmed in real data: Chase's `Payment`-type rows (`AUTOMATIC PAYMENT - THANK`, `Payment Thank You-Mobile`) have a **blank** `Category` column, while every `Return`/`Adjustment`/`Fee` row has `Category` populated normally. The Chase parser (Phase 1) discards the `Type` column entirely today.

Fix: when `Type == "Payment"` and `Category` is blank, the Chase parser sets `raw_category = "Payment"` instead of `None`. This is additive — it only changes behavior for rows that previously had `raw_category = None`, so it doesn't touch any amount/sign/dedupe behavior already verified in Phase 1. The full Phase 1 test suite is re-run after this change to confirm no regression.

`category_rules` then maps `(institution="Chase", raw_category="Payment") → Transfers`, same mechanism as every other bank mapping, just scoped per-institution to avoid any future collision with an unrelated bank's raw category string spelled the same way.

## 3. Data Model Additions

```python
class Category(Base):
    __tablename__ = "categories"
    id: int (PK)
    name: str (unique)
    parent_id: int | None (FK categories.id, nullable — subcategories, unused for now)

class CategoryRule(Base):
    __tablename__ = "category_rules"
    id: int (PK)
    institution: str          # scopes the rule to one bank's raw category vocabulary
    raw_category: str         # exact match against Transaction.raw_category
    category_id: int (FK categories.id)
    __table_args__ = (UniqueConstraint("institution", "raw_category"),)

class MerchantRule(Base):
    __tablename__ = "merchant_rules"
    id: int (PK)
    match_pattern: str         # substring match against Transaction.description (case-insensitive)
    clean_name: str
    category_id: int | None (FK categories.id, nullable — a merchant rule may also imply a category)

class TransferMatch(Base):
    __tablename__ = "transfer_matches"
    id: int (PK)
    transaction_id_a: int (FK transactions.id)
    transaction_id_b: int (FK transactions.id)
    status: str                # "suggested" | "confirmed" | "rejected"
    __table_args__ = (UniqueConstraint("transaction_id_a", "transaction_id_b"),)
```

`transactions.category_id` (already a plain nullable column since Phase 1) becomes a real `ForeignKey("categories.id")` now that the table exists. New nullable column `transactions.clean_description` — `NULL` means "display the raw `description`"; non-null means an override (whether rule-applied or manually edited) wins.

## 4. Category Resolution

Priority, highest wins:
1. `transaction.category_id` already set (manual edit, or a prior rule application) — never overwritten by re-running rule application.
2. `category_rules` match on `(account.institution, transaction.raw_category)`.
3. Otherwise `NULL` (uncategorized) — never guessed.

Rule application is idempotent: it only sets `category_id` on transactions where it is currently `NULL`, so it's safe to re-run after every import without clobbering manual edits.

## 5. Merchant Cleanup

Priority, highest wins:
1. `transaction.clean_description` already set (manual edit, or a prior rule application) — never overwritten by re-running rule application.
2. `merchant_rules` substring match against `description` (case-insensitive) — first match wins, sets `clean_description` and, if the rule specifies one, `category_id` (only if `category_id` is still `NULL`, per §4's priority).
3. Otherwise display the raw `description` as-is.

No default merchant rules are seeded — CLAUDE.md's "never guess financial data" extends to merchant names; you add rules as you notice patterns worth cleaning (e.g. `AMAZON MKTPL*` → `Amazon`), same spirit as the `add-bank-source` skill but for merchant patterns instead of bank formats.

## 6. Transfer / Credit-Card-Payment Detection

Run as an explicit backend pass (`POST /transfer-matches/detect`), not real-time — it's a batch matching problem over the whole transaction set, not a per-row concern.

**Candidate generation:** two transactions qualify as a candidate pair if:
- They belong to two *different* accounts (both of which are the user's own — true of every account in this system).
- `amount_cents` are exact opposites (`a.amount_cents == -b.amount_cents`).
- `date`s are within 3 days of each other.
- Neither transaction already belongs to a `confirmed` or `rejected` `TransferMatch`.
- No existing `suggested` `TransferMatch` already covers this exact pair (dedupe on the unique constraint).

Each qualifying pair becomes a new `TransferMatch` row with `status="suggested"`. Confirmed real example this will catch: the BOA pair from 2026-07-23 (`Online To Acct# 9837`, -$4,284.66, BOA Interest Checking) ↔ (`Online/Mobile Recurring From Chk 1962`, +$4,284.66, BOA Customized Cash Rewards).

**Review (manual override, as decided):** `GET /transfer-matches?status=suggested` lists pending pairs for the UI to render side by side. `PATCH /transfer-matches/{id}` with `{status: "confirmed"}` sets `is_transfer = true` on both linked transactions and marks the match confirmed. `{status: "rejected"}` marks it rejected — permanently excluded from future re-suggestion, never re-proposed.

**Ambiguity handling:** if a transaction has more than one `suggested` candidate (e.g. two same-amount transfers within the matching window), confirming one match automatically rejects every other `suggested` match that references either of its two transactions — a transaction can only be part of one real transfer pair.

**Why this is separate from the `Transfers` category:** a transaction can be categorized "Transfers" (via §4's rule mapping) without yet having a confirmed pair — e.g. an Amex `AUTOPAY PAYMENT` has no matching outbound transaction in our data at all (we don't have a statement for whatever account actually paid it), so it will never get an `is_transfer` match, but it's still correctly categorized as a transfer and excluded from spending totals by category alone. `is_transfer` is specifically for *confirmed, matched pairs* — used later to avoid double-counting when both sides of a real internal transfer are visible in the data.

## 7. API Endpoints

| Endpoint | Behavior |
|---|---|
| `GET /categories` | list all categories |
| `POST /categories` | create a new category `{name, parent_id?}` |
| `PATCH /categories/{id}` | rename `{name}` |
| `PATCH /transactions/{id}` | manual edit: `{category_id?, clean_description?, is_transfer?}` |
| `GET /merchant-rules` | list all merchant cleanup rules |
| `POST /merchant-rules` | create a rule `{match_pattern, clean_name, category_id?}` — applies immediately to existing matching transactions, not just future imports |
| `POST /transfer-matches/detect` | run the candidate-generation pass, returns newly created `suggested` matches |
| `GET /transfer-matches?status=suggested` | list pending matches for review |
| `PATCH /transfer-matches/{id}` | `{status: "confirmed" \| "rejected"}` |

## 8. Frontend Additions

- Transaction table: category cell becomes an editable `<select>` (options from `GET /categories`, plus "Uncategorized"); on change, `PATCH /transactions/{id}`.
- Description cell: click-to-edit; on save, `PATCH /transactions/{id}` with `clean_description`.
- New "Transfers to review" section: lists `suggested` matches side by side (date/account/description/amount for each side), with Confirm/Reject buttons per pair, and a button to trigger `POST /transfer-matches/detect` after new imports.

## 9. Success Criteria (Phase 2) — all verified against real data

- Every raw category actually observed across all 5 real files (§1's table) resolves to exactly one seeded category — confirmed: 0 uncategorized Chase/BOA rows out of 654 real transactions; only US Bank (6) and Amex (29), which provide no raw category at all, remain uncategorized by default.
- Chase's 15 `Payment`-type rows categorize as "Transfers" via the synthesized `raw_category = "Payment"` rule — confirmed, after a one-time backfill (see §11's note on why existing rows needed reconciling, not just new imports).
- Running transfer detection surfaces the real BOA $4,284.66 pair as a `suggested` match; confirming it sets `is_transfer = true` on both sides — confirmed live in the browser: 27 real candidate pairs found on the first run (including this exact pair and, unexpectedly, a matching outbound payment for the Amex autopay that was assumed to have no counterpart), and confirming the flagged pair correctly flipped `is_transfer` on both sides while leaving an unrelated same-description, different-amount transaction (the $819.75 payment from a different month) untouched.
- Manually editing a transaction's category or description persists across a re-run of rule application — confirmed via a live edit (renamed `DD *DOORDASH MAINELYNO` to `DoorDash` through the actual UI).
- US Bank and Amex transactions remain uncategorized by default (no raw category to map) until a rule or manual edit sets one — confirmed, 35 total uncategorized, all US Bank/Amex.
- The full Phase 1 test suite still passes after the Chase parser change in §2 — confirmed, 54/54 across the whole suite (Phase 1 + Phase 2 tests combined).
- Automated tests cover: category resolution priority, merchant rule priority, transfer-match candidate generation, the "don't re-suggest decided pairs" rule, and the "confirming one match rejects other candidates referencing the same transactions" rule (the ambiguity case actually occurred in real data — several recurring $250/$1,000 transfers between the same three accounts produced genuinely ambiguous candidates, exactly as designed for manual review rather than a silent guess).

## 10. Explicit Non-Goals (this phase)

- No subcategories UI (the `parent_id` column exists but nothing uses it yet).
- No AI-assisted merchant cleanup (deferred to Phase 4's chatbot infrastructure, per user decision this session) — rules are hand-authored.
- No bulk category-rule editing UI — rules are seeded once; adding more is a direct DB/API operation for now, not a polished UI, consistent with not over-building ahead of actual need.

## 11. Gotcha Discovered During Verification: Parser Changes Don't Retroactively Fix Already-Imported Rows

The dedupe hash (`compute_row_hashes`, `lld_claude.md` §5.2) is built from `account_id + date + amount_cents + description` — it deliberately excludes `raw_category`, since category has nothing to do with duplicate detection. This means: when the Chase parser was fixed (§2) to synthesize `raw_category = "Payment"`, re-running the import against the real files did **not** update the 15 real `Payment` rows already sitting in `backend/finance.db` from before the fix — `INSERT ... ON CONFLICT DO NOTHING` matched their existing hash and skipped them, silently leaving their old (blank) `raw_category` in place.

This was caught during Phase 2 verification (querying for Chase rows with `NULL raw_category` found exactly the 15 expected `Payment` rows still unfixed) and repaired with a one-time backfill: re-parse the real files with the fixed parser, match each parsed row to its already-stored counterpart by the same dedupe hash, and update `raw_category` wherever it differs. This is safe specifically *because* it matches on the same hash used for dedupe — it can't accidentally update the wrong row.

**Generalizable lesson:** any future change to a parser's *non-hashed* fields (`raw_category`, `memo`, `posted_date`, description cleanup logic, etc.) on a parser that already has real imported data needs this same reconciliation step — re-importing alone will not apply the fix retroactively. A change to a *hashed* field (date, amount, or description) doesn't have this problem, but for a different reason: it would change the hash entirely, which would insert a brand-new duplicate row instead of updating the old one — an even worse outcome, requiring its own manual cleanup. Either way, changing a parser after it has real production data behind it needs a deliberate reconciliation pass, not just a re-import.
