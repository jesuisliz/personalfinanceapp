# Import Overlap Guard - Phase 1 Implementation Plan (pairing function)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure pairing function that decides which newly parsed rows are suspected cross-format duplicates, prove it with unit tests, and prove it against real import history by switching the replay script to call it.

**Architecture:** One new module, `backend/app/imports/overlap.py`, with no DB or pipeline dependency: it takes plain row records and returns `{new row index: existing row id}`. Candidate pairs are grouped into clusters (connected new/existing rows); each cluster is solved by exhaustive search (most held, then smallest total date gap, then a content-key tie-break), or, above 8 rows on either side, every new row with a candidate is held. Nothing in the import path changes in this phase.

**Tech Stack:** Python 3, pytest, stdlib only.

**Spec:** `docs/lld_import_overlap_guard_claude.md` (sections "Rule", "Measured against real import history", "Tests" 1-6c).

## Global Constraints

- Window: **3 days** either way (`WINDOW_DAYS = 3`), inclusive: a 3-day gap pairs, 4 does not.
- Match on same `account_id` AND same signed `amount_cents`. No description comparison.
- One-to-one pairing: each existing row explains at most one new row; each new row is held for at most one existing row (except the oversized-cluster fallback, below).
- Result must be **independent of the order** of both input lists. File position is never a tie-break.
- Cluster ranking: (1) most rows held, (2) smallest total date gap, (3) earliest by (new row date, new row hash).
- Cluster with **more than 8** new or **more than 8** existing rows: skip search, hold every new row that has any candidate.
- Rows within the new list are never compared to each other.
- Code style: small functions, docstrings, no defensive try/except, no emojis.

**Spec clarification (record in the LLD, Task 2):** tie-break (3) does not decide between two assignments that hold the same new rows with the same total gap but different partners. The full ranking key is the sorted tuple of `(new date, new hash, existing date, existing id)` per pair, compared lexicographically. Existing id is a DB identity, not file position, so order independence holds. In the oversized fallback each held row shows its closest candidate by `(gap, existing date, existing id)`; two held rows may then show the same existing row, which is acceptable since the user decides.

## Review Focus

Input classes the spec implies but tests 1-6c don't pin, most likely to bite first:

1. **Two separate clusters of the same account+amount months apart** - must be solved separately. A "group by account+amount" shortcut would lump them, cross the >8 threshold, and hold rows that should insert. -> test R6, Task 1.
2. **Equal-gap tie between different partners** (two new rows on the same day, existing rows one day either side) - result must not change when either input list is reversed. -> test R2, Task 1.
3. **Oversized threshold exactly at 8 vs 9**, new side and existing side separately (`>` vs `>=` mutation). -> tests R3, R4, Task 1.
4. **`window_days` argument honored** - the replay script depends on it for the 2/3/4/7/14 table. -> test R5, Task 1.
5. **Empty inputs** (no existing rows, e.g. a brand-new account; or no new rows after hash dedupe) -> `{}`. -> test R1, Task 1.

---

## File Structure

- Create `backend/app/imports/overlap.py` - pairing rule only (records, candidate pairs, clusters, search).
- Create `backend/tests/test_overlap.py` - tests 1-6c from the LLD plus R1-R6.
- Modify `backend/scripts/replay_overlap_guard.py` - replace inline greedy pairing with `find_suspected_duplicates`.
- Modify `docs/lld_import_overlap_guard_claude.md` - status, tie-break clarification, replay re-run result, stale "script kept out of the repo" line.

Run all commands from `backend/` unless stated. No dev server is needed in this phase.

---

### Task 1: Pairing function + unit tests

**Files:**
- Create: `backend/app/imports/overlap.py`
- Test: `backend/tests/test_overlap.py`

**Interfaces:**
- Consumes: nothing from the app.
- Produces (Phase 2 and Task 2 rely on these exact names):
  - `WINDOW_DAYS: int = 3`, `MAX_CLUSTER_SIDE: int = 8`
  - `@dataclass(frozen=True) class NewRow: account_id: int; date: date; amount_cents: int; row_hash: str`
  - `@dataclass(frozen=True) class ExistingRow: id: int; account_id: int; date: date; amount_cents: int`
  - `find_suspected_duplicates(new_rows: list[NewRow], existing_rows: list[ExistingRow], window_days: int = WINDOW_DAYS) -> dict[int, int]` - key: index into `new_rows`; value: `ExistingRow.id`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_overlap.py`:

```python
"""Tests for the import overlap guard's pairing rule.

Numbered tests match docs/lld_import_overlap_guard_claude.md ("Tests"); R-tests come from
the Phase 1 plan's Review Focus. Ids, dates and list order are deliberately not aligned.
"""
from datetime import date

import pytest

from app.imports.overlap import ExistingRow, NewRow, find_suspected_duplicates

AMOUNT = -2000


def new(day: int, row_hash: str, account_id: int = 1, amount_cents: int = AMOUNT, month: int = 1) -> NewRow:
    return NewRow(account_id=account_id, date=date(2026, month, day), amount_cents=amount_cents, row_hash=row_hash)


def existing(row_id: int, day: int, account_id: int = 1, amount_cents: int = AMOUNT, month: int = 1) -> ExistingRow:
    return ExistingRow(id=row_id, account_id=account_id, date=date(2026, month, day), amount_cents=amount_cents)


def held(new_rows, existing_rows, **kwargs) -> dict[str, int]:
    """Run the pairing, keyed by row hash so assertions never depend on list positions."""
    result = find_suspected_duplicates(new_rows, existing_rows, **kwargs)
    return {new_rows[index].row_hash: existing_id for index, existing_id in result.items()}


def test_1_same_account_amount_and_date_is_held():
    # The function has no description input: different descriptions cannot prevent a hold.
    assert held([new(5, "a")], [existing(3, 5, account_id=2), existing(7, 5)]) == {"a": 7}


@pytest.mark.parametrize("offset, expected", [(3, {"a": 1}), (-3, {"a": 1}), (4, {}), (-4, {})])
def test_2_window_is_three_days_both_directions(offset, expected):
    assert held([new(15 + offset, "a")], [existing(1, 15)]) == expected


def test_3_different_account_is_not_held():
    new_rows = [new(5, "other", account_id=2), new(5, "same", account_id=1)]
    assert held(new_rows, [existing(4, 5, account_id=1)]) == {"same": 4}


def test_4_amount_must_match_exactly_and_signed():
    assert held([new(5, "a", amount_cents=-2001)], [existing(1, 5, amount_cents=-2000)]) == {}
    assert held([new(5, "a", amount_cents=2000)], [existing(1, 5, amount_cents=-2000)]) == {}


def test_5_closer_new_row_is_held_regardless_of_file_order():
    far, near = new(12, "far"), new(11, "near")
    assert held([far, near], [existing(4, 10)]) == {"near": 4}
    assert held([near, far], [existing(4, 10)]) == {"near": 4}


def test_6_closer_existing_row_wins_even_with_higher_id():
    farther, closer = existing(5, 7), existing(9, 11)
    assert held([new(10, "a")], [farther, closer]) == {"a": 9}
    assert held([new(10, "a")], [closer, farther]) == {"a": 9}


def test_6a_most_held_beats_closest_pair():
    # Closest-first greedy would pair Jan 3 with Jan 4 and leave Jan 7 unpaired.
    existing_rows = [existing(8, 1), existing(2, 4)]
    assert held([new(3, "x"), new(7, "y")], existing_rows) == {"x": 8, "y": 2}


def test_6b_exact_tie_goes_to_earliest_date_not_smallest_hash():
    # Hash order deliberately disagrees with date order.
    jan1, jan3 = new(1, "zz"), new(3, "aa")
    assert held([jan1, jan3], [existing(1, 2)]) == {"zz": 1}
    assert held([jan3, jan1], [existing(1, 2)]) == {"zz": 1}


def test_6c_oversized_cluster_holds_every_new_row():
    new_rows = [new(10 + i % 3, f"n{i}") for i in range(9)]
    existing_rows = [existing(100 + i, 10 + i % 3) for i in range(9)]
    assert set(held(new_rows, existing_rows)) == {f"n{i}" for i in range(9)}


def test_r1_empty_inputs():
    assert held([], [existing(1, 5)]) == {}
    assert held([new(5, "a")], []) == {}


def test_r2_equal_gap_partner_tie_is_order_independent():
    # a-6 + b-3 and a-3 + b-6 both total 2 days; the content key picks a-6 (Jan 1 < Jan 3).
    new_rows = [new(2, "b"), new(2, "a")]
    existing_rows = [existing(6, 1), existing(3, 3)]
    expected = {"a": 6, "b": 3}
    assert held(new_rows, existing_rows) == expected
    assert held(new_rows[::-1], existing_rows) == expected
    assert held(new_rows, existing_rows[::-1]) == expected
    assert held(new_rows[::-1], existing_rows[::-1]) == expected


def test_r3_threshold_on_new_side_is_more_than_eight():
    eight = [new(10, f"n{i}") for i in range(8)]
    assert held(eight, [existing(1, 10)]) == {"n0": 1}
    nine = [new(10, f"n{i}") for i in range(9)]
    assert held(nine, [existing(1, 10)]) == {f"n{i}": 1 for i in range(9)}


def test_r4_threshold_on_existing_side_is_more_than_eight():
    new_rows = [new(10, "a"), new(10, "b")]
    eight = [existing(50, 10)] + [existing(51 + i, 12) for i in range(7)]
    assert held(new_rows, eight) == {"a": 50, "b": 51}
    nine = eight + [existing(58, 13)]
    assert held(new_rows, nine) == {"a": 50, "b": 50}


def test_r5_window_days_argument_is_honored():
    assert held([new(13, "a")], [existing(1, 10)], window_days=2) == {}
    assert held([new(12, "a")], [existing(1, 10)], window_days=2) == {"a": 1}


def test_r6_far_apart_clusters_of_same_amount_are_solved_separately():
    january = [new(10, f"jan{i}") for i in range(5)]
    june = [new(10, f"jun{i}", month=6) for i in range(4)]
    existing_rows = [existing(1, 10), existing(2, 10, month=6)]
    assert held(january + june, existing_rows) == {"jan0": 1, "jun0": 2}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_overlap.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'app.imports.overlap'`.

- [ ] **Step 3: Implement**

`backend/app/imports/overlap.py`:

```python
"""Pairing rule for the import overlap guard.

Decides which newly parsed rows look like cross-format duplicates of rows already in the DB:
same account, same signed amount, dates within a few days. See
docs/lld_import_overlap_guard_claude.md ("Rule").
"""
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

WINDOW_DAYS = 3
MAX_CLUSTER_SIDE = 8


@dataclass(frozen=True)
class NewRow:
    account_id: int
    date: date
    amount_cents: int
    row_hash: str


@dataclass(frozen=True)
class ExistingRow:
    id: int
    account_id: int
    date: date
    amount_cents: int


def find_suspected_duplicates(
    new_rows: list[NewRow], existing_rows: list[ExistingRow], window_days: int = WINDOW_DAYS
) -> dict[int, int]:
    """Return {index into new_rows: id of the existing row it likely duplicates}.

    Pairing is one-to-one within each cluster of linked rows and does not depend on the
    order of either list. Clusters larger than MAX_CLUSTER_SIDE on either side hold every
    new row that has a candidate.
    """
    candidates = _candidate_pairs(new_rows, existing_rows, window_days)
    suspects: dict[int, int] = {}
    for cluster_new, cluster_existing in _clusters(candidates):
        if len(cluster_new) > MAX_CLUSTER_SIDE or len(cluster_existing) > MAX_CLUSTER_SIDE:
            pairs = _closest_for_each(cluster_new, candidates, new_rows, existing_rows)
        else:
            pairs = _best_assignment(cluster_new, candidates, new_rows, existing_rows)
        suspects.update({new_index: existing_rows[existing_index].id for new_index, existing_index in pairs})
    return suspects


def _candidate_pairs(
    new_rows: list[NewRow], existing_rows: list[ExistingRow], window_days: int
) -> dict[int, list[int]]:
    """Map each new row index to the existing row indices it could duplicate."""
    existing_by_key: dict[tuple[int, int], list[int]] = {}
    for existing_index, row in enumerate(existing_rows):
        existing_by_key.setdefault((row.account_id, row.amount_cents), []).append(existing_index)

    candidates: dict[int, list[int]] = {}
    for new_index, row in enumerate(new_rows):
        matches = [
            existing_index
            for existing_index in existing_by_key.get((row.account_id, row.amount_cents), [])
            if abs((existing_rows[existing_index].date - row.date).days) <= window_days
        ]
        if matches:
            candidates[new_index] = matches
    return candidates


def _clusters(candidates: dict[int, list[int]]) -> Iterator[tuple[set[int], set[int]]]:
    """Yield (new indices, existing indices) for each group of rows linked by candidate pairs."""
    new_by_existing: dict[int, list[int]] = {}
    for new_index, existing_indices in candidates.items():
        for existing_index in existing_indices:
            new_by_existing.setdefault(existing_index, []).append(new_index)

    visited: set[int] = set()
    for start in candidates:
        if start in visited:
            continue
        cluster_new: set[int] = set()
        cluster_existing: set[int] = set()
        pending = [start]
        while pending:
            new_index = pending.pop()
            if new_index in cluster_new:
                continue
            cluster_new.add(new_index)
            for existing_index in candidates[new_index]:
                if existing_index not in cluster_existing:
                    cluster_existing.add(existing_index)
                    pending.extend(new_by_existing[existing_index])
        visited |= cluster_new
        yield cluster_new, cluster_existing


def _gap(new_row: NewRow, existing_row: ExistingRow) -> int:
    return abs((existing_row.date - new_row.date).days)


def _best_assignment(
    cluster_new: set[int],
    candidates: dict[int, list[int]],
    new_rows: list[NewRow],
    existing_rows: list[ExistingRow],
) -> list[tuple[int, int]]:
    """Try every one-to-one assignment in the cluster and return the best-ranked one."""
    order = sorted(cluster_new, key=lambda i: (new_rows[i].date, new_rows[i].row_hash))
    best: tuple[tuple, list[tuple[int, int]]] | None = None

    def search(position: int, used: set[int], pairs: list[tuple[int, int]]) -> None:
        nonlocal best
        if position == len(order):
            rank = _rank(pairs, new_rows, existing_rows)
            if best is None or rank < best[0]:
                best = (rank, list(pairs))
            return
        new_index = order[position]
        for existing_index in candidates[new_index]:
            if existing_index not in used:
                used.add(existing_index)
                pairs.append((new_index, existing_index))
                search(position + 1, used, pairs)
                pairs.pop()
                used.remove(existing_index)
        search(position + 1, used, pairs)

    search(0, set(), [])
    return best[1]


def _rank(pairs: list[tuple[int, int]], new_rows: list[NewRow], existing_rows: list[ExistingRow]) -> tuple:
    """Lower is better: most rows held, then smallest total gap, then earliest content key."""
    total_gap = sum(_gap(new_rows[n], existing_rows[e]) for n, e in pairs)
    content_key = tuple(
        sorted(
            (new_rows[n].date, new_rows[n].row_hash, existing_rows[e].date, existing_rows[e].id)
            for n, e in pairs
        )
    )
    return (-len(pairs), total_gap, content_key)


def _closest_for_each(
    cluster_new: set[int],
    candidates: dict[int, list[int]],
    new_rows: list[NewRow],
    existing_rows: list[ExistingRow],
) -> list[tuple[int, int]]:
    """Oversized-cluster fallback: hold every new row, shown against its closest candidate."""
    pairs = []
    for new_index in cluster_new:
        closest = min(
            candidates[new_index],
            key=lambda e: (_gap(new_rows[new_index], existing_rows[e]), existing_rows[e].date, existing_rows[e].id),
        )
        pairs.append((new_index, closest))
    return pairs
```

- [ ] **Step 4: Run the new tests, then the full suite**

Run: `./venv/Scripts/python.exe -m pytest tests/test_overlap.py -v`
Expected: 18 passed (test 2 is 4 parametrized cases).

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: 208 passed (baseline 190 + 18).

- [ ] **Step 5: Self-mutation check (record results in the ledger)**

Apply each mutation by hand, run `tests/test_overlap.py`, confirm at least one test fails, revert:
1. `<= window_days` -> `< window_days` (expect test 2).
2. drop `row.amount_cents` from the key (expect test 4).
3. rank without `-len(pairs)` (expect 6a).
4. content key using `row_hash` before `date` (expect 6b).
5. `> MAX_CLUSTER_SIDE` -> `>=` (expect R3/R4).
6. `_clusters` replaced by one cluster per (account, amount) (expect R6).
7. drop `existing_rows[e].date` from content key (expect R2).

Any mutation that survives -> add a test that kills it before committing.

- [ ] **Step 6: Commit**

```bash
git add app/imports/overlap.py tests/test_overlap.py
git commit -m "Add pairing function for import overlap guard"
```

---

### Task 2: Replay script calls the real function; re-measure; docs

**Files:**
- Modify: `backend/scripts/replay_overlap_guard.py` (pairing block, docstring)
- Modify: `docs/lld_import_overlap_guard_claude.md`

**Interfaces:**
- Consumes: `NewRow`, `ExistingRow`, `find_suspected_duplicates` from Task 1.
- Produces: nothing new for later phases.

- [ ] **Step 1: Capture the current (greedy) baseline**

From repo root:
```bash
for w in 2 3 4 7 14; do PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend backend/venv/Scripts/python.exe backend/scripts/replay_overlap_guard.py $w | grep window=; done
```
Expected (from the LLD table): 41/0/0 at 2, 3, 4; 41/0/1 at 7; 41/0/9 at 14.

- [ ] **Step 2: Replace the inline pairing**

Add to the imports: `from app.imports.overlap import ExistingRow, NewRow, find_suspected_duplicates`.
Replace the docstring's "Phase 1 of that LLD replaces..." sentence and the "closest first" wording with: "pairing is done by app.imports.overlap.find_suspected_duplicates (the code the import uses)". Replace everything from `cands = []` through the end of the `for diff, eid, ...` loop with:

```python
    new_rows, parsed = [], []
    for a, h, r in rows:
        if h not in all_rows or h in claimed or origin.get(h) != idx:
            continue
        new_rows.append(NewRow(account_id=a, date=r.date, amount_cents=r.amount_cents, row_hash=h))
        parsed.append(r)
    existing_rows = [ExistingRow(id=eid, account_id=ea, date=ed, amount_cents=eamt)
                     for eh, (eid, ea, ed, eamt, edesc) in earlier if eh not in claimed]
    for i, existing_id in find_suspected_duplicates(new_rows, existing_rows, window_days=WINDOW).items():
        r = parsed[i]
        _, _, ed, _, edesc = by_id[existing_id]
        row_id = all_rows[new_rows[i].row_hash][0]
        item = (f.name, r.date, r.amount_cents / 100, r.description[:32], "<->", ed, edesc[:28])
        if row_id in deleted_ids:
            tp.append(item); held_deleted.add(row_id)
        else:
            fp.append(item)
```

and, after `all_rows` is built: `by_id = {v[0]: v for v in all_rows.values()}`.

- [ ] **Step 3: Re-run all five windows**

Same command as Step 1. Expected: identical numbers. If any number differs, **stop and report to Liz** with the differing rows before continuing - do not adjust the function or the expectation.

- [ ] **Step 4: Update the LLD**

In `docs/lld_import_overlap_guard_claude.md`:
- Status line: append "Phase 1 (pairing function) built <date>."
- Under "Rule", after the three ranking criteria, add the tie-break clarification from this plan's Global Constraints.
- Under "Measured against real import history": replace "script kept out of the repo" with the path `backend/scripts/replay_overlap_guard.py`, and replace the "not expected to change these numbers; the replay will be re-run..." sentence with the actual Step 3 result.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/replay_overlap_guard.py docs/lld_import_overlap_guard_claude.md
git commit -m "Replay script uses real overlap pairing; record result"
```

---

### Phase close-out (after both tasks)

- [ ] Independent review, two engines, against merge-base with `main` at phase start (`d853551`): a fresh Opus subagent and `codex exec`. Each **runs** `tests/test_overlap.py` and the full suite and reports literal output, and does a mutation review: for each test, name a wrong implementation that still passes; read the `new`/`existing`/`held` helpers for vacuous defaults. Verify every finding against the code before acting; bring High/cross-cutting ones to Liz.
- [ ] Update `overlap_guard_status` memory (Phase 1 done, next is Phase 2 plan).
- [ ] Push. Stop for Liz's approval before writing the Phase 2 plan.
