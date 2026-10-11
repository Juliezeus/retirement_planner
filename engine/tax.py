"""Simplified annual resident tax for ONE person, in nominal AUD.

Excludes offsets (including LITO/SAPTO), Medicare low-income reductions and
exemptions, Medicare levy surcharge, HELP and Division 293. Excess concessional
income inclusion and its non-refundable offset are modeled, without release
elections. The projection must disclose these limitations and an assumed income split
when only combined couple income is available. This is not an ATO tax estimator.
"""

from math import isfinite

from config import (
    CONTRIBUTIONS_TAX_RATE, EXCESS_CONTRIBUTIONS_OFFSET_RATE,
    MEDICARE_LEVY_RATE, RESIDENT_TAX_BRACKETS,
)


def income_tax_with_excess(taxable_income: float, excess_contributions: float) -> float:
    """Add excess concessional income and apply the 15% income-tax offset.

    The non-refundable offset cannot reduce income tax below zero and does not
    reduce Medicare levy. This handles an excess crossing marginal brackets.
    Extra tax is paid from household cash, while contributions remain in super.
    """
    _validate_amount(taxable_income)
    _validate_amount(excess_contributions)
    income = taxable_income + excess_contributions
    offset = excess_contributions * EXCESS_CONTRIBUTIONS_OFFSET_RATE
    return max(0.0, resident_income_tax(income) - offset) + medicare_levy(income)


def _validate_amount(amount: float) -> None:
    """Reject negative, infinite and missing monetary values."""
    if not isfinite(amount) or amount < 0:
        raise ValueError("Amount must be a finite, non-negative number.")


def resident_income_tax(taxable_income: float) -> float:
    """Calculate progressive 2026–27 tax before offsets and Medicare levy."""
    _validate_amount(taxable_income)
    return sum(
        max(0.0, min(taxable_income, upper) - lower) * rate
        for lower, upper, rate in RESIDENT_TAX_BRACKETS
    )


def medicare_levy(taxable_income: float) -> float:
    """Apply the requested flat 2% assumption; no low-income adjustment."""
    _validate_amount(taxable_income)
    return taxable_income * MEDICARE_LEVY_RATE


def total_income_tax(taxable_income: float) -> float:
    """Return income tax plus the simplified Medicare levy."""
    return resident_income_tax(taxable_income) + medicare_levy(taxable_income)


def after_tax_income(taxable_income: float) -> float:
    """Return income remaining after modeled tax and levy."""
    return taxable_income - total_income_tax(taxable_income)


def contributions_tax(concessional_contributions: float) -> float:
    """Calculate standard 15% tax on employer and salary-sacrifice contributions.

    Contribution caps are checked separately; contributions are not silently
    clipped here. After-tax contributions must not be passed to this function.
    """
    _validate_amount(concessional_contributions)
    return concessional_contributions * CONTRIBUTIONS_TAX_RATE
