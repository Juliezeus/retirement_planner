"""Independent expected values for the simplified annual tax model."""

import pytest

from engine.tax import (
    after_tax_income, contributions_tax, medicare_levy,
    resident_income_tax, total_income_tax,
)


@pytest.mark.parametrize("income, expected", [
    (0, 0), (18_200, 0), (18_201, .15), (45_000, 4_020),
    (45_001, 4_020.30), (100_000, 20_520), (135_000, 31_020),
    (135_001, 31_020.37), (190_000, 51_370),
    (190_001, 51_370.45), (250_000, 78_370),
])
def test_resident_brackets(income: float, expected: float) -> None:
    assert resident_income_tax(income) == pytest.approx(expected)


def test_levy_and_take_home() -> None:
    assert medicare_levy(100_000) == pytest.approx(2_000)
    assert total_income_tax(100_000) == pytest.approx(22_520)
    assert after_tax_income(100_000) == pytest.approx(77_480)


@pytest.mark.parametrize("amount, expected", [(0, 0), (12_000, 1_800), (32_500, 4_875)])
def test_contributions(amount: float, expected: float) -> None:
    assert contributions_tax(amount) == pytest.approx(expected)


@pytest.mark.parametrize("function", [resident_income_tax, medicare_levy,
    total_income_tax, after_tax_income, contributions_tax])
@pytest.mark.parametrize("amount", [-1, float("nan"), float("inf"), -float("inf")])
def test_invalid_amounts(function, amount: float) -> None:
    with pytest.raises(ValueError, match="finite, non-negative"):
        function(amount)


def test_individual_tax_is_not_household_tax() -> None:
    assert 2 * total_income_tax(50_000) == pytest.approx(13_040)
    assert total_income_tax(100_000) == pytest.approx(22_520)
