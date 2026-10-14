"""Tests for the import overlap guard's pairing rule.

Numbered tests match docs/lld_import_overlap_guard_claude.md ("Tests"); R-tests come from
the Phase 1 plan's Review Focus. Ids, dates and list order are deliberately not aligned.
"""
from datetime import date

import time

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


def test_r7_closer_new_row_wins_even_when_farther_row_is_earlier():
    # Test 5 with the farther row dated first, so "earliest new date wins" cannot pass it.
    far, near = new(8, "far"), new(11, "near")
    assert held([far, near], [existing(4, 10)]) == {"near": 4}
    assert held([near, far], [existing(4, 10)]) == {"near": 4}


def test_r8_smallest_total_gap_across_several_pairs():
    # b-10 + c-20 totals 3 days; a-10 + b-20 totals 4 (but has the smaller sum of squares).
    new_rows = [new(1, "a"), new(3, "b"), new(8, "c")]
    existing_rows = [existing(10, 3), existing(20, 5)]
    assert held(new_rows, existing_rows) == {"b": 10, "c": 20}
    assert held(new_rows[::-1], existing_rows[::-1]) == {"b": 10, "c": 20}


def test_r9_same_date_new_rows_tie_on_hash_not_file_position():
    for new_rows in ([new(10, "z"), new(10, "a")], [new(10, "a"), new(10, "z")]):
        assert held(new_rows, [existing(1, 10)]) == {"a": 1}


def test_r10_same_date_existing_rows_tie_on_lowest_id():
    for existing_rows in ([existing(9, 12), existing(5, 12)], [existing(5, 12), existing(9, 12)]):
        assert held([new(10, "a")], existing_rows) == {"a": 5}


def test_r11_oversized_fallback_shows_closest_then_earliest_then_lowest_id():
    # Nine new rows force the fallback; closest (id 5) is neither first, earliest nor lowest id.
    nine_new = [new(10, f"n{i}") for i in range(9)]
    for existing_rows in ([existing(9, 8), existing(5, 11), existing(1, 12)],
                          [existing(1, 12), existing(5, 11), existing(9, 8)]):
        assert held(nine_new, existing_rows) == {f"n{i}": 5 for i in range(9)}
    # Nine existing rows force the fallback; equal gaps (id 9 on Jan 9, id 1 on Jan 11) go to the earlier date.
    nine_existing = [existing(1, 11), existing(9, 9)] + [existing(20 + i, 13) for i in range(7)]
    assert held([new(10, "a")], nine_existing) == {"a": 9}
    assert held([new(10, "a")], nine_existing[::-1]) == {"a": 9}


def test_r12_new_rows_are_never_compared_to_each_other():
    same_amount_pair = [new(10, "first"), new(11, "second")]
    assert held(same_amount_pair, []) == {}
    assert held(same_amount_pair, [existing(1, 10, amount_cents=-999)]) == {}


def test_r13_window_crosses_month_boundary():
    assert held([new(30, "a")], [existing(1, 1, month=2)]) == {"a": 1}


def test_r14_dense_cluster_at_threshold_is_fast():
    new_rows = [new(10 + i % 3, f"n{i}") for i in range(8)]
    existing_rows = [existing(100 + i, 10 + i % 3) for i in range(8)]
    started = time.perf_counter()
    assert len(held(new_rows, existing_rows)) == 8
    assert time.perf_counter() - started < 1.0
