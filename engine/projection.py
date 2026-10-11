"""Deterministic annual household model with no Streamlit or persistence.

Both partners stop salary income when the primary person reaches retirement_age.
Combined super/income use editable allocations, not an inferred legal ownership.
Year rows describe a FULL year starting at the displayed age; balances are year
end. Pension is assessed on opening assets, then returns and annual cash flows
apply. The final row funds the full year beginning at life expectancy.
"""

from dataclasses import dataclass, fields, replace
from math import floor, isfinite

import pandas as pd

from config import (
    ACCUMULATION_EARNINGS_TAX_RATE, AGE_PENSION_AGE, Assumptions,
    CONCESSIONAL_CAP, CONCESSIONAL_CAP_INDEX_STEP, DEFAULT_ASSUMPTIONS, MINIMUM_DRAWDOWN_RATES,
    NON_CONCESSIONAL_CAP, PRESERVATION_AGE, SHORTFALL_TOLERANCE,
    SOLVER_MAX_INCOME, SOLVER_MAX_ITERATIONS, SOLVER_TOLERANCE,
    SUPER_GUARANTEE_RATE, TRANSFER_BALANCE_CAP,
)
from engine.age_pension import estimate_age_pension
from engine.tax import contributions_tax, income_tax_with_excess, total_income_tax


@dataclass(frozen=True)
class Household:
    """Non-identifying household inputs; money is combined annual nominal AUD."""

    age: int = 45
    partner_age: int | None = None
    retirement_age: int = 65
    homeowner: bool = True
    children_ages: tuple[int, ...] = ()
    gross_salary: float = 100_000
    other_income: float = 0
    super_balance: float = 250_000
    salary_sacrifice: float = 0
    after_tax_contributions: float = 0
    cash: float = 20_000
    investments: float = 30_000
    property_value: float = 0
    annual_rent: float = 0
    mortgage_balance: float = 0
    mortgage_rate: float = .06
    mortgage_years: int = 20
    other_debts: float = 0
    annual_spending: float = 50_000
    retirement_income: float = 56_166


def _number(value: float, name: str, minimum: float = 0) -> None:
    """Validate finite numeric values without accepting booleans as money."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be finite and at least {minimum}.")


def validate_scenario(h: Household, a: Assumptions) -> None:
    """Reject invalid scenarios before any simulation or solver work."""
    for name in ("age", "retirement_age"):
        value = getattr(h, name)
        _number(value, name)
        if not isinstance(value, int):
            raise ValueError(f"{name} must be a whole number.")
    if h.partner_age is not None:
        _number(h.partner_age, "partner_age")
        if not isinstance(h.partner_age, int):
            raise ValueError("partner_age must be a whole number.")
    if not isinstance(h.homeowner, bool):
        raise ValueError("homeowner must be True or False.")
    if h.retirement_age < h.age or h.retirement_age > a.life_expectancy:
        raise ValueError("Retirement age must be between current age and life expectancy.")
    for field in fields(h):
        if field.name not in {"age", "partner_age", "retirement_age", "homeowner", "children_ages"}:
            _number(getattr(h, field.name), field.name)
    for child in h.children_ages:
        _number(child, "Child age")
        if not isinstance(child, int) or child > 17:
            raise ValueError("Child ages must be whole numbers from 0 to 17.")
    for field in fields(a):
        _number(getattr(a, field.name), field.name, -0.99 if field.name in {
            "inflation", "wage_growth", "super_return", "investment_return",
            "cash_return", "property_growth", "pension_indexation"} else 0)
    for name in ("surplus_investment_share", "primary_income_share", "primary_super_share",
                 "rental_expense_share", "super_fees"):
        if getattr(a, name) > 1:
            raise ValueError(f"{name} must be between 0 and 1.")
    if not isinstance(a.life_expectancy, int) or not max(h.age, h.partner_age or 0) <= a.life_expectancy <= 120:
        raise ValueError("Life expectancy must be a whole age up to 120, at least both current ages.")
    for balance, years in ((h.mortgage_balance, h.mortgage_years), (h.other_debts, a.other_debt_years)):
        if not isinstance(years, int) or years < 0 or (balance > 0 and years == 0):
            raise ValueError("Debt years must be whole numbers, positive for outstanding debt.")
    if h.annual_rent and not h.property_value:
        raise ValueError("Rental income requires an investment property value.")
    if h.salary_sacrifice > h.gross_salary:
        raise ValueError("Salary sacrifice cannot exceed gross salary.")
    net_super_rate = a.super_return * (1 - ACCUMULATION_EARNINGS_TAX_RATE) - a.super_fees
    if min(net_super_rate, a.super_return - a.super_fees) <= -1:
        raise ValueError("Super return after fees must exceed -100%.")


def annual_loan_payment(balance: float, rate: float, years: int) -> float:
    """Monthly amortisation expressed as a year's scheduled repayments."""
    _number(balance, "balance")
    _number(rate, "rate")
    if isinstance(years, bool) or not isinstance(years, int) or years < 0 or (balance and not years):
        raise ValueError("Loan years must be positive when a balance is outstanding.")
    if not balance:
        return 0.0
    if not rate:
        return balance / years
    monthly = rate / 12
    return 12 * balance * monthly / (1 - (1 + monthly) ** (-12 * years))


def _pay_loan(balance: float, rate: float, annual_payment: float) -> tuple[float, float]:
    """Apply twelve monthly payments; never pay more than balance plus interest."""
    paid = 0.0
    for _ in range(12):
        due = balance * (1 + rate / 12)
        payment = min(due, annual_payment / 12)
        balance = max(0.0, due - payment)
        paid += payment
    return (0.0 if balance < 1e-7 else balance), paid


def minimum_drawdown_rate(age: int) -> float:
    """Full-year account-based pension percentage for age at year start."""
    _number(age, "age")
    return next(rate for lower, rate in reversed(MINIMUM_DRAWDOWN_RATES) if age >= lower)


def _withdraw(balances: list[float], need: float) -> float:
    """Withdraw from a list in order, mutating only simulation-local balances."""
    taken = 0.0
    for i, balance in enumerate(balances):
        amount = min(balance, max(0.0, need - taken))
        balances[i] -= amount
        taken += amount
    return taken


def indexed_concessional_cap(year: int, wage_growth: float) -> float:
    """Round cumulative wage-linked growth down to $2,500 steps, never below base.

    This is a scenario assumption; actual legislated indexation uses AWOTE.
    Grow the unrounded base cumulatively so small annual increases are retained.
    """
    _number(year, "year")
    _number(wage_growth, "wage_growth", -.99)
    if not isinstance(year, int):
        raise ValueError("year must be a whole number.")
    raw_cap = CONCESSIONAL_CAP * (1 + wage_growth) ** year
    return float(max(CONCESSIONAL_CAP,
        floor(raw_cap / CONCESSIONAL_CAP_INDEX_STEP) * CONCESSIONAL_CAP_INDEX_STEP))


@dataclass(frozen=True)
class ContributionResult:
    """Per-person accepted contributions and explainable soft-limit outcomes."""

    additions: list[float]
    sacrifices: list[float]
    excesses: list[float]
    after_tax: float
    rejected: float
    warnings: list[dict]


def _contributions(salary: float, sacrifice: float, after_tax: float,
                   balances: list[float], shares: list[float], ages: list[int],
                   cap: float) -> ContributionResult:
    """Trim sacrifice first; retain employer excess and return warnings."""
    additions, sacrifices, excesses, warnings = [], [], [], []
    actual_after_tax, rejected = 0.0, 0.0
    for balance, share, age in zip(balances, shares, ages):
        sg = salary * share * SUPER_GUARANTEE_RATE
        # Salary sacrifice is an employer contribution; the under-75 limit
        # below applies to the modeled personal after-tax contributions only.
        voluntary = min(sacrifice * share, salary * share, max(0.0, cap - sg))
        excess = max(0.0, sg + voluntary - cap)
        noncon = min(after_tax * share, NON_CONCESSIONAL_CAP) if age < 75 and balance < TRANSFER_BALANCE_CAP else 0.0
        additions.append(sg + voluntary - contributions_tax(sg + voluntary) + noncon)
        sacrifices.append(voluntary)
        excesses.append(excess)
        actual_after_tax += noncon
        rejected += (sacrifice + after_tax) * share - voluntary - noncon
        person = len(additions)
        if sacrifice * share > voluntary:
            warnings.append(dict(code="salary_sacrifice_trimmed", person=person,
                amount=sacrifice * share - voluntary,
                message="Salary sacrifice reduced to fit the modeled before-tax cap."))
        if excess:
            warnings.append(dict(code="excess_concessional", person=person, amount=excess,
                message="Employer super exceeds the modeled cap. Excess is retained in super and added to taxable income with a 15% offset; extra tax is paid from household cash."))
        if after_tax * share > noncon:
            warnings.append(dict(code="after_tax_trimmed", person=person,
                amount=after_tax * share - noncon,
                message="After-tax super contributions reduced under modeled caps or eligibility."))
    return ContributionResult(additions, sacrifices, excesses, actual_after_tax, rejected, warnings)


def project(h: Household, a: Assumptions = DEFAULT_ASSUMPTIONS) -> pd.DataFrame:
    """Return annual balances, income sources, expenses and unmet spending.

    Investments use after-tax total returns, cash interest is taxed as income,
    rent grows with inflation less an editable expense allowance. Other income
    continues in retirement. Mortgage is assumed secured on the exempt home.
    Property is never automatically sold. Tax brackets and other super caps stay
    fixed; concessional cap uses wage growth in $2,500 steps. Pension rates AND
    thresholds grow by pension_indexation. Both indexation paths are assumptions.
    """
    validate_scenario(h, a)
    couple = h.partner_age is not None
    income_shares = [a.primary_income_share, 1 - a.primary_income_share] if couple else [1.0]
    super_shares = [a.primary_super_share, 1 - a.primary_super_share] if couple else [1.0]
    accumulation = [h.super_balance * share for share in super_shares]
    pensions = [0.0] * len(super_shares)
    pension_started = [False] * len(super_shares)
    liquid = [h.cash, h.investments]
    mortgage, debt, property_value = h.mortgage_balance, h.other_debts, h.property_value
    mortgage_payment = annual_loan_payment(mortgage, h.mortgage_rate, h.mortgage_years)
    debt_payment = annual_loan_payment(debt, a.other_debt_rate, a.other_debt_years)
    # Fund the younger partner to the same assumed longevity; no death transition.
    horizon = a.life_expectancy - min(h.age, h.partner_age if couple else h.age)
    rows, warnings = [], []
    for year in range(horizon + 1):
        age = h.age + year
        ages = [age, h.partner_age + year] if couple else [age]
        retired = age >= h.retirement_age
        inflation = (1 + a.inflation) ** year
        pension_factor = (1 + a.pension_indexation) ** year
        salary = 0.0 if retired else h.gross_salary * (1 + a.wage_growth) ** year
        other_income = h.other_income * inflation
        rent = h.annual_rent * inflation * (1 - a.rental_expense_share)
        for i, person_age in enumerate(ages):
            if retired and person_age >= PRESERVATION_AGE and not pension_started[i]:
                transfer = min(accumulation[i], TRANSFER_BALANCE_CAP)
                pensions[i] += transfer
                accumulation[i] -= transfer
                pension_started[i] = True
        assessable_super = sum(pensions) + sum(balance for balance, person_age in zip(accumulation, ages) if person_age >= AGE_PENSION_AGE)
        pension = estimate_age_pension(
            age=age, partner_age=ages[1] if couple else None, homeowner=h.homeowner,
            financial_assets=(sum(liquid) + assessable_super) / pension_factor,
            non_financial_assets=property_value / pension_factor,
            other_assessable_annual_income=(salary + other_income + rent) / pension_factor,
        ).annual_pension * pension_factor
        minimum = [balance * minimum_drawdown_rate(person_age) for balance, person_age in zip(pensions, ages)]
        cash_interest = liquid[0] * a.cash_return
        liquid[1] *= 1 + a.investment_return
        opening_accumulation = accumulation.copy()
        for i in range(len(ages)):
            accumulation[i] *= 1 + a.super_return * (1 - ACCUMULATION_EARNINGS_TAX_RATE) - a.super_fees
            pensions[i] *= 1 + a.super_return - a.super_fees
        cap = indexed_concessional_cap(year, a.wage_growth)
        contributions = _contributions(
            salary, h.salary_sacrifice if not retired else 0.0,
            h.after_tax_contributions if not retired else 0.0,
            opening_accumulation, income_shares, ages, cap,
        )
        additions, sacrifices = contributions.additions, contributions.sacrifices
        after_tax, rejected = contributions.after_tax, contributions.rejected
        warnings.extend(dict(warning, year=year, age=age) for warning in contributions.warnings)
        sacrifice = sum(sacrifices)
        for i, addition in enumerate(additions):
            accumulation[i] += addition
        # Salary sacrifice follows salary ownership; other income follows same
        # explicit split. Pension is allocated only to eligible recipients.
        eligible = [person_age >= AGE_PENSION_AGE for person_age in ages]
        count = sum(eligible)
        taxable_incomes = [max(0.0,
            (salary + other_income + rent + cash_interest) * share - sacrifices[i]
            + (pension / count if eligible[i] else 0.0))
            for i, share in enumerate(income_shares)]
        base_tax = sum(total_income_tax(income) for income in taxable_incomes)
        tax = sum(income_tax_with_excess(income, excess)
                  for income, excess in zip(taxable_incomes, contributions.excesses))
        excess_tax = tax - base_tax
        mortgage, mortgage_paid = _pay_loan(mortgage, h.mortgage_rate, mortgage_payment)
        debt, debt_paid = _pay_loan(debt, a.other_debt_rate, debt_payment)
        children_cost = sum(child + year < 18 for child in h.children_ages) * a.annual_child_cost * inflation
        target = (h.retirement_income if retired else h.annual_spending) * inflation
        expenses = target + children_cost + mortgage_paid + debt_paid + after_tax
        net_income = salary + other_income + rent + cash_interest + pension - sacrifice - tax
        minimum_taken = sum(min(balance, amount) for balance, amount in zip(pensions, minimum))
        pensions = [max(0.0, balance - amount) for balance, amount in zip(pensions, minimum)]
        available = net_income + minimum_taken
        need = max(0.0, expenses - available)
        liquid_taken = _withdraw(liquid, need)
        need -= liquid_taken
        super_taken = 0.0
        if retired:
            super_taken += _withdraw(pensions, need)
            need -= super_taken
            # Accessible excess accumulation stays taxable until withdrawn.
            accessible = [balance if person_age >= PRESERVATION_AGE else 0.0 for balance, person_age in zip(accumulation, ages)]
            excess_taken = _withdraw(accessible, need)
            for i, person_age in enumerate(ages):
                if person_age >= PRESERVATION_AGE:
                    accumulation[i] = accessible[i]
            super_taken += excess_taken
            need -= excess_taken
        surplus = max(0.0, available - expenses)
        # Debt service has priority over living costs/contributions. If even the
        # debt service is unfunded, restore its unpaid amount to the loan rather
        # than inventing repayment. No further interest on arrears is modeled.
        unpaid_debt = max(0.0, need - target - children_cost - after_tax)
        restored_other = min(debt_paid, unpaid_debt)
        debt += restored_other
        debt_paid -= restored_other
        restored_mortgage = min(mortgage_paid, max(0.0, unpaid_debt - restored_other))
        mortgage += restored_mortgage
        mortgage_paid -= restored_mortgage
        liquid[1] += surplus * a.surplus_investment_share
        liquid[0] += surplus * (1 - a.surplus_investment_share)
        property_value *= 1 + a.property_growth
        super_balance = sum(accumulation) + sum(pensions)
        rows.append(dict(
            year=year, age=age, partner_age=ages[1] if couple else None,
            retired=retired, inflation_factor=inflation,
            super=super_balance, pension_super=sum(pensions), accumulation_super=sum(accumulation),
            investments=liquid[1], cash=liquid[0], property=property_value,
            mortgage=mortgage, other_debts=debt,
            net_worth=super_balance + sum(liquid) + property_value - mortgage - debt,
            salary_income=salary, other_income=other_income, rental_income=rent,
            cash_interest=cash_interest, age_pension_income=pension,
            super_income=minimum_taken + super_taken, investment_income=liquid_taken,
            income_tax=tax, salary_sacrifice=sacrifice, after_tax_contributions=after_tax,
            super_contributions=sum(additions), rejected_contributions=rejected,
            concessional_cap=cap, excess_concessional_contributions=sum(contributions.excesses),
            excess_contributions_tax=excess_tax,
            net_income=net_income, target_income=target, child_costs=children_cost,
            mortgage_payment=mortgage_paid, other_debt_payment=debt_paid,
            unpaid_debt_service=restored_mortgage + restored_other,
            total_expenses=expenses, shortfall=max(0.0, need),
        ))
    frame = pd.DataFrame(rows)
    frame.attrs["warnings"] = warnings
    frame.attrs["limitations"] = [
        "Both partners retire together; no death or survivor transition.",
        "Combined income and super use editable allocation assumptions.",
        "Investment total return is after tax; no separate dividends or capital gains tax.",
        "Net worth excludes the family home; investment property is not sold to fund gaps.",
        "Concessional caps use wage growth in $2,500 steps; other caps and tax brackets stay fixed. Future indexation is an assumption.",
        "Tax offsets except the excess-contribution offset, Medicare reductions, Work Bonus and Division 293/296 are excluded.",
        "Excess employer contributions stay in super; release elections and their non-concessional-cap interaction are not modeled.",
        "Voluntary contributions are limited to modeled caps and reported as rejected_contributions.",
        "Unfunded expenses are reported without new borrowing; repay loans before discretionary spending.",
    ]
    return frame


def todays_dollars(projection: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with all monetary columns deflated, preserving ages/flags."""
    result = projection.copy()
    metadata = {"year", "age", "partner_age", "retired", "inflation_factor"}
    for column in result.columns:
        if column not in metadata:
            result[column] = result[column] / result["inflation_factor"]
    return result


def money_lasts_until(projection: pd.DataFrame) -> int | None:
    """First retirement age with an unmet expense; None means horizon funded.

    This measures spending coverage, not whether all wealth (including property)
    reaches zero. A later pension may restore coverage after an earlier gap.
    """
    gaps = projection[projection.retired & (projection.shortfall > SHORTFALL_TOLERANCE)]
    return None if gaps.empty else int(gaps.iloc[0].age)


@dataclass(frozen=True)
class SustainableIncome:
    """Today-dollar income and a verified bracket, or an explicit failure reason."""

    annual_income: float
    upper_bound: float
    feasible: bool
    reason: str


def sustainable_income(h: Household, a: Assumptions = DEFAULT_ASSUMPTIONS,
                       tolerance: float = SOLVER_TOLERANCE) -> SustainableIncome:
    """Binary-search spending that funds every year through household longevity.

    No terminal estate target. Property cannot fund a gap without rent or sale.
    Even zero retirement spending may fail due to debt/children or earlier gaps;
    such scenarios return feasible=False rather than an invented safe income.
    """
    _number(tolerance, "tolerance")
    if tolerance == 0:
        raise ValueError("Solver tolerance must be positive.")
    def funded(income: float) -> bool:
        frame = project(replace(h, retirement_income=income), a)
        return bool((frame.shortfall <= SHORTFALL_TOLERANCE).all())
    if not funded(0):
        return SustainableIncome(0.0, 0.0, False, "Expenses cannot be funded even with zero retirement spending.")
    low, high = 0.0, max(1.0, h.retirement_income)
    high = min(high, SOLVER_MAX_INCOME)
    while funded(high):
        low = high
        if high == SOLVER_MAX_INCOME:
            return SustainableIncome(low, high, True, "Search ceiling reached; result is a lower bound.")
        high = min(high * 2, SOLVER_MAX_INCOME)
    for _ in range(SOLVER_MAX_ITERATIONS):
        if high - low <= tolerance:
            break
        middle = (low + high) / 2
        if funded(middle):
            low = middle
        else:
            high = middle
    return SustainableIncome(low, high, True, "Feasible income within the returned search bracket.")
