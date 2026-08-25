"""Result equivalence: same information counts, same text does not matter."""

from datetime import date
from decimal import Decimal

from askindia_evals.scoring import score_result


def test_identical_rows_match() -> None:
    assert score_result([{"x": 1}], [{"x": 1}]).correct


def test_extra_predicted_columns_and_different_names_are_fine() -> None:
    gold = [{"population_total": 199812341}]
    pred = [{"name": "UTTAR PRADESH", "pop": 199812341}]
    assert score_result(gold, pred).correct


def test_rounding_and_decimal_types_are_tolerated() -> None:
    assert score_result([{"pct": Decimal("94.00")}], [{"rate": 93.998}]).correct
    assert score_result([{"v": 2516.2}], [{"v": "2516.20"}]).correct
    assert not score_result([{"v": 2516.2}], [{"v": 2600.0}]).correct


def test_strings_compare_loosely_and_years_match_dates() -> None:
    assert score_result([{"name": "KERALA"}], [{"name": "Kerala "}]).correct
    assert score_result([{"year": 2021}], [{"y": date(2021, 1, 1)}]).correct
    assert score_result([{"d": date(2022, 4, 6)}], [{"d": "2022-04-06"}]).correct


def test_row_count_and_membership_are_enforced() -> None:
    gold = [{"s": "A"}, {"s": "B"}, {"s": "C"}]
    assert score_result(gold, [{"s": "C"}, {"s": "A"}, {"s": "B"}]).correct
    assert not score_result(gold, [{"s": "A"}, {"s": "B"}]).correct
    assert not score_result(gold, [{"s": "A"}, {"s": "B"}, {"s": "D"}]).correct


def test_empty_results_never_score() -> None:
    assert not score_result([], []).correct
    assert not score_result([{"x": 1}], []).correct
