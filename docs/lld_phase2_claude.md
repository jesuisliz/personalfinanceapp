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
| Transfers | BOA `Transfers`, `Savings`, `Checks`, `ATM/Cash Withdrawals` — account-to-account movement of the user's own money |
| Credit Card Payment | BOA `Credit Card Payments`, **Chase `Payment` (synthesized, see §2)** — paying off a card, not spending (see §12) |
| RSU/Stock Sales | no raw-category mapping; assigned via a merchant rule matching the brokerage transfer description (see §12) |
| Mortgage | no raw-category mapping; assigned via a merchant rule matching a specific recurring Xoom remittance (see §13) |
| Auto Loan | BOA `Loans` **for one specific account only** (an account-scoped `CategoryRule`, see §13) — every other account's `Loans` raw category still falls through to Transfers |

US Bank and American Express provide no raw category at all — their transactions start uncategorized (`category_id = NULL`) until a rule or manual edit assigns one. This is correct behavior, not a gap: we never guess a category from nothing.

**2026-07-28 updates:** the `Transfers` row above reflects the *original* Phase 2 taxonomy, since narrowed twice more (§12: Credit Card Payment; §13: Mortgage and Auto Loan). Category count as of §13: **20**. See §12/§13 for why and for the current, authoritative mapping.

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
    account_id: int | None (FK accounts.id, nullable)  # added 2026-07-28, see §12
    __table_args__ = (UniqueConstraint("institution", "raw_category", "account_id"),)

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
2. `merchant_rules` match on `description` (§5) — a specific known merchant is a more accurate signal than the bank's own generic raw category, so `apply_merchant_rules` runs *before* `apply_category_rules` in the import pipeline (`app/imports/pipeline.py`).
3. `category_rules` match on `(account_id, transaction.raw_category)` — an account-specific rule (§12).
4. `category_rules` match on `(account.institution, transaction.raw_category)` — the institution-wide rule.
5. Otherwise `NULL` (uncategorized) — never guessed.

Rule application is idempotent: it only sets `category_id` on transactions where it is currently `NULL`, so it's safe to re-run after every import without clobbering manual edits. **This ordering was fixed 2026-07-29 — see §14; before that, category_rules ran first and could permanently claim a transaction a merchant rule would have categorized more accurately.**

## 5. Merchant Cleanup

Priority, highest wins:
1. `transaction.clean_description` already set (manual edit, or a prior rule application) — never overwritten by re-running rule application.
2. `merchant_rules` substring match against `description` (case-insensitive) — first match wins, sets `clean_description` and, if the rule specifies one, `category_id` (only if `category_id` is still `NULL`).
3. Otherwise display the raw `description` as-is.

Because `apply_merchant_rules` now runs before `apply_category_rules` (§4, §14), a merchant rule's `category_id` normally wins outright rather than only filling a gap left by §4 — the "only if still `NULL`" case now mainly protects against re-running merchant rules after a category rule was applied some other way (e.g. a future pipeline change, or a rule added out of band).

No default merchant rules were seeded at launch — CLAUDE.md's "never guess financial data" extends to merchant names; rules get added as patterns are noticed worth cleaning (e.g. `AMAZON MKTPL*` → `Amazon`), same spirit as the `add-bank-source` skill but for merchant patterns instead of bank formats.

**2026-07-28 update — first real rule set added, in response to a discovered gap:** `merchant_rules` had stayed empty this entire project until the native BOA parsers ([[phase1-status]] in memory) landed ~264 transactions with no raw category at all, exposing that *every* category assignment so far had come from `(institution, raw_category)` rules or manual edits, never this mechanism. 53 rules were added, each proposed against and cross-checked with existing categorization precedent already present in the real data (e.g. `DISCOVER CARD` → Transfers mirrors the already-categorized "Payment to Discover Card"; `XOOM` → Transfers mirrors the user's own prior manual edits on "Transfer to Xoom") before being applied, per this doc's "never guess" principle — genuinely ambiguous merchants (a vehicle loan payment, an IRS tax payment, a $2,000 transfer to a named third party outside the tracked accounts, a few subscriptions with no clean category fit, opaque check numbers) were deliberately left out of the rule set for manual categorization instead of guessed. Result: 264 → 44 uncategorized. See [[phase2-status]] for the full list and current uncategorized count.

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
- (2026-07-28 full-app test pass, after the native-BOA backfill in [[phase1-status]]) Confirmed live: manually editing a category via the UI persists correctly for the newly-added `BOA Checking (...1640)` account, same as any other. Confirmed the merchant-rule mechanism, exercised for the first time at scale (53 rules, ~264 candidate rows), behaves as designed — never overwrites an existing `category_id`, applies immediately on rule creation. Also confirmed a previously purely-theoretical point from §6 in practice: transactions correctly get excluded from dashboard totals via the "Transfers" *category* alone, even before their `TransferMatch` pair is confirmed — applying the new rules dropped Feb 2026's overstated dashboard income from ~$65k back to ~$26.5k without touching a single `TransferMatch` row (see [[phase3-status]]).

## 10. Explicit Non-Goals (this phase)

- No subcategories UI (the `parent_id` column exists but nothing uses it yet).
- No AI-assisted merchant cleanup (deferred to Phase 4's chatbot infrastructure, per user decision this session) — rules are hand-authored.
- No bulk category-rule editing UI — rules are seeded once; adding more is a direct DB/API operation for now, not a polished UI, consistent with not over-building ahead of actual need.

## 11. Gotcha Discovered During Verification: Parser Changes Don't Retroactively Fix Already-Imported Rows

The dedupe hash (`compute_row_hashes`, `lld_claude.md` §5.2) is built from `account_id + date + amount_cents + description` — it deliberately excludes `raw_category`, since category has nothing to do with duplicate detection. This means: when the Chase parser was fixed (§2) to synthesize `raw_category = "Payment"`, re-running the import against the real files did **not** update the 15 real `Payment` rows already sitting in `backend/finance.db` from before the fix — `INSERT ... ON CONFLICT DO NOTHING` matched their existing hash and skipped them, silently leaving their old (blank) `raw_category` in place.

This was caught during Phase 2 verification (querying for Chase rows with `NULL raw_category` found exactly the 15 expected `Payment` rows still unfixed) and repaired with a one-time backfill: re-parse the real files with the fixed parser, match each parsed row to its already-stored counterpart by the same dedupe hash, and update `raw_category` wherever it differs. This is safe specifically *because* it matches on the same hash used for dedupe — it can't accidentally update the wrong row.

**Generalizable lesson:** any future change to a parser's *non-hashed* fields (`raw_category`, `memo`, `posted_date`, description cleanup logic, etc.) on a parser that already has real imported data needs this same reconciliation step — re-importing alone will not apply the fix retroactively. A change to a *hashed* field (date, amount, or description) doesn't have this problem, but for a different reason: it would change the hash entirely, which would insert a brand-new duplicate row instead of updating the old one — an even worse outcome, requiring its own manual cleanup. Either way, changing a parser after it has real production data behind it needs a deliberate reconciliation pass, not just a re-import.

## 12. 2026-07-28 Update — Credit Card Payment split from Transfers, RSU/Stock Sales added, account-aware CategoryRule

Three related category-taxonomy changes made in direct response to the user reviewing real categorized data and finding it insufficiently specific:

**Credit Card Payment split out of Transfers.** The user wanted to distinguish "these are savings transfers between my own accounts" from "these are me paying off a credit card" — both were previously lumped under `Transfers`. New category `Credit Card Payment` (category_id 18 in the live DB). Reclassified 67 existing transactions by direct classification (not guessed): every transaction physically on a credit-card-type account, every confirmed-transfer-pair counterpart of one, and every remaining transaction whose raw category or existing merchant-rule label already identified it as a card payment (Discover, Wells Fargo, Best Buy, J.Crew — cards not tracked as accounts in this system, so no confirmed pair exists for these). A payment against an unrelated *loan* (raw category `Loans`, e.g. the vehicle-loan `Payment to Bank of America` rows) was deliberately left in `Transfers`, not reclassified — it isn't a credit card, and this was out of the scope the user asked for. The 6 existing card-payment merchant rules (`AMERICAN EXPRESS`, `BANK OF AMERICA CREDIT CARD`, `CHASE CREDIT CRD`, `DISCOVER CARD`, `US BANK CREDIT CARD`, `WELLS FARGO CARD`) and the BofA `Credit Card Payments`/Chase `Payment` category rules were repointed from `Transfers` to `Credit Card Payment` so future imports land correctly without manual cleanup.

**RSU/Stock Sales added.** A `"Online Banking Transfer From Brk 2454"` transaction (RSU-sale proceeds landing in checking) had been silently swallowed by BofA's raw `Transfers` category, which excludes it from income entirely even though there's no real transfer counterpart in this system (the brokerage account isn't tracked here) — it's real income, just not payroll. New category `RSU/Stock Sales` (category_id 17), plus a merchant rule matching `"Brk 2454"` so future proceeds land here automatically instead of vanishing from the income picture.

**Account-aware `CategoryRule` (the `account_id` column, §3/§4).** Discovered while fixing the two categories above: BofA's own export tags the `BOA Customized Cash Rewards` card's *own payments received* with raw category `Refunds/Adjustments` — the same raw category BofA uses elsewhere for genuine refunds (`Fees & Adjustments`). An institution-wide `(institution, raw_category) → category` rule can't express "except on this one account," so `CategoryRule` gained a nullable `account_id`: when set, it overrides the institution-wide rule for that account only (§4's resolution order). One account-specific rule added: `(Bank of America, Refunds/Adjustments, account=BOA Customized Cash Rewards) → Credit Card Payment`, leaving the institution-wide `Refunds/Adjustments → Fees & Adjustments` rule intact for every other BofA account's genuine refunds.

**Bug this surfaced, fixed same session:** `seed_categories()` (runs on every app startup) looked up an existing rule by `(institution, raw_category)` alone. Once an account-specific rule shared that pair with the institution-wide seeded rule, that lookup returned two rows and crashed the app at startup (`sqlalchemy.exc.MultipleResultsFound`). Fixed by scoping the seed's own existing-rule lookup to `account_id IS NULL` — seeding only ever manages institution-wide rules, so it should never see (or collide with) an account-specific one. Regression test: `test_seed_is_safe_alongside_account_specific_rule` (`test_categories.py`).

**Dashboard/chat exclusion logic generalized.** `app/dashboard/aggregates.py`'s `_load_real_transactions` (Phase 3, §6 of this doc) excluded transactions by category name `"Transfers"` only. Generalized to a `NON_SPENDING_CATEGORY_NAMES` tuple now including `"Credit Card Payment"` too — otherwise the 17 card payments with no confirmed transfer pair would have started counting as real expenses the moment the category was created. This in turn broke the chatbot's `get_category_transactions` tool for these two categories specifically: it drills into a category's `category_breakdown` total, and a non-spending category has no such total by design, so it always returned `[]`. Fixed with a new `non_spending_category_transactions()` function (direct lookup, both money directions, no spending exclusion) that `chat/tools.py` routes to specifically for `"Transfers"`/`"Credit Card Payment"`; every other category keeps the original behavior unchanged. See `lld_phase4_claude.md` for the chat-side narrative and the live-validation numbers.

**Migration note:** `category_rules`'s unique constraint changed from `(institution, raw_category)` to `(institution, raw_category, account_id)` — this required a SQLite table rebuild (create-new/copy/drop/rename), not just `ALTER TABLE ADD COLUMN`, since SQLite can't add a column to an existing composite unique constraint in place.

Verified: full backend suite 128/128 (7 new regression tests added this session — 2 in `test_categories.py`, 3 in `test_dashboard.py`, 2 in `test_chat.py`); frontend `npm run build` clean; live chatbot re-query independently SQL-verified exact match (10/10 transactions, all cents-to-dollars conversions correct) after the fix, versus 3/10 before it and 0/10 immediately after the dashboard-exclusion fix alone (the intermediate, still-wrong state that motivated the chat-side fix).

## 13. 2026-07-28, later still — three merchant-level corrections, plus a second account-scoped `CategoryRule`

**Barnes & Noble** was scattered across three categories (Shopping/Entertainment/Dining & Drinks) purely because of which raw bank category each individual purchase happened to carry — not a deliberate distinction (a café purchase vs. a book vs. a game all landed differently by accident). Consolidated all 17 transactions to **Shopping** via a new merchant rule; the small in-store café spend is folded in rather than split out, per the user's explicit call ("hard to figure out if it's the drinks if i bought a lego").

**Xoom → Mortgage.** 11 `Transfer to Xoom` transactions (~$7,900 across the data) were categorized as `Transfers`, so silently excluded from expense totals entirely — money that looked like it vanished. The user clarified these are real payments for a condo in the Philippines they don't live in themselves. New category **Mortgage**; existing `XOOM` merchant rule repointed to it.

**Vehicle loan → Auto Loan, plus a second dual-source-format gap.** The $800/month vehicle loan payment (7 months, Jan-Jul) had two separate problems, found while investigating a user report that the label was "correct for Jan-Apr, wrong for May-Jul":
1. **Description bug**: one BofA source file (`ExportData_BOA.csv`, the older aggregator export) carries *two* description columns per row — `Original Description` (`BANK OF AMERICA VEHICLE LOAN Bill Payment`) and an aggregator-simplified `Simple Description` (`Payment to Bank of America`). The BOA parser (`app/imports/boa.py`) uses `Simple Description` — the right call for the other 216 differing rows in that file (systematically diffed and keyword-searched for LOAN/MORTGAGE/TAX/IRS/etc. to confirm no other merchant has this problem), but wrong for this one, where it threw away the only detail that mattered. Fixed with a merchant rule mapping `"Payment to Bank of America"` → the fuller label.
2. **Category bug, found via the same investigation**: even after the label was fixed, the 7 payments were split between `Fees & Adjustments` (Jan-Apr, an old assignment predating this session) and `Transfers` (May-Jul) — neither correct for a recurring debt payment. New category **Auto Loan**; all 7 reclassified. Repointing the `"Payment to Bank of America"` merchant rule's `category_id` to Auto Loan looked sufficient but wasn't: the institution-wide `CategoryRule` `(Bank of America, Loans) → Transfers` (rule id 37, pre-existing) still runs *before* merchant rules for any row with a populated `raw_category`, so a future aggregator-format import of this same payment (`raw_category="Loans"`) would have kept landing in Transfers — only its clean_description would have been fixed, not its category. Same account-scoping mechanism as §12's BofA Cash Rewards fix: added `(Bank of America, Loans, account_id=<BOA Interest Checking>) → Auto Loan`, confirmed no other account ever uses BofA's `Loans` raw category (so this can't misfire elsewhere), and verified live by resetting a real transaction's `category_id` to `NULL`, re-running `apply_category_rules`, confirming it resolved to Auto Loan, then restoring the original value.

Category count as of this section: **20**. Full test suite still 132/132 (4 more regression tests added since §12: `test_dispatch_get_category_transactions_all_months_when_month_omitted` and its `test_dashboard.py` counterparts — see `lld_phase4_claude.md` §9 for why "all months" needed its own fix, a related but separate chatbot issue found the same day).

## 14. 2026-07-29 — Central Maine Power split across categories; fixed the general `category_rules`-before-`merchant_rules` precedence bug §13 had flagged but only worked around

User report: "Bills & Utilities" showed Central Maine Power (CMP) payments for Jan-Apr 2026 but not May-Jul, despite the source data having all 7 months. Root cause was the same *class* of bug §13's vehicle-loan fix (account-scoped `CategoryRule`) had worked around for one specific merchant, but this time hit the general case:

1. The BOA Interest Checking account's CMP payments changed description format starting May 2026 (per [[phase1-status]]'s native-BOA-format discovery): Jan-Apr used the old aggregator's ACH string (`CMP DES:CMP PMT ID:...`, no `raw_category` at all), which the existing `merchant_rules` pattern `"CMP DES:CMP PMT"` matched, correctly setting `Bills & Utilities`. May-Jul used the new native-format description (just `Cmp`) *plus* a populated `raw_category` (`"Other Expenses"`).
2. `apply_category_rules` ran before `apply_merchant_rules` in `app/imports/pipeline.py`, so the generic `(Bank of America, "Other Expenses") → Fees & Adjustments` institution-wide rule claimed these 3 transactions first. Even if the merchant-rule pattern had matched `Cmp` (it didn't — too narrow), `apply_merchant_rules` never overwrites an already-set `category_id`, so the merchant rule could never have won under the old pipeline order.
3. This is exactly the general form of the gap §13 flagged in its vehicle-loan fix ("the institution-wide CategoryRule still runs before merchant rules for any row with a populated raw_category") — that fix added a one-off account-scoped `CategoryRule` to work around it for that one merchant; this time the fix addressed the root cause instead.

**Fix, applied at the pipeline level rather than as another one-off account-scoped rule:** swapped the call order in `app/imports/pipeline.py` so `apply_merchant_rules` runs before `apply_category_rules` (§4/§5 updated accordingly). A specific merchant match is a more accurate signal than a bank's own generic raw-category bucket, so it should win by default — the account-scoped-`CategoryRule` mechanism from §12/§13 remains available for cases with no merchant rule at all, but is no longer the only tool for this class of conflict. Also broadened the CMP merchant rule's pattern from `"CMP DES:CMP PMT"` to `"cmp"` (checked case-insensitive substring `"cmp"` against every transaction description in the real data first — matches only the 7 genuine CMP transactions, no false positives) so it catches both description formats. The 3 already-miscategorized May-Jul transactions were corrected directly via `PATCH /transactions/{id}` (the same mechanism as manual category editing), since `apply_merchant_rules` running after the fact still won't touch a transaction whose `category_id` was already set by the old pipeline order.

Checked whether this same precedence conflict silently affects any other merchant right now (a transaction with both a populated `raw_category` and a matching merchant rule of a different category) — it didn't; CMP was the only live case. Added a regression test, `test_merchant_rule_wins_over_raw_category_when_applied_first` in `test_categories.py`, that seeds a conflicting `CategoryRule` and `MerchantRule` for the same transaction and asserts the merchant rule's category wins — this would fail under the old pipeline order. Full suite 133/133. Verified live: all 7 CMP months show `Bills & Utilities` in the Transactions tab, and the July 2026 dashboard category drill-down lists "Central Maine Power" under Bills & Utilities.
