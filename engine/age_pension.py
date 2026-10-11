"""Simplified normal-rate domestic Age Pension estimate, before income tax.

Inputs must be Centrelink-assessable amounts, not raw net worth. Exclude the
principal home and exempt super; deduct only permitted asset-secured debts.
Financial assets include assessable super and modern account-based pensions.
Do not also count their interest, dividends or withdrawals as other income.

Residence/claim eligibility is assumed; age eligibility is checked here. Work
Bonus, Rent Assistance, transitional rates, overseas rules, grandfathered income
streams, illness-separated couples, gifting and special exemptions are excluded.
The taper is continuous; Centrelink rounding and supplement details can differ.
No Streamlit dependencies or stored household data.
"""

from dataclasses import dataclass
from math import isfinite
from typing import Literal

from config import (
    AGE_PENSION_AGE, DEEMING_LOWER_RATE, DEEMING_THRESHOLD, DEEMING_UPPER_RATE,
    FORTNIGHTS_PER_YEAR, PENSION_ASSET_FREE_AREA, PENSION_ASSET_TAPER_PER_DOLLAR,
    PENSION_INCOME_FREE_AREA_FORTNIGHTLY, PENSION_INCOME_TAPER,
    PENSION_MAX_FORTNIGHTLY,
)

HouseholdType = Literal["single", "couple"]
LimitingTest = Literal["assets", "income", "both", "age"]


def _validate_amount(value: float, name: str) -> None:
    """Reject negative or non-finite inputs rather than hiding bad scenarios."""
    if isinstance(value, bool) or not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative.")


def _validate_household(household: HouseholdType) -> None:
    """Only ordinary singles and couples are supported."""
    if household not in ("single", "couple"):
        raise ValueError("Household must be 'single' or 'couple'.")


def deemed_annual_income(financial_assets: float, household: HouseholdType) -> float:
    """Estimate annual income Centrelink assumes financial assets earn."""
    _validate_household(household)
    _validate_amount(financial_assets, "Financial assets")
    threshold = DEEMING_THRESHOLD[household]
    return (min(financial_assets, threshold) * DEEMING_LOWER_RATE
            + max(0.0, financial_assets - threshold) * DEEMING_UPPER_RATE)


def assets_test_fortnightly(
    assessable_assets: float, household: HouseholdType, homeowner: bool,
) -> float:
    """Return single or combined-couple rate before age eligibility scaling."""
    _validate_household(household)
    _validate_amount(assessable_assets, "Assessable assets")
    if not isinstance(homeowner, bool):
        raise ValueError("Homeowner must be True or False.")
    excess = max(0.0, assessable_assets - PENSION_ASSET_FREE_AREA[household, homeowner])
    return max(0.0, PENSION_MAX_FORTNIGHTLY[household]
               - excess * PENSION_ASSET_TAPER_PER_DOLLAR)


def income_test_fortnightly(
    assessable_annual_income: float, household: HouseholdType,
) -> float:
    """Apply income taper to single or combined-couple pension entitlement."""
    _validate_household(household)
    _validate_amount(assessable_annual_income, "Assessable income")
    excess = max(0.0, assessable_annual_income / FORTNIGHTS_PER_YEAR
                 - PENSION_INCOME_FREE_AREA_FORTNIGHTLY[household])
    return max(0.0, PENSION_MAX_FORTNIGHTLY[household] - excess * PENSION_INCOME_TAPER)


@dataclass(frozen=True)
class PensionEstimate:
    """Explainable household estimate; amounts are nominal dollars before tax."""

    annual_pension: float
    fortnightly_pension: float
    assets_test_fortnightly: float
    income_test_fortnightly: float
    deemed_annual_income: float
    assessable_annual_income: float
    eligible_people: int
    limiting_test: LimitingTest


def estimate_age_pension(
    *, age: float, partner_age: float | None = None, homeowner: bool,
    financial_assets: float = 0.0, non_financial_assets: float = 0.0,
    other_assessable_annual_income: float = 0.0,
) -> PensionEstimate:
    """Pay the lower means-test estimate for age-eligible household members.

    A partner age denotes a couple. All amounts are combined household figures.
    Non-financial assets are assessable property/possessions after permitted debt
    deductions; the family home is excluded. Other income includes assessable
    salary and rental income, but excludes deemed-asset returns and Age Pension.
    For couples with one eligible partner, use couple thresholds and half the
    combined payment/tapers. Callers must handle younger-partner exempt super
    before passing financial assets; no automatic 50/50 super allocation occurs.
    """
    _validate_amount(age, "Age")
    if partner_age is not None:
        _validate_amount(partner_age, "Partner age")
    _validate_amount(non_financial_assets, "Non-financial assets")
    _validate_amount(other_assessable_annual_income, "Other assessable income")
    household: HouseholdType = "single" if partner_age is None else "couple"
    deemed = deemed_annual_income(financial_assets, household)
    assessable_income = deemed + other_assessable_annual_income
    assets_rate = assets_test_fortnightly(
        financial_assets + non_financial_assets, household, homeowner,
    )
    income_rate = income_test_fortnightly(assessable_income, household)
    ages = (age,) if partner_age is None else (age, partner_age)
    eligible = sum(person_age >= AGE_PENSION_AGE for person_age in ages)
    share = eligible / len(ages)
    assets_rate *= share
    income_rate *= share
    limiting: LimitingTest
    if eligible == 0:
        limiting = "age"
    elif assets_rate == income_rate:
        limiting = "both"
    else:
        limiting = "assets" if assets_rate < income_rate else "income"
    payment = min(assets_rate, income_rate)
    return PensionEstimate(
        annual_pension=payment * FORTNIGHTS_PER_YEAR,
        fortnightly_pension=payment,
        assets_test_fortnightly=assets_rate,
        income_test_fortnightly=income_rate,
        deemed_annual_income=deemed,
        assessable_annual_income=assessable_income,
        eligible_people=eligible,
        limiting_test=limiting,
    )
