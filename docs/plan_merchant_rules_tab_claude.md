# Merchant Rules Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Rules tab that lists every merchant rule with how many transactions
it wins today, filters them by text, and deletes one with an inline confirm.

**Architecture:**
- **Backend:** a pure count function next to `find_matching_rule` reuses that
  function unchanged. `GET /merchant-rules` adds the count to each rule.
- **Frontend:** a pure `rules.ts` module (labels, filter, sort) with vitest
  tests, two API helpers, and a `Rules.tsx` tab that loads its own data each
  time it opens.
- No schema change.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite + pytest (backend/venv);
React 19 + TypeScript + Vite + Tailwind v4 + vitest + oxlint (frontend).

**Spec:** `docs/lld_merchant_rules_tab_claude.md` (v2). Read it before any task.

## Global Constraints

- No schema change, no new table or column (spec section 2).
- `MerchantRuleOut` stays unchanged. The list uses a new `MerchantRuleListItem(MerchantRuleOut)` with `match_count: int` (section 3.2).
- `count_rule_wins` must call `find_matching_rule` unchanged and must NOT skip rows with a `clean_description` (section 3.1).
- Count definition, verbatim: "the number of transactions whose description currently has this rule as its highest-precedence match, whether or not the row is already named" (section 1).
- `DELETE /merchant-rules/{id}` is unchanged (section 3.2).
- UI copy, verbatim (spec section 4.2):
  - Header note: "Deleting a rule stops it applying from now on. Transactions it already named or categorized keep those values."
  - Confirm: "Delete rule #N?"
  - 404 status: "Rule #N was already deleted"
  - Empty states: "No rules yet" and "No rules match <query>"
  - Fallback labels: "-" for no category, "Unknown category #N", "All accounts", "Unknown account #N"
- Remember-edit panel undo text, verbatim: "To undo, delete rule #N on the Rules tab." (spec section 4.1)
- No browser `confirm()` / `alert()` on this tab.
- No emojis in code or output.
- `API_BASE` is hardcoded to `http://localhost:8000`.
- Never delete a rule in the real `backend/finance.db` during verification. Use a DB copy.
- Run test passes serially (two runs sharing a temp dir produce phantom failures).
- Don't revert uncommitted changes outside a task's file list.

## Review Focus

1. **A search query with regex-special characters**, such as `sq *k` or `acct#`. It must be treated as plain text and match literally. Test in Task 2 `rules.test.ts`.
2. **A search query that is only whitespace.** It must show every rule, not "No rules match". Test in Task 2.
3. **A double click on Confirm.** It must send only one DELETE, so the status never says "already deleted" for a delete you just made. The row's buttons are disabled while the delete is in flight. Live check in Task 3, step 3.
4. **Leaving the tab and coming back after a category edit or import.** Counts and labels must be fresh, because the tab remounts and re-fetches. Live check in Task 3, step 3.
5. **Deleting while a filter is active.** The query stays, the list re-fetches, and the deleted rule disappears from the filtered view. Live check in Task 3, step 3.

Ledger for execution: `.superpowers/sdd/plan_merchant_rules_tab_claude/progress.md`.
Hard stop after every task.

---

### Task 1: Backend count + list endpoint

**Files:**
- Modify: `backend/app/categories/apply.py` (add `count_rule_wins` after `find_matching_rule`)
- Modify: `backend/app/schemas.py` (add `MerchantRuleListItem` after `MerchantRuleOut`)
- Modify: `backend/app/routers/merchant_rules.py` (`list_merchant_rules`)
- Test: `backend/tests/test_categories.py`, `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `find_matching_rule(rules, description: str, account_id: int) -> MerchantRule | None` (existing).
- Produces:
  - `count_rule_wins(session: Session) -> dict[int, int]`
  - `MerchantRuleListItem` (fields: `id`, `match_pattern`, `clean_name`, `category_id`, `account_id`, `match_count`)
  - `GET /merchant-rules -> list[MerchantRuleListItem]`, ascending id

- [ ] **Step 1: Write the failing unit tests** at the end of `backend/tests/test_categories.py`. Add `count_rule_wins, find_matching_rule` to the existing `from app.categories.apply import ...` line.

```python
# --- count_rule_wins (docs/lld_merchant_rules_tab_claude.md) ---


def add_described_txn(session, account_id, description, clean=None):
    global _hash_counter
    _hash_counter += 1
    session.add(
        Transaction(
            account_id=account_id,
            date=date(2026, 7, 1),
            description=description,
            amount_cents=-1000,
            clean_description=clean,
            source_row_hash=f"hash-{_hash_counter}",
        )
    )
    session.commit()


def test_count_rule_wins_scoped_rule_beats_overlapping_global_rule_on_its_own_account():
    """A naive 'every matching pattern gets +1' counter gives global 3; a
    case-sensitive matcher gives scoped 0."""
    session = make_session()
    card_a = make_account(session, name="Card A")
    card_b = make_account(session, name="Card B")
    global_rule = MerchantRule(match_pattern="AMAZON", clean_name="Amazon")
    scoped_rule = MerchantRule(match_pattern="amazon mktp", clean_name="Amazon Marketplace", account_id=card_a.id)
    session.add_all([global_rule, scoped_rule])
    session.commit()
    add_described_txn(session, card_a.id, "AMAZON MKTP US*1A2B")
    add_described_txn(session, card_b.id, "AMAZON MKTP US*3C4D")
    add_described_txn(session, card_a.id, "Amazon.com*5E6F")

    assert count_rule_wins(session) == {global_rule.id: 2, scoped_rule.id: 1}


def test_count_rule_wins_lower_id_wins_within_a_tier_even_when_inserted_later():
    session = make_session()
    account = make_account(session)
    session.add(MerchantRule(id=20, match_pattern="STARBUCKS", clean_name="Starbucks"))
    session.commit()
    session.add(MerchantRule(id=10, match_pattern="STAR", clean_name="Star"))
    session.commit()
    add_described_txn(session, account.id, "STARBUCKS #1234")

    assert count_rule_wins(session) == {10: 1, 20: 0}


def test_find_matching_rule_ignores_caller_order_within_a_tier():
    """count_rule_wins inherits precedence from find_matching_rule; this pins it
    against list order, which a DB-backed test can't (SQLite returns id order)."""
    high = MerchantRule(id=20, match_pattern="STARBUCKS", clean_name="Starbucks")
    low = MerchantRule(id=10, match_pattern="STAR", clean_name="Star")

    assert find_matching_rule([high, low], "STARBUCKS #1234", account_id=1) is low


def test_count_rule_wins_reports_dead_rules_as_zero_next_to_an_exact_winner():
    session = make_session()
    account = make_account(session)
    dead = MerchantRule(match_pattern="NETFLIX", clean_name="Netflix")
    live = MerchantRule(match_pattern="SPOTIFY", clean_name="Spotify")
    session.add_all([dead, live])
    session.commit()
    add_described_txn(session, account.id, "SPOTIFY USA")
    add_described_txn(session, account.id, "")
    add_described_txn(session, account.id, "HULU")

    assert count_rule_wins(session) == {dead.id: 0, live.id: 1}


def test_count_rule_wins_counts_rows_that_are_already_named():
    """Kills both 'skip named rows' (gives 1) and 'only named rows' (gives 1)."""
    session = make_session()
    account = make_account(session)
    rule = MerchantRule(match_pattern="KURA", clean_name="Kura Sushi")
    session.add(rule)
    session.commit()
    add_described_txn(session, account.id, "SQ *KURA 1", clean="Kura Sushi")
    add_described_txn(session, account.id, "SQ *KURA 2")
    add_described_txn(session, account.id, "OTHER PLACE")

    assert count_rule_wins(session) == {rule.id: 2}


def test_count_rule_wins_with_no_rules_is_empty():
    session = make_session()
    account = make_account(session)
    add_described_txn(session, account.id, "ANYTHING")

    assert count_rule_wins(session) == {}
```

- [ ] **Step 2: Write the failing API test** in `backend/tests/test_api.py`, directly after `test_delete_rule_keeps_rows_it_filled`.

```python
def test_list_rules_reports_match_counts_and_delete_unshadows_the_next_rule():
    """Rows 1-3 all contain "KURA"; only rows 1 and 2 contain the longer pattern,
    which is shadowed by the lower-id global rule until that rule is deleted."""
    client, Session = make_rule_client()
    broad = add_existing_rule(Session, "KURA", DINING)
    narrow = add_existing_rule(Session, "SQ *KURA REVOLVING SUSHI", TRAVEL)

    before = client.get("/merchant-rules")

    assert before.status_code == 200
    assert before.json() == [
        {"id": broad, "match_pattern": "KURA", "clean_name": "Existing", "category_id": DINING,
         "account_id": None, "match_count": 3},
        {"id": narrow, "match_pattern": "SQ *KURA REVOLVING SUSHI", "clean_name": "Existing",
         "category_id": TRAVEL, "account_id": None, "match_count": 0},
    ]

    rows_before = [(r.clean_description, r.category_id) for r in (get_row(Session, i) for i in (1, 2, 3))]
    assert client.delete(f"/merchant-rules/{broad}").status_code == 204

    after = client.get("/merchant-rules").json()
    assert [(r["id"], r["match_count"]) for r in after] == [(narrow, 2)]
    rows_after = [(r.clean_description, r.category_id) for r in (get_row(Session, i) for i in (1, 2, 3))]
    assert rows_after == rows_before
    assert client.delete(f"/merchant-rules/{broad}").status_code == 404


def test_list_rules_with_no_rules_is_empty_list():
    client, _ = make_rule_client()

    resp = client.get("/merchant-rules")

    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run (from `backend/`): `venv/Scripts/python.exe -m pytest tests/test_categories.py tests/test_api.py -k "count_rule_wins or find_matching_rule_ignores or list_rules" -v`
Expected:
- `test_categories.py` fails to collect with `ImportError: cannot import name 'count_rule_wins'`.
- `test_find_matching_rule_ignores_caller_order_within_a_tier` would pass on its own, since it pins existing behavior. That's expected.
- The API tests fail with a `KeyError` / mismatch on `match_count`.

- [ ] **Step 4: Implement `count_rule_wins`** in `backend/app/categories/apply.py`, directly after `find_matching_rule`.

```python
def count_rule_wins(session: Session) -> dict[int, int]:
    """How many transactions each rule wins today, keyed by rule id.

    A rule wins a transaction when find_matching_rule picks it for that row's
    description and account, whether or not the row is already named - so this
    measures coverage (dead or shadowed rules show 0), not what applying the
    rules would change. Every rule is present.
    """
    rules = session.execute(select(MerchantRule)).scalars().all()
    counts = {rule.id: 0 for rule in rules}
    rows = session.execute(select(Transaction.description, Transaction.account_id)).all()
    for description, account_id in rows:
        rule = find_matching_rule(rules, description, account_id)
        if rule is not None:
            counts[rule.id] += 1
    return counts
```

- [ ] **Step 5: Add the schema** in `backend/app/schemas.py`, directly after `class MerchantRuleOut`.

```python
class MerchantRuleListItem(MerchantRuleOut):
    """A rule as the Rules tab lists it: how many transactions it wins today."""

    match_count: int
```

- [ ] **Step 6: Update the endpoint** in `backend/app/routers/merchant_rules.py`.
  - Add `count_rule_wins` to the `from app.categories.apply import ...` line.
  - Add `MerchantRuleListItem` to the schemas import.
  - Replace `list_merchant_rules` with:

```python
@router.get("/merchant-rules", response_model=list[MerchantRuleListItem])
def list_merchant_rules(db: Session = Depends(get_db)):
    counts = count_rule_wins(db)
    rules = db.execute(select(MerchantRule).order_by(MerchantRule.id)).scalars().all()
    return [
        MerchantRuleListItem(**MerchantRuleOut.model_validate(rule).model_dump(), match_count=counts[rule.id])
        for rule in rules
    ]
```

- [ ] **Step 7: Run the new tests, then the full suite**

Run: `venv/Scripts/python.exe -m pytest tests/test_categories.py tests/test_api.py -k "count_rule_wins or find_matching_rule_ignores or list_rules" -v`
Expected: 8 passed.
Run: `venv/Scripts/python.exe -m pytest -q`
Expected: 323 passed (315 + 8).

- [ ] **Step 8: Mutation check.** On a scratch copy of `apply.py`, never committed, apply each mutant, run the 8 tests, and confirm at least one fails. Restore after each.
  1. Replace the `find_matching_rule` call with "every rule whose pattern is a substring gets +1" (`for r in rules: if r.match_pattern.lower() in description.lower(): counts[r.id] += 1`).
  2. Make the matching case-sensitive (drop the `.lower()` calls, in a local copy of the loop).
  3. Skip rows with a `clean_description`: select it and `continue` when it's set.
  4. Count only named rows.
  5. Return `{}` (missing zeros).
  6. Always return zeros.
  7. In the endpoint, return `match_count=0`.

  Record each mutant and the test that killed it in the ledger.

- [ ] **Step 9: Commit**

```bash
git add backend/app/categories/apply.py backend/app/schemas.py backend/app/routers/merchant_rules.py backend/tests/test_categories.py backend/tests/test_api.py
git commit -m "Count each merchant rule's matches in GET /merchant-rules"
```

HARD STOP. Write the ledger line and report to Liz.

---

### Task 2: Frontend API helpers, `rules.ts`, Rules tab, panel text

**Files:**
- Modify: `frontend/src/api.ts` (type + `fetchMerchantRules` + `deleteMerchantRule`, placed after `createRuleFromEdit`)
- Create: `frontend/src/rules.ts`
- Create: `frontend/src/rules.test.ts`
- Modify: `frontend/src/api.test.ts`
- Create: `frontend/src/Rules.tsx`
- Modify: `frontend/src/App.tsx` (import, `TABS`, render)
- Modify: `frontend/src/RememberRulePanel.tsx:110-111` (undo text)

**Interfaces:**
- Consumes: `GET /merchant-rules -> MerchantRuleListItem[]` (Task 1), `DELETE /merchant-rules/{id}` (204 / 404).
- Produces:
  - `type MerchantRuleListItem = MerchantRule & { match_count: number }`
  - `fetchMerchantRules(): Promise<MerchantRuleListItem[]>`
  - `deleteMerchantRule(id: number): Promise<"deleted" | "already_deleted">`
  - `ruleCategoryLabel(rule: MerchantRule, categories: Category[]): string`
  - `ruleScopeLabel(rule: MerchantRule, accounts: Account[]): string`
  - `filterRules(rules: MerchantRuleListItem[], query: string, categories: Category[], accounts: Account[]): MerchantRuleListItem[]`
  - `sortRulesNewestFirst(rules: MerchantRuleListItem[]): MerchantRuleListItem[]`
  - default export `Rules` (no props).

  The spec's working names `filterRules(rules, query, categoryNames, accountNames)` and `sortRules` were refined to these signatures. The labels need the full lists to tell "unknown" apart from "none".

- [ ] **Step 1: Write the failing `rules.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import type { Account, Category, MerchantRuleListItem } from "./api";
import { filterRules, ruleCategoryLabel, ruleScopeLabel, sortRulesNewestFirst } from "./rules";

const categories: Category[] = [{ id: 4, name: "Dining Out", parent_id: null }];
const accounts: Account[] = [{ id: 8, name: "American Express", institution: "American Express", account_type: "credit_card" }];

function rule(overrides: Partial<MerchantRuleListItem>): MerchantRuleListItem {
  return { id: 1, match_pattern: "PATTERN", clean_name: "Name", category_id: null, account_id: null, match_count: 0, ...overrides };
}

const kura = rule({ id: 2, match_pattern: "SQ *KURA", clean_name: "Kura Sushi", category_id: 4 });
const amex = rule({ id: 10, match_pattern: "AUTOPAY PMT", clean_name: "Card Payment", account_id: 8 });
const orphan = rule({ id: 3, match_pattern: "OLD", clean_name: "Old", category_id: 99, account_id: 42 });
const all = [kura, amex, orphan];

describe("rule labels", () => {
  it("names a known category, '-' for none, and the id for an unknown one", () => {
    expect(ruleCategoryLabel(kura, categories)).toBe("Dining Out");
    expect(ruleCategoryLabel(amex, categories)).toBe("-");
    expect(ruleCategoryLabel(orphan, categories)).toBe("Unknown category #99");
  });

  it("names the account, 'All accounts' for a global rule, and the id for an unknown one", () => {
    expect(ruleScopeLabel(amex, accounts)).toBe("American Express");
    expect(ruleScopeLabel(kura, accounts)).toBe("All accounts");
    expect(ruleScopeLabel(orphan, accounts)).toBe("Unknown account #42");
  });
});

describe("filterRules", () => {
  const ids = (query: string) => filterRules(all, query, categories, accounts).map((r) => r.id);

  it.each([
    ["pattern, mid-string, mixed-case query", "oPAY p", [10]],
    ["clean name, mid-string", "rd paym", [10]],
    ["clean name, mid-string", "SUSH", [2]],
    ["category label, mid-string", "ning ou", [2]],
    ["scope label, mid-string", "xpress", [10]],
    ["'All accounts' label", "all acc", [2]],
    ["unknown category label", "unknown category", [3]],
    ["unknown account label", "account #42", [3]],
    ["regex characters taken literally", "sq *k", [2]],
  ])("matches on %s", (_label, query, expected) => {
    expect(ids(query as string)).toEqual(expected);
  });

  it("returns every rule for an empty or whitespace-only query", () => {
    expect(ids("")).toEqual([2, 10, 3]);
    expect(ids("   ")).toEqual([2, 10, 3]);
  });

  it("returns nothing when no field matches", () => {
    expect(ids("zzz")).toEqual([]);
  });
});

describe("sortRulesNewestFirst", () => {
  it("sorts by numeric id, highest first, without mutating the input", () => {
    const input = [kura, amex, orphan];
    expect(sortRulesNewestFirst(input).map((r) => r.id)).toEqual([10, 3, 2]);
    expect(input.map((r) => r.id)).toEqual([2, 10, 3]);
  });
});
```

Fixture design: each query appears in exactly one field of exactly one rule, so dropping any field from the filter fails its row. "xpress" matches amex only through its scope label, because its clean name is "Card Payment". Each field matching on its own proves OR semantics: an AND across fields fails every row. Data is mixed case ("Kura Sushi", "Dining Out"), so lowercasing only the query fails "SUSH" and "ning ou". Re-check every expectation by hand against the four labels when implementing. If one is wrong, fix the fixture, not the code.

- [ ] **Step 2: Add the failing api tests** to `frontend/src/api.test.ts`. Add `deleteMerchantRule, fetchMerchantRules` to the import from `./api`, and append:

```ts
describe("merchant rules", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetchMerchantRules GETs /merchant-rules and returns the list", async () => {
    const rows = [{ id: 1, match_pattern: "X", clean_name: "X", category_id: null, account_id: null, match_count: 2 }];
    const fetchMock = stubFetch(rows);

    const result = await fetchMerchantRules();

    expect(requestedUrl(fetchMock).pathname).toBe("/merchant-rules");
    expect(fetchMock.mock.calls[0][1]).toBeUndefined();
    expect(result).toEqual(rows);
  });

  it("deleteMerchantRule sends DELETE and reports a 204 as deleted", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 });
    vi.stubGlobal("fetch", fetchMock);

    expect(await deleteMerchantRule(53)).toBe("deleted");
    expect(requestedUrl(fetchMock).pathname).toBe("/merchant-rules/53");
    expect(fetchMock.mock.calls[0][1]).toEqual({ method: "DELETE" });
  });

  it("deleteMerchantRule reports a 404 as already deleted", async () => {
    stubFetchError(404, { detail: "Merchant rule 53 not found" });

    expect(await deleteMerchantRule(53)).toBe("already_deleted");
  });

  it("deleteMerchantRule throws on any other error status", async () => {
    stubFetchError(500, {});

    await expect(deleteMerchantRule(53)).rejects.toThrow("Deleting rule #53 failed (500)");
  });
});
```

- [ ] **Step 3: Run to verify failure**

Run (from `frontend/`): `npx vitest run src/rules.test.ts src/api.test.ts`
Expected: FAIL. The `./rules` module isn't found, and `fetchMerchantRules` / `deleteMerchantRule` aren't exported.

- [ ] **Step 4: Implement the API helpers** in `frontend/src/api.ts`, directly after `createRuleFromEdit`:

```ts
export type MerchantRuleListItem = MerchantRule & { match_count: number };

export async function fetchMerchantRules(): Promise<MerchantRuleListItem[]> {
  const res = await fetch(`${API_BASE}/merchant-rules`);
  if (!res.ok) throw new Error("Failed to load rules");
  return res.json();
}

/** Delete a rule. A 404 means it was already gone, which isn't an error for the Rules tab. */
export async function deleteMerchantRule(id: number): Promise<"deleted" | "already_deleted"> {
  const res = await fetch(`${API_BASE}/merchant-rules/${id}`, { method: "DELETE" });
  if (res.status === 404) return "already_deleted";
  if (!res.ok) throw new Error(`Deleting rule #${id} failed (${res.status})`);
  return "deleted";
}
```

- [ ] **Step 5: Implement `frontend/src/rules.ts`**

```ts
import type { Account, Category, MerchantRule, MerchantRuleListItem } from "./api";

/** The rule's category name, "-" when it sets none, or the id when the category no longer exists. */
export function ruleCategoryLabel(rule: MerchantRule, categories: Category[]): string {
  if (rule.category_id === null) return "-";
  return categories.find((c) => c.id === rule.category_id)?.name ?? `Unknown category #${rule.category_id}`;
}

/** "All accounts" for a global rule, else the account name, or the id when the account no longer exists. */
export function ruleScopeLabel(rule: MerchantRule, accounts: Account[]): string {
  if (rule.account_id === null) return "All accounts";
  return accounts.find((a) => a.id === rule.account_id)?.name ?? `Unknown account #${rule.account_id}`;
}

/** Rules where any of pattern, clean name, category label or scope label contains the query (plain text, any case). */
export function filterRules(
  rules: MerchantRuleListItem[],
  query: string,
  categories: Category[],
  accounts: Account[]
): MerchantRuleListItem[] {
  const needle = query.trim().toLowerCase();
  if (needle === "") return rules;
  return rules.filter((rule) =>
    [rule.match_pattern, rule.clean_name, ruleCategoryLabel(rule, categories), ruleScopeLabel(rule, accounts)].some(
      (field) => field.toLowerCase().includes(needle)
    )
  );
}

/** A new array, highest id first: the rule just created is the one most likely to need checking. */
export function sortRulesNewestFirst(rules: MerchantRuleListItem[]): MerchantRuleListItem[] {
  return [...rules].sort((a, b) => b.id - a.id);
}
```

- [ ] **Step 6: Run the tests**

Run: `npx vitest run src/rules.test.ts src/api.test.ts`
Expected: all pass.

- [ ] **Step 7: Create `frontend/src/Rules.tsx`**

```tsx
import { useEffect, useState } from "react";
import {
  deleteMerchantRule,
  fetchAccounts,
  fetchCategories,
  fetchMerchantRules,
  type Account,
  type Category,
  type MerchantRuleListItem,
} from "./api";
import { categoryDotColor } from "./categoryColor";
import { filterRules, ruleCategoryLabel, ruleScopeLabel, sortRulesNewestFirst } from "./rules";
import { Card, SecondaryButton, inputClass } from "./ui";

/** Every merchant rule, with how many transactions it wins today; delete one with an inline confirm. */
export default function Rules() {
  const [rules, setRules] = useState<MerchantRuleListItem[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [confirmingId, setConfirmingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  function load() {
    setLoading(true);
    setLoadError(null);
    return Promise.all([fetchMerchantRules(), fetchAccounts(), fetchCategories()])
      .then(([rulesResult, accountsResult, categoriesResult]) => {
        setRules(rulesResult);
        setAccounts(accountsResult);
        setCategories(categoriesResult);
      })
      .catch((e: Error) => setLoadError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  async function handleDelete(id: number) {
    setDeletingId(id);
    setStatus(null);
    try {
      const outcome = await deleteMerchantRule(id);
      setStatus(outcome === "deleted" ? `Deleted rule #${id}.` : `Rule #${id} was already deleted.`);
    } catch (e) {
      setStatus((e as Error).message);
    } finally {
      setDeletingId(null);
      setConfirmingId(null);
      await load();
    }
  }

  const visible = sortRulesNewestFirst(filterRules(rules, query, categories, accounts));

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
        <h2 className="font-semibold text-ink">Merchant rules ({rules.length})</h2>
        <input
          className={`${inputClass} w-64`}
          placeholder="Search rules"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <p className="text-sm text-ink-muted mb-3">
        Deleting a rule stops it applying from now on. Transactions it already named or categorized keep those values.
      </p>
      {status && <p className="text-sm text-ink-secondary mb-3">{status}</p>}

      {loadError ? (
        <p className="text-sm text-critical">{loadError}</p>
      ) : loading && rules.length === 0 ? (
        <p className="text-sm text-ink-muted">Loading...</p>
      ) : rules.length === 0 ? (
        <p className="text-sm text-ink-muted">No rules yet</p>
      ) : visible.length === 0 ? (
        <p className="text-sm text-ink-muted">No rules match {query.trim()}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-ink-muted border-b border-hairline">
              <tr>
                <th className="py-2 pr-3 font-medium">#</th>
                <th className="py-2 pr-3 font-medium">Pattern</th>
                <th className="py-2 pr-3 font-medium">Clean name</th>
                <th className="py-2 pr-3 font-medium">Category</th>
                <th className="py-2 pr-3 font-medium">Scope</th>
                <th className="py-2 pr-3 font-medium text-right">Matches</th>
                <th className="py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {visible.map((rule) => {
                const knownCategory = categories.some((c) => c.id === rule.category_id);
                const busy = deletingId === rule.id;
                return (
                  <tr key={rule.id} className="border-b border-hairline last:border-0">
                    <td className="py-2 pr-3 text-ink-muted">{rule.id}</td>
                    <td className="py-2 pr-3 font-mono text-xs text-ink">{rule.match_pattern}</td>
                    <td className="py-2 pr-3 text-ink">{rule.clean_name}</td>
                    <td className="py-2 pr-3 text-ink-secondary">
                      <span className="inline-flex items-center gap-1.5">
                        {knownCategory && rule.category_id !== null && (
                          <span
                            className="inline-block h-2 w-2 rounded-full"
                            style={{ backgroundColor: categoryDotColor(rule.category_id) }}
                          />
                        )}
                        {ruleCategoryLabel(rule, categories)}
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-ink-secondary">{ruleScopeLabel(rule, accounts)}</td>
                    <td className={`py-2 pr-3 text-right ${rule.match_count === 0 ? "text-ink-muted" : "text-ink"}`}>
                      {rule.match_count}
                    </td>
                    <td className="py-2 text-right whitespace-nowrap">
                      {confirmingId === rule.id ? (
                        <span className="inline-flex items-center gap-2">
                          <span className="text-ink-secondary">Delete rule #{rule.id}?</span>
                          <SecondaryButton disabled={busy} onClick={() => handleDelete(rule.id)}>
                            Confirm
                          </SecondaryButton>
                          <SecondaryButton disabled={busy} onClick={() => setConfirmingId(null)}>
                            Cancel
                          </SecondaryButton>
                        </span>
                      ) : (
                        <button
                          className="text-xs text-critical hover:underline disabled:opacity-40"
                          disabled={deletingId !== null}
                          onClick={() => setConfirmingId(rule.id)}
                        >
                          Delete
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
```

The double-click guard (Review Focus 3): React re-renders with `busy` before a second click can land on an enabled button. Task 3 checks this live. If a second DELETE is observed, add a `useRef` in-flight guard.

- [ ] **Step 8: Wire the tab** in `frontend/src/App.tsx`:
  - Add `import Rules from "./Rules";` next to `import Planning from "./Planning";`.
  - Add `IconTag` to the existing `./icons` import.
  - Add `{ key: "rules", label: "Rules", icon: IconTag },` after the planning entry in `TABS`.
  - Add `{view === "rules" && <Rules />}` after `{view === "planning" && <Planning />}`.

- [ ] **Step 9: Update the panel text** in `frontend/src/RememberRulePanel.tsx`. Replace lines 110-111:

```tsx
            Rule saved (#{state.savedRuleId}). Matching transactions without a name were updated. To undo, delete rule
            #{state.savedRuleId} on the Rules tab.
```

Check whether any vitest asserts the old `DELETE /merchant-rules` text: `grep -rn "DELETE /merchant-rules" frontend/src`. Update any hits.

- [ ] **Step 10: Full frontend checks**

Run (from `frontend/`): `npx vitest run`, then `npx tsc -b`, then `npx oxlint`.
Expected:
- vitest 100 -> 118 passed. The new tests are 14 rule tests (2 label, 9 `it.each` rows, 2 filter, 1 sort) plus 4 api tests; recount from the output and record the real number.
- `tsc -b` exits 0.
- `oxlint` reports 0 errors.

- [ ] **Step 11: Mutation check** on scratch edits, restoring after each. Confirm a test fails for each:
  1. The filter uses `startsWith`.
  2. The filter lowercases only the query.
  3. The filter drops the scope field.
  4. The filter drops the category field.
  5. No trim.
  6. Sort with `String(b.id).localeCompare(String(a.id))`.
  7. Sort in place (`rules.sort`).
  8. A 404 throws.
  9. A 404 returns "deleted".
  10. Unknown category returns "-".
  11. Unknown account returns "All accounts".
  12. `new RegExp(needle)` matching.

  Record the results in the ledger.

- [ ] **Step 12: Commit**

```bash
git add frontend/src/api.ts frontend/src/api.test.ts frontend/src/rules.ts frontend/src/rules.test.ts frontend/src/Rules.tsx frontend/src/App.tsx frontend/src/RememberRulePanel.tsx
git commit -m "Add Rules tab: list, search and delete merchant rules"
```

HARD STOP. Write the ledger line and report to Liz.

---

### Task 3: Independent oracle, live walkthrough, reviews, docs, push

**Files:**
- Create (scratchpad only, not committed): `count_oracle.py`
- Modify: `docs/lld_merchant_rules_tab_claude.md` (add "10. Results")
- Modify: `docs/hld_claude.md` section 6 (one line under post-roadmap work, matching how earlier features are recorded)
- Memory: new `merchant_rules_tab_status.md` + `MEMORY.md` pointer

- [ ] **Step 1: Independent count oracle.** In the scratchpad, write `count_oracle.py`. It uses only `sqlite3`, no `app` imports, and has its own copy of the precedence logic:
  - For each transaction, take the rules scoped to that row's account, sorted by id.
  - Then the global rules, sorted by id.
  - The first one where `pattern.lower()` is in `description.lower()` wins.

  Run it against the real `backend/finance.db`, which is read-only here. Compare it with `GET /merchant-rules` from the running server, after confirming the server reloaded Task 1's code: check the worker's start time against the file modification time, per `dev_server_gotchas`.

  Expected:
  - All 77 counts are identical.
  - Rule 53 = 0 and rule 77 = 2.
  - Rule 61 equals the number of Cash Rewards (account 3) rows containing "payment - thank you", queried separately by SQL.

  Time `GET /merchant-rules` with `curl -w "%{time_total}"` and record the result (spec section 3.1).

- [ ] **Step 2: Serve a DB copy on :8000.**
  - Stop the backend that was started this session, killing the reloader first per `dev_server_gotchas`.
  - Copy `backend/finance.db` to the scratchpad.
  - Start uvicorn with `DATABASE_PATH=<copy>` on port 8000.
  - Prove it serves the copy: put a marker note on one row in the copy via SQL, then read it back through `GET /transactions`.
  - Vite on 5173 is Liz's and is left running.

- [ ] **Step 3: Browser walkthrough** (claude-in-chrome, new tab at `http://localhost:5173`). Each step below includes its check.
  1. Open the Rules tab. The header shows "Merchant rules (77)" and the first row is #77 "AUTOPAY PAYMENT", Matches 2, scope "American Express". Rule 53's count is 0 and shown muted.
  2. Search `sq *` and `xpress`. The list narrows to the oracle's expectation. Search `zzz` and the page shows "No rules match zzz".
  3. Delete -> Cancel on rule 53. The rule is still listed and no request is sent (check network requests).
  4. With `payment` typed in the search box, Delete -> Confirm on rule 53, double-clicking Confirm. Exactly one DELETE appears in the network log. The status reads "Deleted rule #53.", the query stays, and rule 53 is gone.
  5. Raw SQL on the copy: rule 53 is gone, and rows 626/629 plus every other row have the same `clean_description`/`category_id` as before the delete (whole-table snapshot diff).
  6. Delete rule 53 again with curl. It returns 404, the UI's reload still works, and this checks the already-deleted path at the API level.
  7. Switch to Transactions, re-categorize one row on the copy, then come back to Rules. The tab re-fetches: watch for a new `GET /merchant-rules` request in the network log.
  8. Trigger the remember-edit panel on the copy, save a rule, and read the new text "To undo, delete rule #N on the Rules tab." Then delete that rule from the Rules tab.
  9. Close the browser tab.

- [ ] **Step 4: Restore.** Stop the copy server and restart the normal backend on :8000 against the real DB. `GET /merchant-rules` must return 77 rules with no marker note. Delete the scratch DB copy.

- [ ] **Step 5: Reviews, run serially.**
  - **Fresh Opus subagent:** give it the spec, this plan and `git diff <merge-base main>..HEAD`. It runs `pytest -q` and `npx vitest run` and quotes the output, then mutation-tests each new test (reading the test helpers, not just the cases) and checks the Global Constraints verbatim.
  - **Codex:** `codex exec --sandbox workspace-write -C <worktree>` on a detached scratch worktree with `node_modules`/`venv` junctioned in. Warn it up front about the EPERM workaround (`vitest run --configLoader runner`), per `DEV_ENVIRONMENT_NOTES.md`. Same instructions. Check its output for anything credential-like.
  - Verify every finding against the code, and re-run any reported failure yourself. Fix unambiguous gaps; bring anything High-severity or new to Liz. Record the outcome in the LLD's Results section.
  - Clean up the worktree: remove the junctions first, then `git worktree remove`.

- [ ] **Step 6: Docs and memory.**
  - LLD section 10 "Results": the real test counts, oracle agreement, timing, walkthrough outcomes and review outcomes.
  - The HLD section 6 line.
  - Memory: `merchant_rules_tab_status.md` plus a `MEMORY.md` pointer.
  - Update `edit_creates_rule_status.md`: its undo text now points at the Rules tab.

- [ ] **Step 7: Commit and push.**

```bash
git add docs/lld_merchant_rules_tab_claude.md docs/hld_claude.md
git commit -m "Record Rules tab verification and reviews"
git push
```

Then confirm with `git status` and `git log --oneline -5`.

HARD STOP. Report to Liz.
