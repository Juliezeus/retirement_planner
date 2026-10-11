"""Projection tests with independently calculated cash flows and balances."""

from dataclasses import replace

import pandas as pd
import pytest

from config import Assumptions
from engine.projection import (
    Household, annual_loan_payment, minimum_drawdown_rate, money_lasts_until,
    project, sustainable_income, todays_dollars,
)


def assumptions(**changes) -> Assumptions:
    """No-growth baseline for hand-calculated examples."""
    defaults = dict(inflation=0, wage_growth=0, super_return=0,
                    super_fees=0, investment_return=0, cash_return=0,
                    property_growth=0, pension_indexation=0)
    return replace(Assumptions(), **(defaults | changes))


def household(**changes) -> Household:
    defaults = dict(age=60, retirement_age=61, gross_salary=0,
                    super_balance=0, cash=0, investments=0, annual_spending=0,
                    retirement_income=0)
    return replace(Household(), **(defaults | changes))


def test_salary_contributions_and_surplus() -> None:
    h = household(gross_salary=100_000, salary_sacrifice=10_000,
                  after_tax_contributions=2_000, annual_spending=40_000)
    row = project(h, assumptions(life_expectancy=61)).iloc[0]
    # $90,000 taxable: $17,520 income tax + $1,800 Medicare.
    assert row.income_tax == pytest.approx(19_320)
    assert row.super_contributions == pytest.approx(22_000 * .85 + 2_000)
    assert row.cash == row.investments == pytest.approx(14_340)
    assert row.shortfall == 0


def test_mortgage_amortises_and_zero_interest() -> None:
    assert annual_loan_payment(120_000, 0, 10) == 12_000
    assert annual_loan_payment(100_000, .06, 1) == pytest.approx(103_279.7156485)
    frame = project(household(cash=110_000, mortgage_balance=100_000,
        mortgage_rate=.06, mortgage_years=1), assumptions(life_expectancy=61))
    assert frame.iloc[0].mortgage == 0
    assert frame.iloc[0].mortgage_payment == pytest.approx(103_279.7156485)
    assert frame.iloc[1].mortgage_payment == 0


def test_children_stop_at_eighteen() -> None:
    frame = project(household(cash=100_000, children_ages=(17,)), assumptions(life_expectancy=61))
    assert frame.child_costs.tolist() == [18_000, 0]
    assert frame.iloc[0].cash == 82_000


def test_locked_super_cannot_fund_early_retirement() -> None:
    h = household(age=58, retirement_age=58, super_balance=100_000,
                  investments=10_000, retirement_income=15_000)
    frame = project(h, assumptions(life_expectancy=60))
    assert frame.iloc[0].super == 100_000
    assert frame.iloc[0].investment_income == 10_000
    assert frame.iloc[0].shortfall == 5_000
    assert frame.iloc[2].shortfall == 0
    assert frame.iloc[2].super_income == 15_000
    assert money_lasts_until(frame) == 58


def test_minimum_drawdown_surplus_is_kept() -> None:
    row = project(household(retirement_age=60, super_balance=100_000,
        retirement_income=1_000), assumptions(life_expectancy=60)).iloc[0]
    assert row.super_income == 4_000
    assert row.super == 96_000
    assert row.cash + row.investments == 3_000
    assert row.net_worth == 99_000


def test_mixed_age_super_and_longevity() -> None:
    frame = project(household(partner_age=58, retirement_age=60, super_balance=200_000),
                    assumptions(life_expectancy=61))
    assert len(frame) == 4
    assert frame.iloc[0].super_income == 4_000
    assert frame.iloc[0].accumulation_super == 100_000
    assert frame.iloc[-1].partner_age == 61
    assert frame.iloc[-1].age == 63


def test_pension_starts_at_each_partners_age_67() -> None:
    frame = project(household(age=66, partner_age=65, retirement_age=66), assumptions(life_expectancy=67))
    assert frame.age_pension_income.tolist() == pytest.approx([0, 24_258, 48_516])


def test_accumulation_and_retirement_returns() -> None:
    a = replace(assumptions(life_expectancy=61), super_return=.10, super_fees=.01)
    frame = project(household(super_balance=100_000), a)
    assert frame.iloc[0].super == pytest.approx(108_000)
    # Retirement phase: 9% return, minimum 4% of opening $108,000.
    assert frame.iloc[1].super == pytest.approx(113_400)


def test_transfer_cap_keeps_excess_in_accumulation() -> None:
    row = project(household(retirement_age=60, super_balance=2_200_000),
                  assumptions(life_expectancy=60)).iloc[0]
    assert row.accumulation_super == 100_000
    assert row.pension_super == 2_016_000


def test_capped_voluntary_contributions_are_reported() -> None:
    row = project(household(gross_salary=100_000, salary_sacrifice=30_000,
        cash=200_000, after_tax_contributions=140_000), assumptions(life_expectancy=61)).iloc[0]
    assert row.salary_sacrifice == 20_500
    assert row.after_tax_contributions == 130_000
    assert row.rejected_contributions == 19_500
    assert row.super_contributions == pytest.approx(157_625)


def test_other_debt_is_repaid() -> None:
    a = replace(assumptions(life_expectancy=61), other_debt_rate=0, other_debt_years=1)
    frame = project(household(cash=20_000, other_debts=10_000), a)
    assert frame.iloc[0].other_debts == 0
    assert frame.iloc[0].other_debt_payment == 10_000
    assert frame.iloc[0].cash == 10_000


def test_unfunded_debt_is_not_erased() -> None:
    frame = project(household(mortgage_balance=10_000, mortgage_rate=0,
        mortgage_years=1), assumptions(life_expectancy=61))
    assert frame.iloc[0].mortgage == 10_000
    assert frame.iloc[0].mortgage_payment == 0
    assert frame.iloc[0].unpaid_debt_service == 10_000
    assert frame.iloc[0].shortfall == 10_000


def test_inflation_and_today_dollar_copy() -> None:
    a = replace(assumptions(life_expectancy=61), inflation=.10)
    frame = project(household(retirement_age=60, cash=100_000, retirement_income=10_000), a)
    real = todays_dollars(frame)
    assert frame.target_income.tolist() == [10_000, 11_000]
    assert real.target_income.tolist() == [10_000, 10_000]
    assert real.iloc[1].cash == pytest.approx(79_000 / 1.1)
    pd.testing.assert_series_equal(real.age, frame.age)


def test_rent_cash_interest_and_tax_are_not_double_counted() -> None:
    a = replace(assumptions(life_expectancy=60), cash_return=.04)
    row = project(household(retirement_age=60, cash=100_000,
        property_value=500_000, annual_rent=20_000), a).iloc[0]
    # $16,000 net rent + $4,000 interest; $270 tax plus $400 levy.
    assert row.rental_income == 16_000
    assert row.income_tax == 670
    assert row.cash + row.investments == 119_330


def test_solver_known_three_year_case_and_boundary() -> None:
    h = household(retirement_age=60, cash=90_000, retirement_income=20_000)
    a = assumptions(life_expectancy=62)
    result = sustainable_income(h, a, tolerance=.10)
    assert result.feasible
    assert result.annual_income == pytest.approx(30_000, abs=.10)
    assert result.upper_bound - result.annual_income <= .10
    assert money_lasts_until(project(replace(h, retirement_income=result.annual_income), a)) is None
    assert money_lasts_until(project(replace(h, retirement_income=result.upper_bound + 1), a)) == 62


def test_solver_reports_unfunded_pre_retirement_expenses() -> None:
    result = sustainable_income(household(annual_spending=10_000), assumptions(life_expectancy=61))
    assert not result.feasible
    assert result.annual_income == 0


@pytest.mark.parametrize("age, rate", [(60,.04), (65,.05), (75,.06), (80,.07),
    (85,.09), (90,.11), (95,.14)])
def test_minimum_rates(age, rate) -> None:
    assert minimum_drawdown_rate(age) == rate


@pytest.mark.parametrize("changes", [
    {"age": -1}, {"age": True}, {"cash": float("nan")},
    {"investments": -1}, {"retirement_age": 59}, {"children_ages": (18,)},
    {"mortgage_balance": 100, "mortgage_years": 0}, {"annual_rent": 100},
    {"salary_sacrifice": 1}, {"homeowner": "yes"},
])
def test_invalid_inputs(changes) -> None:
    with pytest.raises(ValueError):
        project(household(**changes), assumptions(life_expectancy=61))


def test_projection_is_repeatable_and_balances_nonnegative() -> None:
    h = Household(partner_age=43, children_ages=(10, 14), mortgage_balance=100_000)
    first = project(h)
    pd.testing.assert_frame_equal(first, project(h))
    assert (first[["super", "investments", "cash", "mortgage", "other_debts", "shortfall"]] >= 0).all().all()
    assert first.iloc[-1].partner_age == 92
