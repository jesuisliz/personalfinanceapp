# LLD: Merchant Rules tab (list, search, delete)

Status: v2, 2026-10-15. Design approved by Liz; Codex spec review folded in (section 9). No code written.

## 1. Context

Merchant rules (`merchant_rules` table) give a transaction its clean name and,
if it has none yet, its category. There are 77 today. The remember-edit
feature (`lld_edit_creates_merchant_rule_claude.md`) adds more from the
Transactions tab, but the app has no screen to see them. Its only way to undo
is `DELETE /merchant-rules/{id}`, which the panel tells you to call by hand
(`RememberRulePanel.tsx:110`). The Amex autopay fix on 2026-10-15
(`lld_phase2_claude.md` section 16) also left global rule 53 in place, and it
no longer matches any row. Today the only way to notice a rule like that is SQL.

Decisions Liz made on 2026-10-15:
- A new top-level **Rules** tab (the 5th, after Planning).
- **List, search, delete** only. To change a rule, delete it and re-create it
  through a category edit. Editing in place is out of scope (section 7).
- Each rule shows **how many rows it wins today**.

### Does the app have this data?

Partly. Each rule's fields are stored. **Which rule filled a row is not
stored:** `transactions.clean_description` and `category_id` have no
provenance column. So the count is **the number of transactions whose
description currently has this rule as its highest-precedence match, whether
or not the row is already named**. It measures coverage (is this rule dead or
shadowed?), not what applying it would change, and not what it actually
filled. The UI says "matches N transactions". Deleting a rule must say that
rows it already filled keep their name and category (already true;
`delete_merchant_rule` docstring).

## 2. Data model

No new tables or columns. The count is computed on each request.

## 3. Backend

### 3.1 Count function

New `count_rule_wins(session) -> dict[int, int]` in
`backend/app/categories/apply.py`, next to `find_matching_rule`:

- Load all rules, and select only `(description, account_id)` from transactions.
- For each transaction, call `find_matching_rule(rules, description, account_id)`.
  The winning rule's id gets +1.
- Return `{rule_id: count}`, with every rule present (0 when it wins nothing).

It reuses `find_matching_rule` unchanged, so the count follows the same
precedence the importer uses: account-scoped first, then global, ascending id
within a tier, first substring match wins. A rule shadowed by an earlier one
shows 0, which is the point.

**Unlike `apply_merchant_rules`, it does not skip rows that already have a
`clean_description`.** Every row counts, per the definition in section 1.

Invariants: `Transaction.description` is non-null (`models.py`), and rule
text created through the API is stripped and non-blank (`RuleText`,
`schemas.py`). Real data has 0 blank patterns and 0 blank descriptions
(checked 2026-10-15), so blank legacy patterns are out of scope. An empty
description matches no valid rule (tested).

Cost: `find_matching_rule` filters and sorts both tiers on every call, so this
is more than 1,188 x 77 substring checks. It will be timed on the real DB
during Task 3. No pagination or caching while the data stays this small.

### 3.2 Endpoint

`GET /merchant-rules` (exists, no current caller in the frontend or tests)
changes its response to `list[MerchantRuleListItem]`:

```python
class MerchantRuleListItem(MerchantRuleOut):
    match_count: int
```

`MerchantRuleOut` stays as it is, because POST and the 409 conflict body use it.
Order stays ascending by id; the frontend sorts.

`DELETE /merchant-rules/{id}` is unchanged.

### 3.3 Chat tool

None. "What rules do I have" isn't a finance question, and the chatbot's tools
are read-only finance aggregates.

## 4. Frontend

### 4.1 Files

- `api.ts`: new type `MerchantRuleListItem = MerchantRule & { match_count: number }`
  (`MerchantRule` itself stays count-free: it's the POST result and the
  conflict shape). `fetchMerchantRules(): Promise<MerchantRuleListItem[]>` and
  `deleteMerchantRule(id): Promise<"deleted" | "already_deleted">`. Unlike
  `deleteGoal`/`deleteConversation`, which throw a generic error on any
  non-ok status, a 404 resolves to `"already_deleted"`. Any other non-ok
  status throws.
- `rules.ts` (pure, vitest-tested): `filterRules(rules, query, categoryNames,
  accountNames)` and `sortRules`.
  - Filter: case-insensitive substring (anywhere in the string, on both the
    query and the data) against the pattern, clean name, category label and
    scope label. A rule is kept if any field matches.
  - Labels (`ruleCategoryLabel`, `ruleScopeLabel`):
    - Category: `category_id` null gives "-"; an id with no category gives
      "Unknown category #N".
    - Scope: `account_id` null gives "All accounts"; an id with no account
      gives "Unknown account #N".
    - SQLite foreign keys are off, so orphans are possible even though real
      data has none. The fallback labels are searchable.
  - Sort: newest first (numeric id descending), because the rule you just
    made is the one you most likely want to check or undo. It returns a new
    array and doesn't mutate its input.
- `Rules.tsx`: the tab.
- `App.tsx`: add `{ key: "rules", label: "Rules", icon: ... }` to `TABS` and
  render `<Rules />`. Rules mounts only while its tab is open, and on each
  mount it fetches rules, accounts and categories together. App's own lists
  load once on mount and can go stale, since categories can be renamed via
  `PATCH /categories/{id}`.
- `icons.tsx`: one new icon if none of the existing ones fit.
- `RememberRulePanel.tsx`: change the undo text from the raw `DELETE` call to
  "To undo, delete rule #N on the Rules tab."

### 4.2 Rules tab layout

Card with a header: "Merchant rules (77)" and a search box.

Table columns:
- `#`
- Pattern
- Clean name
- Category: a dot from the existing `categoryDotColor(category.id)` plus the
  name. No dot for null or unknown categories.
- Scope
- Matches: a number, with 0 shown muted
- Delete action

Delete is a two-step inline confirm: "Delete" becomes "Delete rule #N?
Confirm / Cancel" in that row. This is a deliberate choice for this tab; the
app isn't consistent today (Chat uses `window.confirm`, Planning deletes
immediately). While the delete is in flight, that row's buttons are
disabled. After it, the list always re-fetches: on success, on
`"already_deleted"` (status line "Rule #N was already deleted"), and on an
error (status line with the message).

A note under the header says: "Deleting a rule stops it applying from now
on. Transactions it already named or categorized keep those values."
(Rules run at import, at app startup and right after a rule is created, not
only at import.)

The data re-loads every time the tab opens. Counts change when descriptions,
rules or imports change. Category edits don't affect matching.

States: loading, load error (with the message), "No rules yet", and
"No rules match <query>" while filtering.

## 5. Tests

Every assertion checks the complete count dictionary, not single keys.

Backend, in `backend/tests/test_categories.py` / `test_api.py`:

1. **Precedence across tiers, with overlapping different patterns and mixed
   case.**
   - A scoped `"amazon mktp"` beats a global `"AMAZON"` on its own account.
   - The global rule still wins the same description on another account.
   - A naive "every pattern that matches gets +1" counter fails this.
2. **Id order within a tier.** Insert the global rules higher-id first, so
   that an implementation relying on DB order or list order fails. Also call
   `find_matching_rule` directly with a shuffled rule list.
3. **A dead rule, plus one exact non-zero winner** in the same fixture. An
   all-zero implementation fails this. An empty description matches nothing.
4. **Already-named rows still count.**
   - Fixture: a matching named row, a matching unnamed row, and a non-match.
   - Expected count: 2.
   - Kills both "skip named rows" and "only count named rows".
5. **API test**, extending the existing delete test in `test_api.py`:
   - Two overlapping rules; assert exact `match_count`s and every response
     field, in id order.
   - Delete the winner; the shadowed rule's count goes up.
   - Transaction fields are unchanged, and a second delete returns 404.

Frontend (vitest):
- `rules.test.ts`:
  - Filter: a substring in the middle of each of the four fields, mixed case
    on both the query and the data, and OR across fields.
  - Labels: null and unknown for both category and scope, and the unknown
    labels are searchable.
  - Sort: ids 2 and 10 (numeric, not lexicographic), and the input is not
    mutated.
- `api.test.ts`:
  - `fetchMerchantRules` hits GET.
  - `deleteMerchantRule` sends DELETE.
  - 204 gives "deleted", 404 gives "already_deleted", 500 throws.
- The component's cancel/confirm/refetch flow has no component-test harness
  in this repo (vitest is used only for pure modules). It is covered by the
  live walkthrough.

For every test, name a wrong implementation that would still pass it (the
mutation-test rule) and kill any that survive.

## 6. Verification

- Full backend suite and vitest, with counts shown (315 -> N, 100 -> M);
  `tsc -b` + `oxlint` clean.
- **Independent oracle for the counts:** a standalone script using only
  `sqlite3` and its own reimplementation of the precedence (scoped tier,
  global tier, ascending id, first match). It must agree with the API on all
  77 rules. Spot-check by hand: rule 53 = 0, rule 77 = 2, rule 61 = 3 or
  however many Cash Rewards rows match it.
- **Live browser walkthrough on a DB copy**, served on :8000 because
  `API_BASE` is hardcoded:
  - The tab loads, and the count matches the oracle.
  - Search narrows the list.
  - Delete -> Cancel leaves the rule in place.
  - Delete -> Confirm removes it from the list, and raw SQL on the copy shows
    the transactions it had filled are unchanged.
  - Then the remember-edit panel's new undo text.
- Real data is never deleted during verification.
- Reviews: one fresh Opus subagent and Codex on the implementation, both
  running the tests.

## 7. Non-goals

- **Editing a rule in place.** It would need a rule for rows the old version
  already filled, plus the remember-edit conflict and category-mismatch
  checks. Delete-and-recreate covers it for now.
- **Clearing the rows a rule filled when it is deleted.** The app can't tell
  which rows a rule filled (no provenance, section 1). A guess would be wrong
  for rows that were edited by hand.
- **Creating rules from this tab.** Rules come from category edits, which
  carry the safety checks.
- **Bulk delete.** 77 rules, deleted one at a time when needed.
- **Recording provenance.** It would make "actually filled" countable, but
  needs a schema change and a backfill. Revisit only if "matches" proves
  misleading in use.

## 8. Plan (task breakdown)

One phase, three tasks, with a hard stop after each:
1. Backend: `count_rule_wins`, schema, endpoint, tests 1-5, mutation check.
2. Frontend: `api.ts` functions, `rules.ts` + vitest, `Rules.tsx`, App tab,
   panel text.
3. Oracle script, live walkthrough on a DB copy, Opus + Codex reviews, docs
   (HLD section 6, this LLD's results section, memory), commit and push.

## 9. Review log

**Codex spec review, 2026-10-15 (read-only, high effort), on v1.** 15
findings; every factual claim checked against the code before acting.
- Accepted and folded into v2:
  - 1 (High): the count's definition and wording.
  - 2-4: test strength, mutants named per test.
  - 5: Rules fetches its own accounts/categories.
  - 6: a 404 on delete resolves to "already deleted" and always re-fetches;
    row disabled while in flight.
  - 7: orphan labels.
  - 8: blank invariants (real data has 0 blank patterns/descriptions).
  - 9: separate list type.
  - 10: inline confirm is a choice, not an app convention (Chat uses
    `window.confirm`).
  - 11: rules also run at startup and on create.
  - 12: dropped the unmeasured timing claim; to be timed in Task 3.
  - 13: reuse `categoryDotColor`.
  - 15: confirmed GET has no current caller.
- Rejected: 14, which called the oracle, mutation testing and two
  implementation reviewers disproportionate. They are Liz's standing review
  rules for every change.
