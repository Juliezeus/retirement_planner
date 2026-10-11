"""Central rates and assumptions for the initial 2026–27 planning model.

Verify annually and after Budget changes; pension rates change twice yearly.
Pension rates were checked against Services Australia on 11 October 2026.
Super rates/caps follow the supplied specification and official references
listed in the README; returns and future indexation are modeling assumptions.
Caps apply PER PERSON, not per household. Monetary amounts are AUD.
"""

from dataclasses import dataclass

FINANCIAL_YEAR = "2026-27"
RATES_REVIEW_DATE = "2026-10-11"
SUPER_GUARANTEE_RATE = 0.12
CONCESSIONAL_CAP = 32_500
NON_CONCESSIONAL_CAP = 130_000
TRANSFER_BALANCE_CAP = 2_100_000
CONTRIBUTIONS_TAX_RATE = 0.15
PRESERVATION_AGE = 60
ACCUMULATION_EARNINGS_TAX_RATE = 0.10
RETIREMENT_EARNINGS_TAX_RATE = 0.0
# Each tuple is (inclusive minimum age, annual minimum withdrawal rate).
MINIMUM_DRAWDOWN_RATES = ((0, .04), (65, .05), (75, .06), (80, .07),
                          (85, .09), (90, .11), (95, .14))
AGE_PENSION_AGE = 67
# Normal domestic rates, including maximum Pension and Energy Supplements.
# Verify annually AND at March/September pension updates and July thresholds.
PENSION_RATES_EFFECTIVE_DATE = "2026-09-20"
PENSION_SOURCES = {
    "rates": "https://www.servicesaustralia.gov.au/how-much-age-pension-you-can-get",
    "assets": "https://www.servicesaustralia.gov.au/assets-test-for-age-pension",
    "income": "https://www.servicesaustralia.gov.au/income-test-for-age-pension",
    "deeming": "https://www.servicesaustralia.gov.au/deeming?context=22526",
    "asset_taper": "https://guides.dss.gov.au/social-security-guide/4/2/3",
    "eligibility": "https://www.servicesaustralia.gov.au/age-pension",
}
FORTNIGHTS_PER_YEAR = 26
PENSION_MAX_FORTNIGHTLY = {"single": 1237.70, "couple": 1866.00}
PENSION_ASSET_FREE_AREA = {
    ("single", True): 333_000, ("single", False): 600_000,
    ("couple", True): 499_000, ("couple", False): 766_000,
}
PENSION_ASSET_TAPER_PER_DOLLAR = .003
PENSION_INCOME_FREE_AREA_FORTNIGHTLY = {"single": 226, "couple": 396}
PENSION_INCOME_TAPER = .50
DEEMING_THRESHOLD = {"single": 66_800, "couple": 110_600}
DEEMING_LOWER_RATE = .0175
DEEMING_UPPER_RATE = .0375
# Marginal brackets: lower bound, exclusive upper bound, rate.
# Source: Income Tax Rates Act 1986, Schedule 7, 2026–27 resident table.
# https://www.legislation.gov.au/C2004A03348/2026-07-01/2026-07-01/text
RESIDENT_TAX_BRACKETS = (
    (0, 18_200, .0), (18_200, 45_000, .15),
    (45_000, 135_000, .30), (135_000, 190_000, .37),
    (190_000, float("inf"), .45),
)
MEDICARE_LEVY_RATE = .02
ASFA_ANNUAL_SPENDING = {
    "single": {"modest": 36_548, "comfortable": 56_166},
    "couple": {"modest": 52_690, "comfortable": 78_998},
}
DISCLAIMER = (
    "General information only, not financial advice. Estimates rely on simplified "
    "assumptions and are not guaranteed. Consider speaking with a licensed "
    "financial adviser before making retirement decisions."
)


@dataclass(frozen=True)
class Assumptions:
    """Editable defaults; a scenario should create its own instance."""

    inflation: float = .025
    wage_growth: float = .035
    super_return: float = .07
    super_fees: float = .008
    investment_return: float = .065
    cash_return: float = .04
    property_growth: float = .045
    life_expectancy: int = 92
    annual_child_cost: float = 18_000
    surplus_investment_share: float = .50
    # Modeling choices, not legislated rates. Investments use after-tax returns.
    primary_income_share: float = .50
    primary_super_share: float = .50
    rental_expense_share: float = .20
    other_debt_rate: float = .08
    other_debt_years: int = 5
    pension_indexation: float = .025


SOLVER_TOLERANCE = 1.0
SOLVER_MAX_INCOME = 10_000_000.0
SOLVER_MAX_ITERATIONS = 80
SHORTFALL_TOLERANCE = .01


DEFAULT_ASSUMPTIONS = Assumptions()
ASFA_QUARTER = "June 2026"
ASFA_SOURCE = "https://www.superannuation.asn.au/media-release/asfa-retirement-standard-retirees-living-costs-rising-faster-than-inflation-as-power-healthcare-insurance-bills-climb/"
SCENARIO_SCHEMA_VERSION = 1
SCENARIO_MAX_BYTES = 100_000
MAX_CHILDREN = 10
MAX_INPUT_MONEY = 1_000_000_000.0
CLOSE_RATIO = .90
