# Retirement planner — Phase 1 MVP

General information only. This is a local prototype with simplified calculations,
not a claim of compliance with ASIC requirements or a guaranteed income estimate.

## Files

- `app.py`: landing page, six-step wizard, results dashboard, editable assumptions
  and session-only calculations. It calls the engines; no financial maths is
  implemented in the UI.
- `config.py`: all requested rates and editable assumption defaults. Tax brackets
  were checked against the 2026–27 legislation. Pension figures were checked
  against Services Australia on 11 October 2026. ASFA June 2026 budgets were checked
  against ASFA. Super references are listed below; returns and future indexation
  are modeling assumptions.
- `engine/tax.py`: individual progressive tax, simplified Medicare levy,
  take-home income and standard contributions tax. No Streamlit dependency.
- `engine/age_pension.py`: deeming, assets/income tests and an explainable annual
  household estimate, including couples with only one person aged 67 or older.
- `engine/projection.py`: annual household projection, debt repayments, retirement
  withdrawals, today's-dollar conversion and sustainable-income binary search.
- `insights.py`: reserved for Phase 3.
- `scenarios.py`: explicit versioned JSON schema, download encoding, upload
  validation and app input limits. It never reads or writes server files.
- `tests/test_tax.py`: brackets, boundaries, contributions and invalid inputs.
- `tests/test_age_pension.py`: means-test thresholds, deeming tiers, eligibility,
  mixed-age couples, the lower-payment rule and invalid inputs.
- `tests/test_projection.py`: independent cash-flow examples, mortgage/debt payoff,
  child independence, inflation, super access, minimum drawdowns and solver bounds.
- `tests/test_app.py`: wizard navigation, couple/child inputs, validation,
  budget quick picks, dollar toggle, assumption edits, unfunded plans and reset.
- `tests/test_scenarios.py`: exact JSON round trip and malformed/incompatible files.
- `requirements.txt`: application and testing dependencies.
- `.streamlit/config.toml`: light, calm green theme and disabled usage telemetry.

## VS Code setup (PowerShell)

Open this `retirement_planner` folder in VS Code, then open its terminal:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Choose **Python: Select Interpreter** from the Command Palette and select
`.venv\Scripts\python.exe`. These commands do not require activating the virtual
environment or changing PowerShell execution policy. Open the local URL printed
by Streamlit, normally `http://localhost:8501`. Run commands from this folder so
the theme and imports resolve correctly.

## Modeling limits to carry into the UI

Tax is per individual. A couple's combined income cannot determine exact tax;
the UI discloses editable allocation assumptions. The simplified levy
can overestimate tax for low incomes. Offsets, levy exemptions/surcharge, HELP,
Division 293 is excluded. Excess concessional contributions are added to taxable income with a 15% offset; release elections are excluded. Super caps are per
person. Tax brackets stay at the 2026–27 snapshot; scheduled future tax changes
are not modeled. There is no persistent server scenario storage.

## Using the app

1. Choose **Get started** and follow the six screens. Every field includes a help
   tooltip; dollar inputs accept `$50,000`, `50000` or amounts with cents.
2. Use **Back** to review earlier answers. The retirement age must be older than
   your current age. Use **Plan until age** to change the household horizon.
3. On the final screen choose an ASFA budget or enter your own living budget.
   ASFA budgets are for homeowners aged 65–84; renters may need extra housing costs.
4. Select **See my results**. The headline always uses today's dollars. The chart
   toggle changes only chart values to future dollars; its dotted line deducts debt.
5. Open **Assumptions used**, make changes and select **Apply assumptions**.
   Invalid edits are rejected while the previously applied assumptions remain.
6. Use **Edit my answers** to revisit the wizard. **Clear session and start again**
   clears answers and results from session state.

The status is green when the goal is funded, amber when estimated sustainable
income is within 10% below the goal, and red for a larger gap or an unfunded plan.
Unfunded plans do not show a misleading affordable-income headline. The horizon
message refers to spending coverage, not an assurance that every asset is liquid.

### Save/load and privacy

The sidebar downloads current valid answers and assumptions as JSON. Upload an
app JSON download, select **Load selected scenario**, and review the restored
answers through the wizard. Files are limited to 100 KB, version/model-year
checked, and validated before replacing the session. Malformed JSON, repeated
keys, unexpected fields and invalid values are rejected. No names, identifiers,
dates of birth or free-form identifying fields exist in the scenario schema.

All application-owned household values, projections and calculation memoization
live in `st.session_state`. The app uses no database, scenario disk writes,
cookies for answers, or shared `st.cache_data` for private inputs. Streamlit uses
transient memory to deliver uploads/downloads; no persistent server storage is
configured. JSON downloads contain financial amounts, so users should store them
privately. Opening a new session loses unsaved answers. Save before leaving.

### Inflation conversion and regulatory scope

The requested model defaults to 2.5% price inflation and uses it throughout the
today's-dollar conversion. ASIC's default conversion under its instrument uses
3.7% before retirement and 2.5% in retirement, unless user-input assumptions
apply. This prototype retains the requested price-based model and explicitly
discloses the difference. It should not be described as meeting ASIC relief
conditions without a separate assessment.

- [ASIC RG 276](https://asic.gov.au/regulatory-resources/find-a-document/regulatory-guides/rg-276-superannuation-forecasts-calculators-and-retirement-estimates/)
- [2024 amendment to the conversion defaults](https://www.legislation.gov.au/F2024L01117/asmade/2024-09-10/text/original/epub/OEBPS/document_1/document_1.html)
- [ASFA June 2026 budgets](https://www.superannuation.asn.au/media-release/asfa-retirement-standard-retirees-living-costs-rising-faster-than-inflation-as-power-healthcare-insurance-bills-climb/)

## Pension engine usage

Run from the `retirement_planner` folder, or import from the UI:

```python
from engine.age_pension import estimate_age_pension

estimate = estimate_age_pension(
    age=68,
    partner_age=65,
    homeowner=True,
    financial_assets=200_000,
    non_financial_assets=100_000,
    other_assessable_annual_income=0,
)
print(estimate.annual_pension)
print(estimate.limiting_test)
```

Amounts are combined nominal household dollars. Financial assets are included
in BOTH asset assessment and income deeming; non-financial assets are included
only in the assets test. Other assessable annual income excludes interest,
dividends and withdrawals already covered by deeming, and excludes Age Pension
itself. Include assessable rental income under Centrelink rules, not simply gross
rent. The result is before income tax.

Pass assessable amounts after exclusions: omit the principal home and exempt
younger-partner accumulation super; only permitted debt deductions apply. The
engine cannot derive these exclusions from a combined super balance. The later
projection must disclose a partner allocation assumption for mixed-age couples.
It assumes residence/claim eligibility. No Work Bonus, Rent Assistance, overseas,
transitional, grandfathered income-stream or illness-separated rules are modeled.
Continuous tapers omit Centrelink rounding and detailed supplement treatment.
Rates stay at the reviewed snapshot; indexation belongs in the projection engine.

Official references (reviewed 11 October 2026):

- [Maximum rates](https://www.servicesaustralia.gov.au/how-much-age-pension-you-can-get)
- [Assets thresholds](https://www.servicesaustralia.gov.au/assets-test-for-age-pension)
- [Income test](https://www.servicesaustralia.gov.au/income-test-for-age-pension)
- [Deeming](https://www.servicesaustralia.gov.au/deeming?context=22526)
- [Asset taper](https://guides.dss.gov.au/social-security-guide/4/2/3)
- [Super assessment](https://www.servicesaustralia.gov.au/superannuation)

## Projection usage

```python
from engine.projection import (
    Household, project, todays_dollars, sustainable_income, money_lasts_until,
)

household = Household()  # sensible starting inputs, no identifying information
nominal = project(household)
real = todays_dollars(nominal)
income = sustainable_income(household)
first_gap_age = money_lasts_until(nominal)
print(income.annual_income, income.feasible)
```

`Household` is an immutable set of combined household inputs. `Assumptions` in
`config.py` holds editable rates, allocations and other modeling choices; use
`dataclasses.replace` to create a changed scenario. No data is written to disk.
`project` returns a pandas DataFrame; rows show a full year starting at the given
age and year-end balances. The final row funds the entire year starting at life
expectancy. Couples run until the younger partner reaches that age, without a
death/survivor transition. Both retire when the primary person reaches the chosen
retirement age. The onboarding will require a future retirement age, although the
engine permits retirement immediately for already-retired examples.

Salary grows with wages. Employer super and accepted salary sacrifice are taxed
at 15%; after-tax contributions are paid out of household cash flow. Salary,
salary sacrifice and contributions are allocated using the primary income share;
initial super uses the primary super share. Both shares default to 50% for couples.
Voluntary contributions are limited to per-person modeled caps; the DataFrame
reports actual and rejected amounts, so the UI must display a warning when any
are rejected. Employer contributions exceeding the cap remain in super and produce warnings rather than errors. Salary sacrifice is trimmed first. The cap follows cumulative wage growth, rounded down in $2,500 steps without falling below the initial cap. Excess contributions are added to individual taxable income with a non-refundable 15% offset; additional tax is paid outside super. Release elections and interaction with the non-concessional cap are excluded.
No carry-forward/bring-forward rules are implemented. Personal after-tax contributions
stop from age 75, and non-concessional eligibility uses opening modeled super
against the general transfer cap (a simplified proxy for prior-year eligibility).

Super receives its annual return before end-of-year contributions/withdrawals.
Accumulation uses return × (1 − 10% effective earnings tax) − fees. Retired super
uses return − fees after access at age 60, assuming a condition of release is met
and a taxed super fund. The general transfer cap is applied per person once on
starting a modeled pension. Excess remains in accumulation; pension investment
growth may exceed the transfer cap. Minimum withdrawals use opening pension
balances and full-year age bands; excess withdrawals are saved outside super.
Remaining spending gaps use cash, investments, then accessible super. Property
is retained and cannot directly fund a spending gap.

Living spending/retirement targets, child costs, rent and continuing other income
grow with inflation. Child costs are ADDITIONAL to entered living spending; avoid
including them twice. Cash interest is included in taxable income, not also added
to the balance. Investment return is an AFTER-TAX total-return approximation;
dividend yields, franking credits, realisations and capital gains tax are not
modeled separately. Rent deducts an editable 20% expense allowance. Mortgage
is assumed to be secured on the exempt home and does not reduce assessable
investment property. Other debt uses editable 8% interest and five-year repayment
defaults. Both loans amortise monthly; debt service is prioritized and unpaid
repayments remain in the debt balance. No new borrowing or penalty interest on
arrears is added. A shortfall indicates this cash-flow path cannot be funded.

Pension assessment uses opening assets, salary, net rent and other income.
Retirement pension balances are assessable; under-67 accumulation is exempt.
Rates AND thresholds grow at the editable pension-indexation assumption (2.5%
default), not a prediction of future government policy. The concessional cap
uses wage growth as an AWOTE proxy, rounded down in $2,500 steps. Tax brackets
and other super caps remain at the 2026–27 snapshot: scheduled future tax changes are not modeled.
The family home is excluded from `net_worth` because no home value is collected.
All tax/pension exclusions described above still apply, including Division 293/296.
DataFrame `attrs['limitations']` provides disclosure text; the UI explains these
limits alongside results.

`money_lasts_until` returns the first retirement age with an unmet expense, or
`None` if the full horizon is funded. It does not claim property or every asset
is exhausted, and a later pension may restore spending coverage.
`sustainable_income` returns today's-dollar annual living spending, a feasible
flag, and a verified feasible/infeasible search bracket (within $1 by default).
It includes debt and child costs on top and assumes no terminal estate target.
Any pre-retirement deficit, or a deficit even at zero retirement spending, returns
`feasible=False`. The search ceiling is explicitly reported as a lower bound if
reached. These are deterministic estimates, not guaranteed incomes.

Super source references:

- [ATO super access conditions](https://www.ato.gov.au/law/view/document?DocID=REG%2F19940057%2FSch1)
- [Minimum pension percentages, Schedule 5](https://www.legislation.gov.au/F1997B02633/2026-04-21/2026-04-21/text)
- [CSC 2026–27 cap summary](https://www.csc.gov.au/advisers/news/2026-05-federal-budget-2026-27)

Validation: 164 pytest cases pass across engines, JSON handling and Streamlit
AppTest interaction tests. These are headless behavior checks, not browser
screenshot or mobile layout verification.

Phase 1 features are implemented. Phases 2–4 remain unimplemented, as requested:
no income-source comparison chart, milestones, nudges, what-if sliders,
Monte Carlo simulations, side-by-side scenarios or PDF export.
