"""Hand-calculated pension examples and boundary/eligibility checks."""

import pytest

from engine.age_pension import (
    assets_test_fortnightly, deemed_annual_income, estimate_age_pension,
    income_test_fortnightly,
)


@pytest.mark.parametrize("household, assets, expected", [
    ("single", 0, 0), ("single", 66_800, 1_169),
    ("single", 67_800, 1_206.50), ("couple", 110_600, 1_935.50),
    ("couple", 111_600, 1_973),
])
def test_deeming_tiers(household, assets, expected) -> None:
    assert deemed_annual_income(assets, household) == pytest.approx(expected)


@pytest.mark.parametrize("household, homeowner, threshold, maximum", [
    ("single", True, 333_000, 1_237.70),
    ("single", False, 600_000, 1_237.70),
    ("couple", True, 499_000, 1_866),
    ("couple", False, 766_000, 1_866),
])
def test_asset_thresholds(household, homeowner, threshold, maximum) -> None:
    assert assets_test_fortnightly(threshold - 1, household, homeowner) == maximum
    assert assets_test_fortnightly(threshold, household, homeowner) == maximum
    assert assets_test_fortnightly(threshold + 1_000, household, homeowner) == pytest.approx(maximum - 3)
    assert assets_test_fortnightly(2_000_000, household, homeowner) == 0


@pytest.mark.parametrize("household, free_area, maximum, cutoff", [
    ("single", 226, 1_237.70, 2_701.40),
    ("couple", 396, 1_866, 4_128),
])
def test_income_thresholds(household, free_area, maximum, cutoff) -> None:
    assert income_test_fortnightly(free_area * 26, household) == maximum
    assert income_test_fortnightly((free_area + 100) * 26, household) == pytest.approx(maximum - 50)
    assert income_test_fortnightly(cutoff * 26, household) == pytest.approx(0)
    assert income_test_fortnightly((cutoff + 1) * 26, household) == 0


@pytest.mark.parametrize("ages, expected, eligible", [
    ((66,), 0, 0), ((67,), 1_237.70, 1), ((66, 66), 0, 0),
    ((67, 66), 933, 1), ((66, 67), 933, 1), ((67, 67), 1_866, 2),
])
def test_age_eligibility(ages, expected, eligible) -> None:
    result = estimate_age_pension(age=ages[0], partner_age=ages[1] if len(ages) == 2 else None, homeowner=True)
    assert result.fortnightly_pension == pytest.approx(expected)
    assert result.annual_pension == pytest.approx(expected * 26)
    assert result.eligible_people == eligible
    assert result.limiting_test == ("age" if eligible == 0 else "both")


def test_assets_limit_payment() -> None:
    result = estimate_age_pension(age=70, homeowner=True, non_financial_assets=433_000)
    assert result.fortnightly_pension == pytest.approx(937.70)
    assert result.limiting_test == "assets"


def test_income_limit_includes_deeming() -> None:
    result = estimate_age_pension(age=70, homeowner=True, financial_assets=66_800,
                                  other_assessable_annual_income=26_000)
    # ($26,000 + $1,169) / 26 = $1,044.961538... per fortnight.
    assert result.assessable_annual_income == pytest.approx(27_169)
    assert result.fortnightly_pension == pytest.approx(828.2192307692)
    assert result.limiting_test == "income"


def test_one_eligible_partner_uses_half_combined_tapers() -> None:
    result = estimate_age_pension(age=68, partner_age=60, homeowner=True,
                                  non_financial_assets=599_000)
    assert result.fortnightly_pension == pytest.approx(783)
    income_limited = estimate_age_pension(age=68, partner_age=60, homeowner=True,
        other_assessable_annual_income=496 * 26)
    assert income_limited.fortnightly_pension == pytest.approx(908)


def test_zero_payment_and_no_negative_pension() -> None:
    result = estimate_age_pension(age=70, homeowner=False, financial_assets=5_000_000)
    assert result.annual_pension == 0
    assert result.assets_test_fortnightly == result.income_test_fortnightly == 0


@pytest.mark.parametrize("field", ["age", "partner_age", "financial_assets",
    "non_financial_assets", "other_assessable_annual_income"])
@pytest.mark.parametrize("invalid", [-1, float("nan"), float("inf"), True])
def test_invalid_scenario(field, invalid) -> None:
    arguments = {"age": 70, "homeowner": True, field: invalid}
    with pytest.raises(ValueError):
        estimate_age_pension(**arguments)


def test_invalid_homeownership() -> None:
    with pytest.raises(ValueError):
        estimate_age_pension(age=70, homeowner="yes")


@pytest.mark.parametrize("function, args", [
    (deemed_annual_income, (0, "family")),
    (assets_test_fortnightly, (0, "family", True)),
    (income_test_fortnightly, (0, "family")),
    (deemed_annual_income, (-1, "single")),
    (assets_test_fortnightly, (-1, "single", True)),
    (income_test_fortnightly, (-1, "single")),
])
def test_invalid_helper_inputs(function, args) -> None:
    with pytest.raises(ValueError):
        function(*args)
