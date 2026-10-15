# LLD: Remember a manual category edit as a merchant rule

Status: DRAFT v3 for approval (2026-10-15), revised after Opus and Codex
spec reviews (see section 10). No code written yet.

## 1. Context

Twice (2026-08-05, 2026-10-14) a new import produced a pile of uncategorized
rows that had to be categorized by hand, including merchants that had already
been categorized by hand before. Root cause, confirmed 2026-10-14: the app
never learns from a manual edit. Categorization comes only from

- `CategoryRule` (institution/account + `raw_category`) - no help where
  `raw_category` is NULL, which is every Amex, US Bank and BOA 1640 row and
  most rows on BOA 3/4/5 (all BOA native exports), and
- `MerchantRule` (substring `match_pattern` against `description`).

A manual edit through `PATCH /transactions/{id}` changes one row and nothing
else. This feature lets the user turn that edit into a `MerchantRule`
deliberately, with a preview, so the next import categorizes the merchant.

Decisions made with the user (2026-10-15):

| Question | Decision |
|---|---|
| Trigger | Opt-in prompt after a category edit; nothing saved without "Save rule" |
| Existing rule already matches the edited row | Warn and refuse; rule precedence is unchanged |
| Default scope | All accounts; switchable to "this account only" |
| Undo | `DELETE /merchant-rules/{id}` only; no rules management screen |

## 2. Data model

No schema change. A rule created this way is an ordinary `MerchantRule`. We
do not record that it came from an edit; nothing would read that field.

## 3. Facts about current behavior this design relies on

- `apply_merchant_rules` checks account-scoped rules first, then global
  rules, each tier in id order; first case-insensitive substring match wins
  (`apply.py:68-91`).
- It only touches rows whose `clean_description` is NULL, and only fills
  `category_id` when it is NULL. A non-null category is never overwritten.
  Caveat: a row the user deliberately set back to Uncategorized is
  indistinguishable from a never-categorized one, and a rule may fill it.
- It runs after every import (`pipeline.py:185`), at startup (`main.py:28-29`)
  and after `POST /merchant-rules`. Rows with NULL `clean_description` are
  *usually* unmatched by every existing rule, but not guaranteed (clearing a
  rename in the UI stores NULL), so the preview simulates rather than
  assuming this (4.2).
- On import, merchant rules run before `CategoryRule`, so a new rule also
  outranks `raw_category` mapping for future rows on accounts that have it
  (Chase). The preview cannot show that; the panel says so in one line.
- Startup runs them in the opposite order (category rules first,
  `main.py:27-29`), so a row both could match gets a different category
  depending on whether it was filled at import or at startup. Fixed in 4.5.
- A rule assigning Transfers does not set `is_transfer`; the dashboard
  excludes the category regardless (`aggregates.py:35`). No interaction.
- Live DB 2026-10-15: 76 rules, 1188 rows, 0 uncategorized, 547 with NULL
  `clean_description`.


## 4. Backend

### 4.1 `app/categories/apply.py`

- **`find_matching_rule(rules, description, account_id) -> MerchantRule | None`**
  - the precedence logic extracted from `apply_merchant_rules`, which is
  refactored to call it. Account-scoped rules for `account_id` first, then
  global rules; within a tier it sorts by the key `(rule.id is None,
  rule.id or 0)`, so an unsaved candidate (id None) sorts as the newest rule
  of its tier. It sorts itself rather than trusting caller order. One source
  of truth, so the preview can never disagree with imports.
- **`suggest_match_pattern(description) -> str`** - a pre-fill only; the user
  always sees and can edit it. Exact algorithm; all positions are indexes
  into the original string, so the result is always a contiguous slice and
  always matches its own row (44 real descriptions contain double spaces):
  1. `start` = 7 if the description starts with `AplPay `, else 0;
     `body` = `description[start:]`.
  2. If `body` contains ` DES:`, end at that index.
  3. Else, if `body` contains `*` and the text before the first `*`,
     stripped, is a single non-empty token (no internal whitespace): end at
     the end of the first non-space run after the `*` (skipping spaces
     right after it); if there is none, end just after the `*`.
     `SQ *7-ELEVEN 1234` -> `SQ *7-ELEVEN`; `IC* INSTACART SAN FRANCISCOCA`
     -> `IC* INSTACART`; `UBER   *TRIP ...` -> `UBER   *TRIP`.
  4. Else, scan `body`'s non-space tokens with their spans; end at the end
     of the last token before the first token containing a digit or `#`
     (empty if the first token has one). `TRADER JOE S #519 PORTLAND ME` ->
     `TRADER JOE S`; `MACYS  ROCKINGHAM PK` -> whole string.
  5. `pattern = description[start:end]`. If shorter than 4 characters,
     return the whole original description instead (`AplPay SQ` ->
     `AplPay SQ`, never `SQ`).
  The panel's preview and the mismatch block are the real guard; this only
  sets a sensible default.
- **`normalize_rule_text(value) -> str`** - strips whitespace; used by both
  the preview and create schemas so the pattern previewed is identical to
  the pattern stored. Blank after stripping is a 422.

### 4.2 `evaluate_candidate` + `POST /merchant-rules/preview`

One server function does all the checking, used by both preview and create:

`evaluate_candidate(session, source_txn, match_pattern, category_id, this_account_only)`

1. **Source category check.** `source_txn.category_id` must equal
   `category_id`, else refuse with code `source_category_changed` (the user
   changed the row again after the panel opened, e.g. back to
   Uncategorized; saving would immediately recategorize it).
2. **Candidate.** An unsaved `MerchantRule` (id None) with `account_id` =
   the source row's account when `this_account_only`, else NULL. The
   account always comes from the source row.
3. **`matches_source`** = case-insensitive substring of the candidate
   pattern in the source description, computed directly. When false,
   `conflicting_rule` is null (a non-match is not a conflict) and create
   refuses with 400.
4. **Conflict** (only when `matches_source`): `find_matching_rule(existing +
   [candidate], source description, source account)`; if the winner is not
   the candidate, it is the `conflicting_rule`.
5. **Simulation.** For every row in scope (the source account when
   `this_account_only`, else all rows), in any `clean_description` state,
   compute the winner the same way. "Candidate wins" = the rule that would
   claim this description if the row arrived in a new import. Then:
   - `would_name_count`: candidate wins and `clean_description` is NULL;
   - `would_categorize_count`: of those, `category_id` is also NULL;
   - `category_mismatch_count`: candidate wins and `category_id` is set and
     differs from `category_id` (includes manually renamed rows - the rule
     won't touch them, but it would mis-file their future siblings);
   - `sample`: up to 5 candidate-win rows, mismatches first, then newest
     first: `{id, date, description, category_name}`.

`POST /merchant-rules/preview` request: `{source_transaction_id,
match_pattern | null, category_id, this_account_only}`; a null pattern means
"use `suggest_match_pattern` on the source row". 404 if the source
transaction doesn't exist; `source_category_changed` returns 409. Read-only.
Response:

```
{
  "match_pattern": str,               // normalized pattern evaluated
  "matches_source": bool,
  "conflicting_rule": {id, match_pattern, clean_name, category_id, account_id} | null,
  "would_name_count": int,
  "would_categorize_count": int,
  "category_mismatch_count": int,
  "sample": [{id, date, description, category_name}]
}
```

"UBER -> Dining & Drinks" reports 30 mismatches (rows in Travel); any
mismatch blocks saving (9.1).

### 4.3 `POST /merchant-rules` (existing)

- Validation for all callers: `match_pattern` and `clean_name` go through
  `normalize_rule_text` and are stored stripped (`""` is a substring of
  everything; a blank pattern would rename all 547 blank rows).
- Optional `source_transaction_id` + `this_account_only`. With a source,
  `account_id` in the body is rejected (422); the stored account is the one
  `evaluate_candidate` derived. Refusals, checked in this order:
  404 no such transaction; 409 `source_category_changed`; 400 pattern
  doesn't match the source; 409 `conflict` (detail includes the rule);
  409 `category_mismatch` (detail includes count and sample).
  Error detail is `{code, message, ...}` so the panel can show it.
- Without a source, behavior is unchanged apart from the validation.

### 4.4 `DELETE /merchant-rules/{id}`

204 on success, 404 if missing. Does not revert rows the rule already
filled; they stay editable in the table.

### 4.5 Startup order (`main.py`)

Swap to merchant rules first, then category rules, matching the import
pipeline (`pipeline.py:181-186`). Live effect today: none (0 uncategorized
rows). It matters once new rules exist, because a row filled at startup
should get the same category as one filled at import.

## 5. Frontend

- **`rememberRule.ts`** - a reducer like `heldImport.ts`, holding
  `{source snapshot, categoryId, pattern, patternTouched, name,
  thisAccountOnly, preview, latestSeq, error, saved} | null`. Actions:
  `categoryEdited(txn, categoryId | null)` (non-null opens or replaces;
  null closes), `previewRequested(seq)`, `previewReceived(seq, preview)`
  (ignored unless `seq === latestSeq`; fills `pattern` only while
  `!patternTouched`), `patternEdited`, `nameEdited`, `scopeToggled`,
  `saveFailed(message)`, `saveSucceeded`, `dismissed`. Plus a pure
  `canSave(state)`.
- `handleCategoryChange` dispatches `categoryEdited` **only after** the PATCH
  resolves successfully; a failed PATCH changes nothing.
- The panel renders **above the table** like `HeldImportPanel`, so
  `reload()`'s Loading swap and active filters (e.g. "uncategorized only",
  which hides the row just edited) can't unmount it.
- Panel contents: pattern input; display name (from `clean_description`,
  else the pattern); category read-only; scope toggle; preview line ("Would
  name N blank transactions, categorize K"); mismatch warning listing the
  sample rows; conflict warning naming the rule and its id, suggesting "This
  account only" only when the conflicting rule is global; one line noting
  future imports will use this rule ahead of the bank's own category.
- `canSave`: pattern and name non-blank; latest preview is for the current
  pattern and scope; `matches_source`; no conflict; `category_mismatch_count
  === 0`; not already saved. A refusal from save shows the server's
  `message`. Success shows "Rule saved" and reloads the table.

## 6. Non-goals

- Rules management screen (list/edit). Deleting needs the API.
- Changing rule precedence. Consequence: correcting a row that an existing
  rule mis-categorized cannot be turned into a rule here - the panel names
  the conflicting rule and its id; fix that rule via delete + recreate.
- Reverting rows when a rule is deleted.
- Learning from description renames - only category edits open the panel.
- Re-categorizing rows that already have a category.
- LLM-suggested patterns or categories.
- Component tests (no React testing library in the repo); panel placement
  and wiring are proven by the live walkthrough, transitions by the reducer
  tests.

## 7. Phases

1. **Backend** - `find_matching_rule` refactor, `suggest_match_pattern`,
   `normalize_rule_text`, `evaluate_candidate`, preview endpoint, create
   validation + guard, delete endpoint, startup order, tests. Live check
   against a server running on a DB copy.
2. **Frontend** - `rememberRule.ts` + vitest, panel, App wiring, live
   browser walkthrough on a DB copy.

## 8. Verification

Each item names the wrong implementation it must catch.

- `find_matching_rule`: rules passed out of id order (dropped sort); account
  rule beats an older global rule; first match wins within a tier; an
  id-None candidate sorts last in its tier but ahead of global rules when
  account-scoped (wrong virtual key). Existing `apply_merchant_rules` tests
  pass unchanged.
- `suggest_match_pattern`: exact input -> output cases for every step:
  `AplPay`, `DES:`, `SQ *7-ELEVEN 1234`, `PM *`, `TST* `, `IC* `,
  `UBER   *TRIP` (spaces kept), `VZWRLSS*APOCC`, `#519`, `Confirmation#`,
  `MACYS  ROCKINGHAM PK`, first token with a digit, `AplPay SQ` fallback,
  `KFC ...` fallback. Plus: every case's result is a substring of its input
  (catches re-joined tokens; exact outputs catch `return description`).
- `evaluate_candidate`: NULL-clean row already won by an existing rule is
  not counted (naive counting); NULL-clean source is in `would_name_count`
  but not `would_categorize_count`; manually renamed row in another category
  counts as a mismatch, not a name, and appears in the sample; the same row
  counts nothing when an older rule wins; scope comes from the source row;
  non-matching pattern gives `matches_source` false and no conflict even
  when an existing rule matches the source; global candidate behind a global
  rule conflicts, account-scoped candidate behind a global rule does not;
  source category changed is refused; sample capped at 5, mismatches first.
- Endpoints: preview with null pattern returns the suggestion (not 422);
  preview leaves rule and transaction rows unchanged; preview 404 and 409;
  exact response fields for conflict (rule fields) and mismatch (count and
  sample); create rejects blank/whitespace pattern and name with and
  without a source; padded values are stored stripped; `account_id` with a
  source is 422 and the stored account is the derived one; each refusal
  code in the stated order; unchanged behavior without a source; delete
  204/404 with filled rows intact.
- Startup: a blank row matched by both a merchant rule and a category rule
  gets the merchant rule's category after startup (fails with the old
  order).
- Frontend vitest (`rememberRule.test.ts`): `canSave` true for the all-good
  state and false for each single failing condition, including nonzero
  mismatches and a stale preview; stale-seq response ignored; prefill
  doesn't overwrite typed text; null category closes the panel; editing
  another row replaces it; `saveFailed` shows the message.
- Live (DB copy): preview numbers against an independent raw-SQL oracle
  (`instr(lower(description), lower(:p)) > 0`, not `LIKE`, whose `_`/`%`
  are wildcards) for a pattern no existing rule competes with. Live data
  has 0 uncategorized rows, so `would_categorize_count` is proven by
  fixture, not live. Refusal cases live: conflict, mismatch (UBER),
  non-matching pattern, blank pattern.
- Opus + Codex review the implementation and run the tests.

## 9. Resolved questions (user, 2026-10-15)

1. **Over-broad pattern:** `category_mismatch_count > 0` **blocks Save**, in
   the panel and server-side. The user narrows the pattern instead.
2. **Clearing a rename stores NULL**, so the next rule save or restart lets
   an old rule re-name the row. Pre-existing, 0 rows affected today: **known
   issue, out of scope.**

## 10. Review log

- 2026-10-15 Opus spec review: 18 findings. Adopted: simulated counts (no
  invariant), contiguous-slice suggestion + `*`-prefix handling + min
  length, server-side blank validation, scope derived from source, 404 for
  missing source, mismatch count + sample, panel state in App above the
  table, preview sequencing + stale-save guard, `instr` oracle,
  out-of-order-id test, corrected section 1/3 facts. Accepted as non-goal:
  dead end when an existing rule mis-categorized the row (finding 10). User
  resolved 9.1 (block) and 9.2 (out of scope).
- 2026-10-15 Codex spec review on v2: 11 findings, all verified and
  adopted: source-category check (stale panel after re-edit), `account_id`
  rejected with a source, virtual sort key for the unsaved candidate,
  `matches_source` computed before conflict, exact index-based suggestion
  algorithm with exact-output tests, source-row and renamed-row fixtures,
  shared normalization, exact response assertions, zero-mismatch `canSave`
  cases, panel transitions moved into a tested reducer, startup order fix
  (4.5).
