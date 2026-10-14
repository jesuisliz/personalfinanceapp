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
