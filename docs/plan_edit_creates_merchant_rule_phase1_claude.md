# Remember Edit as Rule - Phase 1 Implementation Plan (backend)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or subagent-driven-development) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the backend everything the Phase 2 panel needs: a preview that says exactly what a candidate rule would do, a create endpoint that refuses unsafe rules, a delete endpoint, and one shared rule-precedence function so none of these can disagree with what imports do.

**Architecture:** `find_matching_rule` (precedence) lives in `app/categories/apply.py` and `apply_merchant_rules` is refactored onto it. A new `app/categories/candidate.py` holds `normalize_rule_text`, `suggest_match_pattern` and `evaluate_candidate` (pure over a session, read-only). The router layer does the source-row lookups and maps outcomes to HTTP codes. `apply_all_rules` (merchant then category) replaces the two hand-ordered call pairs in the pipeline and startup.

**Tech Stack:** Python 3.13, FastAPI 0.115, Pydantic 2.10, SQLAlchemy 2.0, SQLite, pytest.

**Spec:** `docs/lld_edit_creates_merchant_rule_claude.md` v3, sections 3, 4, 8.

## Global Constraints

- Precedence (unchanged): account-scoped rules for the row's account first, then global rules; within a tier, ascending id with an unsaved (id None) candidate last; first case-insensitive substring match (`pattern.lower() in description.lower()`) wins.
- `evaluate_candidate` never writes: no `session.add`, no flush, no commit. The candidate is a transient `MerchantRule` never attached to the session.
- Scope of a candidate always comes from the source row; a request with `source_transaction_id` and `account_id` is 422.
- `match_pattern` and `clean_name` pass through `normalize_rule_text` (strip; blank -> 422) for **every** create call, with or without a source, and for preview patterns.
- Create-with-source refusal order: 404 source missing -> 409 `source_category_changed` -> 400 `pattern_not_matching_source` -> 409 `conflict` -> 409 `category_mismatch`. Error `detail` is a dict with at least `code` and `message`.
- Existing behavior of `POST /merchant-rules` without a source is unchanged except validation; it still calls `apply_merchant_rules` after insert.
- Code style: small functions, docstrings, no defensive try/except, no emojis. Match surrounding style.

**Decisions this plan adds (record in the LLD, Task 5):**

1. **Module split:** `find_matching_rule` and `apply_all_rules` in `apply.py` (they define how rules apply); `normalize_rule_text`, `suggest_match_pattern`, `evaluate_candidate` in new `candidate.py` (they only exist for this feature). The LLD put the suggestion in `apply.py`; this keeps `apply.py` about applying.
2. **Startup-order fix via `apply_all_rules(session)`** called by both `pipeline.py` and `main.py`, instead of swapping two lines in `main.py`. The lifespan isn't exercised by tests (`test_api.py` deliberately avoids it), so a test on a shared function is the only way the order can be pinned; one call site per path also stops them drifting again.
3. **Source lookup and category check live in the router**, not `evaluate_candidate`: they are HTTP-level refusals (404/409) shared by preview and create via one helper `load_source_row(db, id, category_id)`. `evaluate_candidate` takes an already-validated row.

## Review Focus

Inputs the spec implies that are easiest to get wrong:

1. **The source row itself:** it is NULL-clean (usually) and has the chosen category. It must count in `would_name_count`, never in `would_categorize_count` or `category_mismatch_count`. -> Task 3 test.
2. **Rows already named by another rule** (clean set, older rule matches): must count nowhere, even though the pattern matches. -> Task 3.
3. **Account-scoped candidate vs older global rule:** candidate wins (no conflict); global candidate vs the same rule: conflict. -> Task 1 and 3.
4. **Padded input `"  KURA  "`**: previewed and stored as `KURA`. -> Task 4.
5. **Out-of-order rule list** into `find_matching_rule`. -> Task 1.

---

## File Structure

- Modify `backend/app/categories/apply.py` - `find_matching_rule`, `apply_all_rules`; `apply_merchant_rules` uses `find_matching_rule`.
- Modify `backend/app/imports/pipeline.py`, `backend/app/main.py` - call `apply_all_rules`.
- Create `backend/app/categories/candidate.py` - `normalize_rule_text`, `suggest_match_pattern`, `CandidateEvaluation`, `evaluate_candidate`.
- Modify `backend/app/schemas.py` - validated `MerchantRuleCreate`, `MerchantRulePreviewRequest`, `MerchantRulePreviewOut`, `SampleRowOut`.
- Modify `backend/app/routers/merchant_rules.py` - preview endpoint, guarded create, delete.
- Modify `backend/tests/test_merchant_rules.py` - Task 1 tests.
- Create `backend/tests/test_rule_candidate.py` - Tasks 2-3 tests.
- Modify `backend/tests/test_api.py` - Task 4 endpoint tests.
- Modify `docs/lld_edit_creates_merchant_rule_claude.md` - status, decisions 1-3, live results.

Backend commands run from `backend/` with `venv/Scripts/python.exe -m pytest ...`. Baseline before Task 1: record the passing count. Work on `main`; commit per task, staging only that task's files.

---

## Task 1: `find_matching_rule` + `apply_all_rules`

**Files:** `apply.py`, `pipeline.py`, `main.py`, `tests/test_merchant_rules.py`

- [ ] **Step 1: Write failing tests** (in `test_merchant_rules.py`, reusing its `make_session`/`make_transaction`/`setup_account` helpers):
  - `test_find_matching_rule_sorts_by_id_not_input_order`: rules id 5 `"kura"` -> A and id 2 `"kura rev"` -> B passed as `[id5, id2]`; description `"SQ *KURA REVOLVING"` returns id 2.
  - `test_find_matching_rule_account_tier_beats_older_global`: global id 1 matches, account rule id 9 for account 1 matches; account 1 -> id 9; account 2 -> id 1.
  - `test_find_matching_rule_unsaved_candidate_is_last_in_its_tier`: transient `MerchantRule(id=None)` global + saved global id 3, both match -> id 3; candidate account-scoped + saved global id 3 -> candidate.
  - `test_find_matching_rule_returns_none_when_nothing_matches`.
  - `test_apply_all_rules_merchant_rule_wins_over_category_rule`: blank row with `raw_category="Food & Drink"` matching a `CategoryRule` -> cat X and a `MerchantRule` -> cat Y; after `apply_all_rules`, category is Y. (With the old startup order it would be X.)
- [ ] **Step 2: Run, confirm they fail** (`ImportError` for the new names).
- [ ] **Step 3: Implement.**

```python
def find_matching_rule(rules, description: str, account_id: int) -> MerchantRule | None:
    """Return the rule that claims `description` on `account_id`, or None.

    Account-scoped rules for this account are checked before global rules; within a
    tier, rules are checked in ascending id, with an unsaved rule (id None) last.
    First case-insensitive substring match wins. Sorts itself; caller order is ignored.
    """
    description_lower = description.lower()

    def tier(scoped: bool):
        return sorted(
            (r for r in rules if (r.account_id == account_id if scoped else r.account_id is None)),
            key=lambda r: (r.id is None, r.id or 0),
        )

    for rule in tier(True) + tier(False):
        if rule.match_pattern.lower() in description_lower:
            return rule
    return None


def apply_all_rules(session: Session) -> None:
    """Apply merchant rules, then category rules - the one order used everywhere.

    Merchant rules go first: a specific merchant match is more accurate than a
    bank's generic raw_category, so it should win when both apply.
    """
    apply_merchant_rules(session)
    apply_category_rules(session)
```

  `apply_merchant_rules` loads all rules once, and for each NULL-clean row calls `find_matching_rule(all_rules, txn.description, txn.account_id)`; behavior otherwise unchanged (docstring kept, precedence sentence points at `find_matching_rule`). `pipeline.py` replaces its two calls + comment with `apply_all_rules(session)`; `main.py` lifespan replaces its two calls with `apply_all_rules(session)` and fixes imports.
- [ ] **Step 4: Run** `pytest tests/test_merchant_rules.py tests/test_categories.py tests/test_pipeline.py -q`, then the full suite. All pass; count = baseline + 5.
- [ ] **Step 5: Commit** `apply.py pipeline.py main.py tests/test_merchant_rules.py`.

## Task 2: `normalize_rule_text` + `suggest_match_pattern`

**Files:** create `candidate.py`, create `tests/test_rule_candidate.py`

- [ ] **Step 1: Write failing tests.** Parametrized exact cases (every result also asserted `result.lower() in description.lower()`):

| Input | Expected | Step |
|---|---|---|
| `AplPay WALGREENS LAS VEGAS NV` | `WALGREENS LAS VEGAS NV` | 1 + 4 |
| `PRUDENTIAL DES:EDI PYMNTS ID:1` | `PRUDENTIAL` | 2 |
| `SQ *7-ELEVEN 1234` | `SQ *7-ELEVEN` | 3 |
| `PM *iDrama 555` | `PM *iDrama` | 3 |
| `TST* TATTE BAKERY BOSTON MA` | `TST* TATTE` | 3, space after `*` |
| `IC* INSTACART SAN FRANCISCOCA` | `IC* INSTACART` | 3 |
| `UBER   *TRIP HELP.UBER.COM` | `UBER   *TRIP` | 3, spaces kept |
| `VZWRLSS*APOCC VISN 04/21` | `VZWRLSS*APOCC` | 3, no space |
| `TRADER JOE S #519 PORTLAND ME` | `TRADER JOE S` | 4, `#` |
| `Online scheduled transfer from CHK 1962 Confirmation# 1` | `Online scheduled transfer from CHK` | 4, digit |
| `MACYS  ROCKINGHAM PK` | `MACYS  ROCKINGHAM PK` | 4, double space kept |
| `ONLINE STORE * 99` | `ONLINE STORE *` | 3 skipped (prefix has a space); 4 keeps the bare `*` token (no digit or `#`) |
| `7-ELEVEN 33012 BOSTON` | `7-ELEVEN 33012 BOSTON` | first token has a digit -> empty -> fallback |
| `AplPay SQ` | `AplPay SQ` | fallback, never `SQ` |
| `KFC J123 TOKYO` | `KFC J123 TOKYO` | `KFC` < 4 -> fallback |
| `ACME*` | `ACME*` | 3, nothing after `*` |

  Plus `normalize_rule_text`: `"  KURA  "` -> `"KURA"`; `""`, `"   "` raise `ValueError`.
- [ ] **Step 2: Run, confirm failure.**
- [ ] **Step 3: Implement** exactly LLD 4.1 steps 1-5, index-based (`re.finditer(r"\S+", body)` for tokens; `re.match(r"\s*\S+", body[star + 1:])` for the word after `*`), returning `description[start:end]` or the whole description when shorter than 4 characters.
- [ ] **Step 4: Run** the new file and the full suite; count = Task 1 count + cases.
- [ ] **Step 5: Commit** `candidate.py tests/test_rule_candidate.py`.

## Task 3: `evaluate_candidate`

**Files:** `candidate.py`, `tests/test_rule_candidate.py`

- [ ] **Step 1: Write failing tests** on an in-memory session. Fixture: accounts 1 and 2; categories Dining (D), Travel (T), Groceries (G); existing global rule id 1 `"KURA OLD"` -> G; rows:
  - r_src: acct 1, `SQ *KURA REVOLVING SUSHI`, clean NULL, cat D (the edited row)
  - r_blank: acct 1, `SQ *KURA REVOLVING SUSHI #2`, clean NULL, cat NULL
  - r_other_acct: acct 2, `SQ *KURA REVOLVING`, clean NULL, cat NULL
  - r_renamed_travel: acct 1, `SQ *KURA TRAVEL`, clean `"My name"`, cat T
  - r_owned: acct 1, `SQ *KURA OLD TOWN`, clean NULL, cat G (rule 1 wins it)

  Cases, candidate pattern `SQ *KURA` -> D unless stated:
  - global: `would_name_count == 3` (src, blank, other_acct), `would_categorize_count == 2` (blank, other_acct), `category_mismatch_count == 1` (renamed_travel), r_owned in no count; sample's first entry is r_renamed_travel; `matches_source` True; no conflict.
  - this_account_only: `would_name_count == 2`, `would_categorize_count == 1`; r_other_acct excluded.
  - the renamed row counts nothing when an older rule wins: add global rule id 2 `"KURA TRAVEL"` -> T; mismatch becomes 0.
  - non-matching pattern `WALMART` while rule 1 `"KURA"`-style rule matches source: `matches_source` False, `conflicting_rule` None.
  - conflict: existing global rule `"SQ *KURA REV"` matching source; global candidate -> `conflicting_rule` is that rule; this_account_only candidate -> None.
  - sample capped at 5: add 6 more candidate-win rows; `len(sample) == 5`, mismatches first, then newest date first, ties id desc.
  - read-only: rule and transaction counts and r_blank's fields unchanged after a call; `session.new` and `session.dirty` empty.
- [ ] **Step 2: Run, confirm failure.**
- [ ] **Step 3: Implement.**

```python
@dataclass
class CandidateEvaluation:
    match_pattern: str
    matches_source: bool
    conflicting_rule: MerchantRule | None
    would_name_count: int
    would_categorize_count: int
    category_mismatch_count: int
    sample: list[Transaction]


def evaluate_candidate(session, source, match_pattern, category_id, this_account_only) -> CandidateEvaluation:
    """Report what a not-yet-saved rule would do. Read-only; see LLD 4.2."""
```

  Build `candidate = MerchantRule(id=None, match_pattern=..., clean_name="", category_id=category_id, account_id=source.account_id if this_account_only else None)` without adding it to the session. Load existing rules once and in-scope rows once (one query each). `matches_source` computed directly; conflict only when it is True. Per row: winner via `find_matching_rule(existing + [candidate], ...)`, `is candidate` identity check.
- [ ] **Step 4: Run** file + full suite.
- [ ] **Step 5: Commit.**

## Task 4: Schemas and endpoints

**Files:** `schemas.py`, `routers/merchant_rules.py`, `tests/test_api.py`

- [ ] **Step 1: Write failing tests** in `test_api.py` (using `make_client_and_sessionmaker` and direct inserts):
  - Preview with `match_pattern: null` returns the suggestion and full exact response (all 7 fields, sample entries with `id, date, description, category_name`).
  - Preview leaves `merchant_rules` and `transactions` row counts and the touched rows unchanged.
  - Preview 404 (unknown source), 409 `source_category_changed` (source set to another category), 422 blank pattern.
  - Create without source: blank/whitespace pattern 422, blank name 422, `"  DoorDash  "` stored as `"DoorDash"`; existing tests (`test_merchant_rule_applies_immediately_...`, invalid category 400) pass unchanged.
  - Create with source: `account_id` in body 422; `this_account_only` true stores the source's account; each refusal returns its code and the detail fields (`conflict` includes `rule` with id/pattern/clean_name/category_id/account_id; `category_mismatch` includes `count` and `sample`); refusal order: a request that is both non-matching and conflicting returns 400; source with changed category and non-matching pattern returns 409 `source_category_changed`. Successful create applies the rule (r_blank gets name and category).
  - Delete: 204, rule gone, rows it filled keep `clean_description`/`category_id`; second delete 404.
- [ ] **Step 2: Run, confirm failure.**
- [ ] **Step 3: Implement.**
  - `RuleText = Annotated[str, AfterValidator(normalize_rule_text)]`; `MerchantRuleCreate.match_pattern/clean_name: RuleText`; add `source_transaction_id: int | None = None`, `this_account_only: bool = False`; a `model_validator(mode="after")` rejects `account_id` with a source.
  - `MerchantRulePreviewRequest {source_transaction_id: int, match_pattern: RuleText | None = None, category_id: int, this_account_only: bool = False}`.
  - `load_source_row(db, transaction_id, category_id)`: 404 / 409 `source_category_changed`.
  - `POST /merchant-rules/preview` -> `MerchantRulePreviewOut`.
  - Guarded create runs `evaluate_candidate` and raises in the stated order; then inserts with the derived `account_id` and calls `apply_merchant_rules` as today.
  - `DELETE /merchant-rules/{rule_id}`, `status_code=204`.
- [ ] **Step 4: Run** `test_api.py`, then the full suite; record the final count.
- [ ] **Step 5: Commit.**

## Task 5: Live check, docs, review

- [ ] **Step 1: DB copy server.** Copy `backend/finance.db` to `$SCRATCH/finance_rule_phase1.db`; start `DATABASE_PATH=... venv/Scripts/python.exe -m uvicorn app.main:app --port 8001` (no `--reload`) in the background; `curl localhost:8001/health`.
- [ ] **Step 2: Oracle first.** Pick a real row whose suggested pattern no existing rule competes with (chosen from the copy by a read-only script outside `backend/`). Compute expected counts with raw SQL only: `instr(lower(description), lower(:p)) > 0`, split by `clean_description IS NULL`, `category_id IS NULL`, `category_id != :cat`, excluding rows any existing rule matches (checked in SQL with `instr` against each rule's pattern, honoring scope). Then call the preview and compare all counts.
- [ ] **Step 3: Refusals live:** conflict (a row matched by `PAYMENT - THANK YOU`), mismatch (an UBER Eats row with `UBER` -> Dining: expect 30 mismatches), non-matching pattern (400), blank pattern (422), `source_category_changed`.
- [ ] **Step 4: Save + delete live:** create one rule from the Step 2 row; raw SQL confirms the expected rows got the name; delete it; rows unchanged; rule gone.
- [ ] **Step 5: Teardown.** Stop the :8001 server (kill reloader-less PID; confirm port free); delete the copy; confirm the real DB still has 76 rules and 1188 rows.
- [ ] **Step 6: Docs.** LLD: status "Phase 1 built", decisions 1-3, live results with numbers. Memory: new status entry + MEMORY.md pointer.
- [ ] **Step 7: Close-out review.** Fresh Opus reviewer, then Codex, against the merge-base before Task 1: mutation pass on every new test (name a wrong implementation that still passes, reading the helpers), both run the full suite and quote output. Verify each finding before acting; fix gaps; re-run.
- [ ] **Step 8: Commit + push** docs and any review fixes.
