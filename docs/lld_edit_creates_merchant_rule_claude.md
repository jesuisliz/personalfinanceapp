# LLD: Remember a manual category edit as a merchant rule

Status: v3 approved. Phase 1 (backend) built and live-verified 2026-10-15
(commits c7a6164, dcfb832, 3ca2280, 7a63e3c, i.e. 7b3e23f..7a63e3c; see section 11).
Close-out review and its fix pass done (11.4, 11.5; commit 78ff014). Phase 2
(frontend panel) built and live-verified 2026-10-15 (commits 1466f1a, 17a019f,
b442518, a5ff7f1; see section 12). Open: three questions for Liz (12.6).

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
  (now `find_matching_rule` in `apply.py`).
- It only touches rows whose `clean_description` is NULL, and only fills
  `category_id` when it is NULL. A non-null category is never overwritten.
  Caveat: a row the user deliberately set back to Uncategorized is
  indistinguishable from a never-categorized one, and a rule may fill it.
- It runs after every import (`pipeline.py`), at startup (the `main.py` lifespan)
  and after `POST /merchant-rules`. Rows with NULL `clean_description` are
  *usually* unmatched by every existing rule, but not guaranteed (clearing a
  rename in the UI stores NULL), so the preview simulates rather than
  assuming this (4.2).
- On import, merchant rules run before `CategoryRule`, so a new rule also
  outranks `raw_category` mapping for future rows on accounts that have it
  (Chase). The preview cannot show that; the panel says so in one line.
- Before this feature, startup ran them in the opposite order (category
  rules first, in the `main.py` lifespan), so a row both could match got a
  different category depending on whether it was filled at import or at
  startup. Fixed in 4.5.
- A rule assigning Transfers does not set `is_transfer`; the dashboard
  excludes the category regardless (`aggregates.py:35`). No interaction.
- Live DB 2026-10-15: 76 rules, 1188 rows, 0 uncategorized, 547 with NULL
  `clean_description`.


## 4. Backend

### 4.1 `app/categories/apply.py`

(As built, `suggest_match_pattern`, `normalize_rule_text` and
`evaluate_candidate` live in `app/categories/candidate.py`; see 11.1.)

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
  5. `pattern = description[start:end]`, stripped. If shorter than 4
     characters after stripping, return the whole original description,
     stripped (`AplPay SQ` -> `AplPay SQ`, never `SQ`; `AplPay   FOO 123`
     -> whole string, since `"  FOO"` strips to 3). A blank description
     gives `""`. (Stripping here, before the length check, was added in the
     11.4 fix pass; see 11.5.)
  The panel's preview and the mismatch block are the real guard; this only
  sets a sensible default.
- **`normalize_rule_text(value) -> str`** - strips whitespace; used by both
  the preview and create schemas so the pattern previewed is identical to
  the pattern stored. Blank after stripping is a 422.

### 4.2 `evaluate_candidate` + `POST /merchant-rules/preview`

One server function does all the checking, used by both preview and create:

`evaluate_candidate(session, source_txn, match_pattern, category_id, this_account_only)`

1. **Source category check** (as built: in the router's `load_source_row`,
   before `evaluate_candidate` is called; see 11.1). `source_txn.category_id` must equal
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
transaction doesn't exist; `source_category_changed` returns 409; a null
pattern on a blank description returns 422 `no_suggested_pattern`. Read-only.
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
  404 no such transaction; 409 `source_category_changed`; 400
  `category_not_found`, then (only when `this_account_only`) 400
  `account_not_found` - SQLite FKs are off, so the source row proves
  neither exists (added in the 11.4 fix pass); 400 pattern
  doesn't match the source; 409 `conflict` (detail includes the rule);
  409 `category_mismatch` (detail includes count and sample).
  Error detail is `{code, message, ...}` so the panel can show it.
- Without a source, behavior is unchanged apart from the validation.

### 4.4 `DELETE /merchant-rules/{id}`

204 on success, 404 if missing. Does not revert rows the rule already
filled; they stay editable in the table.

### 4.5 Startup order (`main.py`)

Swap to merchant rules first, then category rules, matching the import
pipeline (`pipeline.py`). As built, both paths call one shared
`apply_all_rules(session)` (see 11.1). Live effect today: none (0 uncategorized
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

## 11. Phase 1 implementation notes (2026-10-15)

### 11.1 Decisions made in the Phase 1 plan

1. **Module split:** `find_matching_rule` and `apply_all_rules` are in
   `apply.py` (they define how rules apply); `normalize_rule_text`,
   `suggest_match_pattern` and `evaluate_candidate` are in the new
   `candidate.py` (they only exist for this feature).
2. **`apply_all_rules(session)`** (merchant, then category) is called by
   both `pipeline.py` and the `main.py` lifespan, so one call site per path
   stops them drifting again. The order is pinned twice: a test on the shared
   function, and (added in the 11.4 fix pass) a test that runs the lifespan
   against an in-memory session with `init_db`/`get_session` monkeypatched.
3. **Source lookup and category check are in the router** (`load_source_row`,
   shared by preview and create) because they are HTTP refusals (404/409).
   `evaluate_candidate` takes an already-validated row.

### 11.2 Rulings made while building (where plan or spec was silent or wrong)

- Plan's Task 3 expected an account-scoped candidate to name 2 fixture rows.
  By this spec's precedence an account-scoped candidate also beats the older
  global `KURA OLD` rule, so it names 3 (1 categorized, 2 mismatches). Tests
  follow the spec.
- Create with `source_transaction_id` but no `category_id` is a 422: a rule
  remembered from a category edit is meaningless without the category.
- With a source, the source refusals run first and the old category/account
  existence 400s are skipped. **The stated reason was wrong** (both
  reviewers): SQLite foreign keys are OFF in this app, so the source's
  category equalling the request's does not prove the category exists. To be
  fixed in the 11.4 fix pass by keeping explicit lookups.
- A missing source returns `detail: {code: "source_not_found", message}`,
  matching the other refusals.
- Added a test pinning `conflict` before `category_mismatch`.

### 11.3 Results

- Tests: 233 -> 287 backend tests passing. Mutation checks run: old startup
  order, candidate sorted first in its tier, mismatch counted only over
  unnamed rows, conflict/mismatch order swapped - each fails at least one
  test.
- Suggestion over all 706 real distinct descriptions: 0 fail to match their
  own row; the only result under 4 characters is the whole description
  `Cmp`.
- Live, server on port 8001 against a DB copy (76 rules, 1188 rows):
  - Startup with the new rule order changed 0 rows compared with the real
    DB.
  - Preview for txn 971 `DD *DOORDASH` -> Dining & Drinks (suggested
    pattern, global) against a raw-SQL `instr` oracle: name 46, categorize 0,
    mismatch 0, sample ids [971, 973, 975, 978, 989] - all identical.
    Categorize is 0 because the live data has 0 uncategorized rows (proven
    by fixture, as section 8 planned).
  - Refusals: `UBER` from txn 81 -> 409 `category_mismatch`, count 30, sample
    identical to the oracle; `PAYMENT` from txn 813 -> 409 `conflict` naming
    rule 61 (account-scoped `PAYMENT - THANK YOU`); non-matching -> 400;
    blank -> 422; changed category -> 409 `source_category_changed`. Rule
    count unchanged after all refusals.
  - Save `DD *DOORDASH` -> exactly the 46 oracle rows changed, all named
    `DoorDash`, categories unchanged; delete -> 204, rows unchanged, second
    delete 404.
  - Teardown: server stopped, port free, copy deleted; real DB still 76
    rules, 1188 rows.

### 11.4 Close-out review (2026-10-15) - fix pass DONE (see 11.5)

Opus subagent ran the suite (287 passed; base 7b3e23f: 233) and mutation-
tested on `git archive` copies. Codex reviewed but could not run tests (its
sandbox had no writable temp dir). No code-correctness bug was found in the
counts, precedence or refusal order; findings are untested behaviors plus two
real code gaps. Next session: one fix pass, each fix a test that fails first
(or a mutant it kills), then full suite, then commit + push.

**Code fixes (verified against the code):**

1. Suggested pattern isn't normalized (Codex 1, Opus 10): preview with
   `match_pattern: null` uses `suggest_match_pattern` raw, so e.g.
   `AplPay  FOO` previews `" FOO"` but create stores `"FOO"`. Fix: run the
   suggestion through `normalize_rule_text` in the preview route. 0 real
   descriptions affected today.
2. Existence checks rely on FKs that are off (Codex 2, Opus 13): restore
   explicit Category (and, when scoped, Account) lookups on the source path.

**Missing tests to add:**

3. No-source create keeps `account_id` (mutant `account_id = None` survives)
   and `account_id: 999` -> 400 (Opus 1).
4. `would_categorize_count` only over named rows: add a candidate-won row
   with a name set and category NULL (Opus 2).
5. Conflict against an existing account-scoped rule on the source's account,
   for global and scoped candidates; also pins "unsaved candidate last in the
   account tier" (Opus 3, Codex 5).
6. A rule scoped to another account never wins (Codex 4).
7. 400 before `category_mismatch`: source 1 with `KURA TRAVEL` while a
   Travel row `SQ *KURA TRAVEL` exists (Opus 4).
8. Preview endpoint with `this_account_only=true` and with a nonzero mismatch
   (Opus 5, Codex 8).
9. Source category set back to NULL -> 409 `source_category_changed` (Opus 6).
10. Lifespan startup order: monkeypatch `app.main.init_db`/`get_session` to
    an in-memory session and run `lifespan(app)` (Opus 7, Codex 10); reword
    11.1 #2 ("only way" overstated).
11. Blank and padded pattern/name on create WITH a source (Opus 11, Codex 7).
12. Source on a non-1 account so scope isn't pinned to a constant (Codex 3).
13. Read-only: catch `commit`/`flush` in `evaluate_candidate` (Codex 6).
14. Error contract: assert `detail.message` on every refusal and 409 on
    conflict-before-mismatch; delete test checks row 3 too (Codex 9, 11).
15. Docs: section 3 / 4.5 cite pre-change line numbers (Opus 13).

**Deferred minors (not planned; plus Opus 7 from the second review, see 11.5):** preview request ignores extra
`account_id` instead of 422 (Opus 8); `this_account_only` without a source is
silently ignored (Opus 9); scope filter in `evaluate_candidate` is redundant
with precedence (Opus 12, equivalent mutant); tab-only text and
`matches_source` case-insensitivity have no dedicated test; sample tie-break
by date vs id where fixture ids track dates (Codex table).

**Question for Liz (Codex ruling verdict 3):** create-with-source requires a
`category_id` (422 otherwise). Codex calls this a product decision since it
blocks a name-only rule remembered from an edit. The panel only opens after a
category edit, so the executor's view is keep the 422; needs Liz's call.

**Liz's ruling (2026-10-15):** keep the 422. A rule remembered from an edit
always carries the edited category.

### 11.5 Fix pass results (2026-10-15)

Both code fixes were written test-first; each new test failed before the fix:

- Fix 1: the suggested pattern is stripped. Test `AplPay  BLUE BOTTLE`
  previewed `" BLUE BOTTLE"` before the fix. First built as
  `normalize_rule_text` in the preview route; moved into
  `suggest_match_pattern` after the second review (below) so the strip
  happens before the 4-character check.
- Fix 2: `check_rule_from_source` checks the category exists, and the
  source's account exists when `this_account_only`. Refusals are 400
  `category_not_found` / `account_not_found`, placed after the 404/409 source
  checks and before the pattern check. Before the fix both requests saved a
  rule (200) pointing at a nonexistent id. (The first category test failed
  for the wrong reason - a fixture row caused `category_mismatch` - and was
  rewritten to use a description nothing else matches.)

Items 3-14 are tests on behavior that already worked, so each was proven by
a named mutant applied to a scratch copy with the full suite run. All 18
were killed; for 10, the new test was the only failure:

| Item | Mutant | Killed by |
|---|---|---|
| 3 | no-source `account_id = None`; account 400 check removed | `..._without_source_keeps_account_id`, `..._unknown_account_returns_400` |
| 4 | `would_categorize_count` over all won rows | `test_evaluate_categorize_count_only_over_rows_it_names` |
| 5 | global tier first; unsaved candidate first in its tier | `..._conflicts_with_scoped_rule_on_source_account` |
| 6 | any scoped rule in the account tier | `test_evaluate_rule_scoped_to_another_account_never_wins` |
| 7 | mismatch checked before pattern | `..._pattern_not_matching_source_beats_category_mismatch` |
| 8 | preview ignores `this_account_only`; mismatch count zeroed | `test_rule_preview_this_account_only_with_mismatch` |
| 9 | NULL source category allowed | `..._source_category_cleared_returns_409` |
| 10 | lifespan applies category rules first | `test_startup_applies_merchant_rules_before_category_rules` |
| 11 | pattern / name not normalized | `..._from_source_stores_stripped_text`, `..._from_source_rejects_blank_text` |
| 12 | scope pinned to account 1 | `..._on_second_account_scopes_to_that_account` |
| 13 | `evaluate_candidate` commits | `test_evaluate_never_commits_or_flushes_changes` |
| 14 | blank `message` on three refusals | the 404/409/400 refusal tests |

Item 14's extra row-3 check in the delete test is coverage only (no
distinct mutant). Item 15 done: sections 3 and 4.5 cite symbols, not line
numbers.

**Second review (fresh Opus subagent + Codex, both ran the suite: 306
passed).** No bug in the two fixes. Findings, all verified against the code
and fixed:

- LLD 4.3 didn't list the new 400s (both). Fixed above.
- The new 400s' position wasn't pinned (Opus): moving them after the pattern
  check survived. Tests `..._unknown_category_beats_non_matching_pattern` /
  `..._unknown_account_beats_non_matching_pattern`.
- The account check being scoped-only wasn't pinned (Opus). Test
  `..._on_unknown_account_unscoped_is_allowed`.
- Startup test passed with category rules dropped from startup (both).
  Added a row only the category rule matches.
- Fix 1 test pinned only the response string; evaluating the raw pattern or
  `.lstrip()` survived (Opus). Now parametrized over a leading and a trailing
  cut (`BLUE BOTTLE  DES:X` cut `"BLUE BOTTLE "`) and asserts
  `would_name_count` with a row only the stripped pattern matches.
- The length check ran before stripping, so `AplPay   FOO 123` suggested
  `FOO` (3 chars), breaking 4.1's minimum (Opus). Fixed in
  `suggest_match_pattern`; table cases added, including `"  AB 12  "` for
  the stripped fallback (the first padded case didn't reach the fallback -
  caught when its mutant survived).
- A blank description made the null-pattern preview raise `ValueError`
  (500) (both; 0 blank descriptions in real data, but the Chase parser
  doesn't reject them). Now 422 `no_suggested_pattern`.
- Item 13 didn't literally catch `flush`: `before_flush` doesn't fire for a
  clean session, so an explicit `session.flush()` survived (Codex). The
  test now turns autoflush off and makes `flush` raise.

Each fix's mutant (new 400s after the pattern check, unconditional account
check, startup merchant-only, `.lstrip()`, unstripped cut, unstripped
fallback, blank not refused, explicit flush) was run on a scratch copy and
killed. Deferred: preview doesn't check the category exists (Opus 7; read-
only, and create refuses). Real data: 0 of 706 distinct descriptions change
suggestion. Suite: 315 passed (287 before the pass).


## 12. Phase 2 implementation notes (2026-10-15)

Plan: `docs/plan_edit_creates_merchant_rule_phase2_claude.md` (commit 61b0c90).
Commits: 1466f1a (API client), 17a019f (reducer), b442518 (panel + App
wiring), a5ff7f1 (review fixes). vitest 32 -> 100; backend unchanged, 315.

### 12.1 Decisions the plan added to section 5

1. Two actions beyond the section 5 list: `previewFailed(seq, message)` (a
   preview 409/422/network error needs a state, or the panel says
   "Checking..." forever) and `saveStarted` (disables Save while the create
   is in flight).
2. `saveSucceeded` / `saveFailed` apply only while `saving`, so a panel
   that replaced the saving one isn't stamped "Rule saved" by the old
   request.
3. `categoryEdited` with null closes the panel only when it is the panel's
   own row; an unrelated row set to Uncategorized leaves a valid panel
   open. **Liz approved this reading of "null closes" 2026-10-15.**
4. `categoryEdited` for the same row and same category keeps the state
   (`CategoryDropdown` fires `onChange` on a re-pick; resetting would
   discard a typed pattern).
5. `name: string | null`: null means not edited; `displayName` derives the
   default (`clean_description`, else the current pattern).
6. Preview staleness is guarded by (a) seq - a response applies only when
   `seq === latestSeq`; the counter lives in App (`useRef`), is never
   reset, and a new panel starts at `latestSeq: 0`; (b) `canSave` compares
   `preview.match_pattern` with the trimmed pattern; (c) the state records
   the scope the preview was computed for. **Amended by the review (12.4):**
   pattern and scope edits also reset `latestSeq` to 0 and clear `error`.
7. Previews are debounced 300 ms and keyed on the request body. While the
   pattern is untouched the body sends `match_pattern: null`, so prefilling
   from a response doesn't trigger a second request. A touched blank
   pattern sends nothing.
8. `refusalMessage(body, fallback)` reads a string `detail`, else
   `detail.message`, else the fallback (FastAPI's 422 detail is an array).
   The existing `asJson` would have shown `{code, message}` as
   `[object Object]`; it is left alone and used only by older calls.
9. The saved view shows the rule id and that undo is
   `DELETE /merchant-rules/{id}`, since no UI lists rules.

Also: no warning color token exists, so blocking statuses (pattern not in
description, conflict, mismatch) and mismatched sample rows use
`text-critical`.

### 12.2 Mutation checks while building

- Reducer (Task 2): the plan's 12 named mutants all killed after one test
  fix - "does not overwrite a pattern the user typed" typed exactly what the
  server echoed, so an always-overwrite mutant passed. It now types
  `"DOORDASH "` while the server returns the stripped `"DOORDASH"`.
- Known equivalent: dropping `pattern !== ""` from `canSave` (the server
  never returns an empty `match_pattern`).

### 12.3 Live walkthrough (server on port 8000 against a DB copy)

Setup: Vite already running on 5173 was reused. The backend read a
scratchpad copy, proven by a marker note on txn 1229 that came back through
the API (a fresh copy is identical to the real DB, so a rule count proves
nothing). Oracle: rule precedence re-implemented from sections 3 and 4.2 in
plain Python over raw SQLite (`instr(lower(..), lower(..)) > 0`), with no
app imports, computed before the browser was opened. Every check matched it.

| Check | Screen | Oracle |
|---|---|---|
| 971 re-pick Dining & Drinks | panel above table after the PATCH 200; pattern `DD *DOORDASH`; 46 / 0; sample 971, 973, 975, 978, 989; Save enabled; 1 preview request (`match_pattern: null`) | 46 / 0 / 0, same sample |
| Scope toggled | "Checking...", Save disabled, then 46; request had `this_account_only: true` | 46 (every DoorDash row is on account 1) |
| `GRUBHUB` | "doesn't appear" warning, Save disabled; typing 7 letters sent 1 request | - |
| Pattern cleared | "Enter a pattern", Save disabled, 0 requests | - |
| 81 replaces 971's panel | new panel, suggestion `UBER   *EATS`, 8 / 0 | 8 / 0 / 0 |
| 81 `UBER` | 30 mismatches; 5 red rows; Save disabled | 30, sample 1022, 1028, 1027, 31, 94 |
| 813 | conflict naming rule 61, "for this account only", no "Only for" hint | conflict 61 (account-scoped) |
| 1134 (extra) | conflict naming global rule 66 **with** the hint; scoped: no conflict, 0 / 0, Save enabled | conflict 66; scoped 0 / 0, sample 1134, 1126, 1120, 1119, 1112 |
| Filter regression: 971 -> Travel under a Dining filter | row left the table, panel stayed and previewed: 46 mismatches | 46 (45 unnamed rows + row 1, already named DoorDash) |
| Failed PATCH (backend stopped) | no panel, no preview request | - |
| Save 971 as "DoorDash" | "Rule saved (#77)", table reloaded | raw SQL: the 46 changed names are exactly the oracle's 46 ids; 0 category changes; rules 76 -> 77 |
| `DELETE /merchant-rules/77` | 204, then 404; 47 rows keep "DoorDash" | - |

Teardown: tab closed, backend stopped, port 8000 free, copy deleted; real
DB 76 rules, 1188 rows, max rule id 76, one row named DoorDash.

Seen, not changed: the sample list collapses runs of spaces (HTML; the
table does the same, and the pattern input keeps them). The first click on
a category dropdown right after typing in the search box doesn't open it -
existing `CategoryDropdown` behavior. A rejected PATCH is an unhandled
promise in the console (existing; this phase dispatches nothing for it).

### 12.4 Close-out reviews

Fresh Opus subagent and Codex (`codex exec`, high effort), each in its own
detached worktree, against 61b0c90..b442518. Both ran the suites (vitest 83,
backend 315, lint clean, build OK - Codex needed worktree workarounds, see
`C:\Projects\DEV_ENVIRONMENT_NOTES.md`). Neither found a path where the
client enables Save when the server would refuse, or relaxes a refusal.

Fixed (a5ff7f1), each verified against the code first:

- **In-flight preview lands after an edit** (Codex Medium; Opus D2 is the
  same root). `patternEdited` / `scopeToggled` cleared `preview` but not
  `latestSeq` or `error`. Clearing the pattern sends no new request, so the
  old response (or failure, or a save refusal) stayed on screen instead of
  "Enter a pattern". Now both reset `latestSeq` to 0 - no request uses 0 -
  and clear `error`. Re-run live with previews delayed 1.5 s in the browser:
  a `DOORDASH` request in flight when the pattern was cleared landed 1.7 s
  later with 200 and was ignored; the normal path still showed 46 / 0.
- **Uncategorized sample rows shown red** (Opus D1). Section 4.2 counts a
  mismatch only when the row has a category that differs; a null-category
  row is one the rule would fill. `isMismatch` moved into `rememberRule.ts`
  so it is tested.
- **Test gaps** (both). Surviving mutants, each re-run before acting:
  first request of a new panel null (M1); keep-as-is ignoring the row (M2);
  replacement carrying `savedRuleId` (M3) or scope/name/error (M4);
  `saveStarted` keeping the error (M5); prefill keyed on empty instead of
  untouched (M9); `canSave` refusing every account-scoped rule (M16);
  API rejecting only 409 (Codex). Tests added for each, plus the fix above.
  Final run: 25 mutants killed (these 8, the fix's own 5, the plan's 12),
  plus 2 for `isMismatch`; 1 known equivalent.

### 12.5 Deferred minors

- Panel status says "Would name N transactions"; section 5 says "N blank
  transactions". Named rows aren't counted (see 12.6 q3).
- If categories fail to load, the `Category {id}` fallback name would mark
  every sample row red.
- The panel's source snapshot doesn't follow a later rename of the same
  row, so the default name can go stale.
- `asJsonOrRefusal` parses JSON before checking `ok` (same as `asJson`).
- Preview doesn't check the category exists (from 11.5; create does).

### 12.6 Open questions for Liz

1. **Stale previews (Opus D3, Low).** A preview only re-runs when the
   pattern or scope changes. After a transient network error the only retry
   is editing the pattern; after other actions change the data (Detect
   Transfers, an upload, a rename) the counts shown can be stale. The server
   still refuses an unsafe save with its message. Options: re-preview after
   `saveFailed` and on each `reload()`, or leave it.
2. **Lost rule id (Opus D4, Low; the trade-off in decision 2).** A save
   still in flight when another row is edited creates the rule and reloads
   the table, but the id is discarded, and there is no rules UI to find it.
   Options: show the id in the status line, disable category dropdowns
   while saving, or leave it.
3. **Wording.** Change "Would name N transactions" to "Would name N unnamed
   transactions" to match section 5?
