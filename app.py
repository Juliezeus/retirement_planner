"""Streamlit UI only; calculations and JSON validation live in separate modules."""

from dataclasses import asdict, replace
from math import floor
import re

import plotly.graph_objects as go
import streamlit as st

from config import (
    ASFA_ANNUAL_SPENDING, ASFA_QUARTER, ASFA_SOURCE, Assumptions, CLOSE_RATIO,
    CONCESSIONAL_CAP, DEFAULT_ASSUMPTIONS, DISCLAIMER, FINANCIAL_YEAR,
    MAX_CHILDREN, MAX_INPUT_MONEY, NON_CONCESSIONAL_CAP, PENSION_SOURCES,
    RATES_REVIEW_DATE, SUPER_GUARANTEE_RATE, TRANSFER_BALANCE_CAP,
    AGE_PENSION_AGE, PRESERVATION_AGE, CONTRIBUTIONS_TAX_RATE,
    ACCUMULATION_EARNINGS_TAX_RATE, RETIREMENT_EARNINGS_TAX_RATE,
    MEDICARE_LEVY_RATE, PENSION_ASSET_TAPER_PER_DOLLAR, PENSION_INCOME_TAPER,
)
from engine.projection import Household, project, sustainable_income, money_lasts_until, todays_dollars
from scenarios import dump_scenario, load_scenario, validate_inputs

STEPS = ("About you", "Family", "Income", "Super", "Assets and debts", "Retirement goal")
RATE_FIELDS = {
    "inflation": ("Cost-of-living growth", "Annual price growth. Today's dollars remove this growth to show current buying power."),
    "wage_growth": ("Salary growth", "Annual salary increases before retirement."),
    "super_return": ("Super return before fees and tax", "A steady annual investment return, not a guarantee. Actual returns vary."),
    "super_fees": ("Super fees", "Annual fees as a share of your super. Insurance premiums are not modeled separately."),
    "investment_return": ("Shares and funds return after tax", "Total return including growth and dividends after tax. No separate capital gains tax calculation."),
    "cash_return": ("Cash interest before tax", "Annual interest on bank savings; simplified income tax is deducted."),
    "property_growth": ("Investment property growth", "Annual growth in value. The property is retained, not sold to pay for living costs."),
    "surplus_investment_share": ("Surplus saved into shares and funds", "Share of money left after costs saved into investments. The rest goes to cash."),
    "primary_income_share": ("Your share of household income", "For couples, assigns salary, other income and contributions to you for individual tax. The remainder belongs to your partner."),
    "primary_super_share": ("Your share of the starting super balance", "For couples, determines each person's super access and pension assessment. The remainder belongs to your partner."),
    "rental_expense_share": ("Rental expense allowance", "Share of gross rent deducted for expenses. A simplified estimate of net assessable rent."),
    "other_debt_rate": ("Other debts interest rate", "Annual rate used to estimate repayments on credit cards and other debts."),
    "pension_indexation": ("Future pension rate and threshold growth", "Assumed annual increases in pension rates and limits, not a promise of future government policy."),
}
NONNEGATIVE_RATES = {"super_fees", "surplus_investment_share", "primary_income_share",
                    "primary_super_share", "rental_expense_share", "other_debt_rate"}


def currency(value: float, decimals: int = 0) -> str:
    """Format AUD without raw floats."""
    return f"${value:,.{decimals}f}"


def initialize() -> None:
    """Initialize per-session values; scenario data never uses a shared cache."""
    st.session_state.setdefault("draft", asdict(Household()))
    st.session_state.setdefault("assumptions", DEFAULT_ASSUMPTIONS)
    st.session_state.setdefault("screen", "landing")
    st.session_state.setdefault("step", 0)
    st.session_state.setdefault("upload_generation", 0)


def current_household() -> Household:
    values = dict(st.session_state.draft)
    values["children_ages"] = tuple(values["children_ages"])
    return Household(**values)


def clear_widget_inputs() -> None:
    """Clear temporary widget state before rendering imported answers."""
    for key in list(st.session_state):
        if str(key).startswith(("input_", "assumption_")):
            del st.session_state[key]
    st.session_state.pop("calculation", None)


def parse_money(text: str) -> float:
    """Accept whole dollars or cents with optional currency separators."""
    cleaned = text.strip().removeprefix("$").replace(",", "").strip()
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", cleaned) or float(cleaned) > MAX_INPUT_MONEY:
        raise ValueError(f"Enter a dollar amount such as $50,000 or $0, up to {currency(MAX_INPUT_MONEY)}.")
    return float(cleaned)


def money_input(field: str, label: str, tooltip: str, errors: list[str]) -> None:
    d = st.session_state.draft
    decimals = 2 if round(d[field], 2) != round(d[field]) else 0
    text = st.text_input(label, value=currency(d[field], decimals), key=f"input_{field}", help=tooltip)
    try:
        d[field] = parse_money(text)
    except ValueError as exc:
        errors.append(f"{label}: {exc}")


def integer_input(field: str, label: str, tooltip: str, minimum: int, maximum: int) -> None:
    d = st.session_state.draft
    d[field] = st.number_input(label, minimum, maximum, value=int(d[field]), step=1,
                                key=f"input_{field}", help=tooltip)


def scenario_tools() -> None:
    """Download/upload in memory; explicit loading replaces the draft."""
    with st.sidebar:
        st.subheader("Your scenario")
        st.caption("No names or contact details. Answers stay only in this session's memory. Download to keep them; a new session starts fresh.")
        try:
            if st.session_state.screen == "wizard" and st.session_state.get("draft_errors"):
                raise ValueError("Correct the current step before saving.")
            data = dump_scenario(current_household(), st.session_state.assumptions)
            st.download_button("Save scenario as JSON", data, file_name="retirement-scenario.json",
                mime="application/json", on_click="ignore",
                help="Save your answers and assumptions to your device. The file contains financial information; keep it private.")
        except ValueError:
            st.caption("Correct your answers before saving this scenario.")
        upload = st.file_uploader("Open a saved scenario", type=["json"], max_upload_size=1,
            key=f"scenario_upload_{st.session_state.upload_generation}",
            help="Choose an app JSON download. It is validated in memory and never saved to disk.")
        if st.button("Load selected scenario", disabled=upload is None, key="load_scenario",
                     help="Replace current answers with this file, then review them before calculating."):
            try:
                h, a = load_scenario(upload.getvalue())
                clear_widget_inputs()
                st.session_state.draft = asdict(h)
                st.session_state.assumptions = a
                st.session_state.screen, st.session_state.step = "wizard", 0
                st.session_state.upload_generation += 1
                st.session_state.notice = "Scenario loaded. Review your answers, then see your results."
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if st.button("Clear session and start again", key="reset_scenario",
            help="Clear this session's answers and calculations. Download first to keep a copy."):
            generation = st.session_state.upload_generation + 1
            st.session_state.clear()
            st.session_state.upload_generation = generation
            st.rerun()


def landing() -> None:
    st.caption("AUSTRALIAN HOUSEHOLD RETIREMENT PLANNER")
    st.title("Plan your retirement with more confidence")
    st.markdown("Explore what your household could spend in retirement, how long your money may cover your costs, and the assumptions behind the estimate.")
    with st.container(border=True):
        st.markdown("**About 5 minutes · Six guided steps**")
        st.markdown("Have rough figures for your income, super, savings and debts handy. Estimates are fine to get started. Couples enter combined amounts.")
        st.info(DISCLAIMER)
        if st.button("Get started", type="primary", key="get_started"):
            st.session_state.screen = "wizard"
            st.rerun()
    st.caption("No sign-up. No identifying information. Your answers stay in session memory unless you download a scenario file.")


def about_you(errors: list[str]) -> None:
    d = st.session_state.draft
    was_couple = d["partner_age"] is not None
    couple = st.radio("Who are you planning for?", ["Just me", "Me and my partner"],
        index=int(was_couple), key="input_household_type",
        help="We model one household. Couples enter combined money amounts but each person's age.") == "Me and my partner"
    if couple != was_couple:
        old_kind, new_kind = ("couple", "single") if was_couple else ("single", "couple")
        for level in ("modest", "comfortable"):
            if d["retirement_income"] == ASFA_ANNUAL_SPENDING[old_kind][level]:
                d["retirement_income"] = float(ASFA_ANNUAL_SPENDING[new_kind][level])
                st.session_state.pop("input_retirement_income", None)
                break
        d["partner_age"] = 45 if couple else None
        st.session_state.pop("input_partner_age", None)
    integer_input("age", "Your age", "Age now in whole years. No date of birth is collected.", 18, 119)
    if couple:
        integer_input("partner_age", "Your partner's age", "Age now. Super and Age Pension access depend on each person's age.", 18, 119)
        st.caption("Both partners stop work when you reach the retirement age below. Income and starting super are split 50/50 by default; edit the splits in results.")
    integer_input("retirement_age", "Your target retirement age", "When household salary stops. Must be older than your age now. Early retirement needs savings outside super until access is available.", 19, 120)
    d["homeowner"] = st.radio("Do you own the home you live in?", ["Yes", "No"],
        index=0 if d["homeowner"] else 1, key="input_homeowner",
        help="The family home is excluded from pension assets. Non-homeowners have different limits.") == "Yes"
    a = st.session_state.assumptions
    longevity = st.number_input("Plan until age", 18, 120, value=a.life_expectancy, step=1,
        key="input_planning_age", help="A planning horizon, not a lifespan prediction. Couples are funded until the younger partner reaches it.")
    st.session_state.assumptions = replace(a, life_expectancy=longevity)
    if d["retirement_age"] <= d["age"]:
        errors.append("Choose a retirement age older than your current age.")
    if max(d["age"], d["partner_age"] or 0, d["retirement_age"]) > longevity:
        errors.append("Choose a planning age at least as high as both current ages and your retirement age.")


def family(errors: list[str]) -> None:
    d = st.session_state.draft
    count = st.number_input("Children you financially support under 18", 0, MAX_CHILDREN,
        value=len(d["children_ages"]), step=1, key="input_child_count",
        help="Annual costs are added for each child until 18. Adult dependants are not modeled.")
    old = list(d["children_ages"])
    d["children_ages"] = tuple(st.number_input(f"Child {i + 1} age", 0, 17,
        value=int(old[i]) if i < len(old) else 5, step=1, key=f"input_child_{i}",
        help="Age now in whole years. No name or date of birth is needed.") for i in range(count))
    st.caption(f"We add {currency(st.session_state.assumptions.annual_child_cost)} a year per child until 18, rising with prices. Exclude child costs from living spending later to avoid counting them twice.")


def income(errors: list[str]) -> None:
    money_input("gross_salary", "Household salary before tax, per year", "Combined salary before tax and salary sacrifice, excluding employer super. Stops at retirement.", errors)
    money_input("other_income", "Other household income, per year", "Before-tax income that continues in retirement. Exclude salary, bank interest, dividends, super withdrawals, Age Pension and property rent.", errors)


def super_step(errors: list[str]) -> None:
    money_input("super_balance", "Combined super balance", f"Total household superannuation savings. Access assumes retirement from {PRESERVATION_AGE} and a taxed fund.", errors)
    money_input("salary_sacrifice", "Extra salary sacrifice, per year", f"Salary paid into super before income tax, on top of employer super. We deduct {CONTRIBUTIONS_TAX_RATE:.0%} contributions tax and apply modeled per-person caps.", errors)
    money_input("after_tax_contributions", "After-tax super contributions, per year", "Money from take-home pay or savings put into super. Stops at retirement; modeled caps and eligibility apply.", errors)
    st.caption(f"Employer super is {SUPER_GUARANTEE_RATE:.0%} of salary. Before-tax cap: {currency(CONCESSIONAL_CAP)} per person including employer super. After-tax cap: {currency(NON_CONCESSIONAL_CAP)}. Unaccepted amounts remain outside super and are reported in results.")
    if st.session_state.draft["salary_sacrifice"] > st.session_state.draft["gross_salary"]:
        errors.append("Extra salary sacrifice cannot exceed household salary.")


def assets(errors: list[str]) -> None:
    for field, label, tooltip in (
        ("cash", "Cash and bank savings", "Combined bank balances available for spending. Do not include again under investments."),
        ("investments", "Shares, ETFs and managed funds", "Combined value outside super. An ETF is a fund traded on a stock exchange. Exclude cash and property."),
        ("property_value", "Investment property value", "Gross market value excluding the family home. Property is retained throughout retirement, not automatically sold."),
        ("annual_rent", "Gross rent received, per year", f"Rent before expenses. The current {st.session_state.assumptions.rental_expense_share:.0%} expense allowance is deducted for a simplified net-rent estimate. Edit it in results."),
        ("mortgage_balance", "Home mortgage remaining", "Debt secured on your family home. Investment-property borrowing is unsupported in this first model; do not enter it here."),
    ):
        money_input(field, label, tooltip, errors)
    d = st.session_state.draft
    d["mortgage_rate"] = st.number_input("Home mortgage interest rate (%)", 0.0, 100.0,
        value=d["mortgage_rate"] * 100, step=.1, format="%.2f", key="input_mortgage_rate",
        help="Annual rate assumed constant. The model calculates monthly principal-and-interest repayments.") / 100
    integer_input("mortgage_years", "Years left on your home mortgage", "Remaining repayment term. At least one year is needed for an outstanding balance.", 0, 100)
    a = st.session_state.assumptions
    money_input("other_debts", "Other debts remaining", f"Credit cards and other debt. Currently repaid over {a.other_debt_years} years at {a.other_debt_rate:.0%}; edit both assumptions in results.", errors)
    if d["annual_rent"] and not d["property_value"]:
        errors.append("Enter a property value if you receive rent.")
    if d["mortgage_balance"] and not d["mortgage_years"]:
        errors.append("Enter at least one year remaining on your mortgage.")
    if d["mortgage_balance"] and not d["homeowner"]:
        errors.append("This model supports a mortgage on your own home only. Remove it or update homeownership.")


def retirement_goal(errors: list[str]) -> None:
    money_input("annual_spending", "Current living spending, per year", "After-tax living costs, excluding child costs, loan repayments and extra super contributions; these are added separately. Include rent if you rent your home.", errors)
    kind = "couple" if st.session_state.draft["partner_age"] is not None else "single"
    budgets = ASFA_ANNUAL_SPENDING[kind]
    st.markdown("**Choose a starting budget, then adjust it to suit you.**")
    with st.container(horizontal=True):
        for level in ("modest", "comfortable"):
            if st.button(f"{level.capitalize()} · {currency(budgets[level])}", key=f"goal_{level}",
                help="Use ASFA's annual budget as a starting point, not a recommendation for your circumstances."):
                st.session_state.draft["retirement_income"] = float(budgets[level])
                st.session_state.pop("input_retirement_income", None)
    money_input("retirement_income", "Retirement living income goal, per year", "Annual after-tax household living budget in today's buying power. Child costs and debt repayments are added on top. $0 means no living budget.", errors)
    st.caption(f"ASFA {ASFA_QUARTER} budgets are for homeowners aged 65–84. Renters may need more for housing. Modest is a basic lifestyle; Comfortable allows more discretionary spending.")
    st.markdown(f"[About the ASFA budget figures]({ASFA_SOURCE})")


def wizard() -> None:
    step = st.session_state.step
    st.title("Your household, step by step")
    st.progress((step + 1) / len(STEPS), text=f"Step {step + 1} of {len(STEPS)} · {STEPS[step]}")
    st.subheader(STEPS[step])
    errors: list[str] = []
    with st.container(border=True):
        (about_you, family, income, super_step, assets, retirement_goal)[step](errors)
    for error in errors:
        st.error(error)
    st.session_state.draft_errors = errors
    with st.container(horizontal=True):
        if st.button("Back", key="wizard_back"):
            if step == 0:
                st.session_state.screen = "landing"
            else:
                st.session_state.step -= 1
            st.rerun()
        if st.button("See my results" if step == 5 else "Next", type="primary", disabled=bool(errors), key="wizard_next"):
            if step < 5:
                st.session_state.step += 1
            else:
                try:
                    h = current_household()
                    validate_inputs(h, st.session_state.assumptions)
                    if h.retirement_age <= h.age:
                        raise ValueError("Choose a retirement age older than your current age.")
                    st.session_state.screen = "results"
                except ValueError as exc:
                    st.error(str(exc))
                    return
            st.rerun()
    st.caption("Go back to change any answer. For couples, all dollar figures are combined.")


def assumptions_panel(h: Household) -> None:
    """Batch edits to avoid calculating every time a field changes."""
    with st.expander("Assumptions used — view or edit"):
        a = st.session_state.assumptions
        st.markdown("Steady yearly assumptions, not predictions. Edit and select **Apply assumptions** to calculate again. Income and super allocation percentages are used for couples only.")
        with st.form("assumptions_form"):
            values = asdict(a)
            for field, (label, tooltip) in RATE_FIELDS.items():
                values[field] = st.number_input(f"{label} (%)", 0.0 if field in NONNEGATIVE_RATES else -99.0,
                    100.0, value=float(values[field] * 100), step=.1, format="%.2f",
                    key=f"assumption_{field}", help=tooltip) / 100
            values["life_expectancy"] = st.number_input("Plan until age", 18, 120,
                value=a.life_expectancy, step=1, key="assumption_life_expectancy",
                help="Fund the whole year starting at this age. Couples run until the younger partner reaches it; no death or survivor change is modeled.")
            child_cost = st.text_input("Annual cost per child", value=currency(a.annual_child_cost, 2 if round(a.annual_child_cost, 2) != round(a.annual_child_cost) else 0),
                key="assumption_child_cost", help="Extra cost per child until age 18, before future price increases.")
            values["other_debt_years"] = st.number_input("Years to repay other debts", 1, 100,
                value=max(1, a.other_debt_years), step=1, key="assumption_other_debt_years",
                help="Repayment term for the combined other-debt balance.")
            submitted = st.form_submit_button("Apply assumptions", type="primary")
        if submitted:
            try:
                values["annual_child_cost"] = parse_money(child_cost)
                candidate = Assumptions(**values)
                validate_inputs(h, candidate)
                st.session_state.assumptions = candidate
                st.session_state.pop("calculation", None)
                st.rerun()
            except ValueError as exc:
                st.error(f"Assumptions were not applied: {exc}")
        statutory_assumptions()


def statutory_assumptions() -> None:
    """Disclose fixed legislated inputs separately from editable model choices."""
    from config import (PENSION_ASSET_FREE_AREA, PENSION_INCOME_FREE_AREA_FORTNIGHTLY,
        DEEMING_THRESHOLD, DEEMING_LOWER_RATE, DEEMING_UPPER_RATE,
        PENSION_MAX_FORTNIGHTLY, MINIMUM_DRAWDOWN_RATES, RESIDENT_TAX_BRACKETS)
    st.caption(f"Model year {FINANCIAL_YEAR} · Rates reviewed {RATES_REVIEW_DATE}. Super caps and tax brackets stay fixed in future years.")
    st.markdown(f"Employer super **{SUPER_GUARANTEE_RATE:.0%}** · Contributions tax **{CONTRIBUTIONS_TAX_RATE:.0%}** · Effective accumulation earnings tax **{ACCUMULATION_EARNINGS_TAX_RATE:.0%}** · Retirement-phase earnings tax **{RETIREMENT_EARNINGS_TAX_RATE:.0%}**. Before-tax cap **{currency(CONCESSIONAL_CAP)}**, after-tax cap **{currency(NON_CONCESSIONAL_CAP)}**, retirement transfer cap **{currency(TRANSFER_BALANCE_CAP)}**, all per person.")
    st.markdown(f"Super access assumes eligible retirement from **{PRESERVATION_AGE}**; Age Pension starts from **{AGE_PENSION_AGE}**. Minimum yearly pension withdrawals:")
    st.markdown("; ".join(f"{'under ' + str(MINIMUM_DRAWDOWN_RATES[i + 1][0]) if low == 0 else str(low) + ('+' if i == len(MINIMUM_DRAWDOWN_RATES) - 1 else '–' + str(MINIMUM_DRAWDOWN_RATES[i + 1][0] - 1))}: **{rate:.0%}**" for i, (low, rate) in enumerate(MINIMUM_DRAWDOWN_RATES)))
    for kind in ("single", "couple"):
        st.markdown(f"**{kind.capitalize()}** pension maximum: {currency(PENSION_MAX_FORTNIGHTLY[kind], 2)} per fortnight {'combined' if kind == 'couple' else ''}. Asset free areas: homeowner {currency(PENSION_ASSET_FREE_AREA[kind, True])}, non-homeowner {currency(PENSION_ASSET_FREE_AREA[kind, False])}. Income free area: {currency(PENSION_INCOME_FREE_AREA_FORTNIGHTLY[kind])} per fortnight. Deeming threshold: {currency(DEEMING_THRESHOLD[kind])}.")
    st.markdown(f"Assets above the free area reduce the single or combined pension by {currency(PENSION_ASSET_TAPER_PER_DOLLAR * 1000)} per fortnight per $1,000. Income above the free area reduces it by {PENSION_INCOME_TAPER * 100:.0f} cents per dollar. Deemed income is the assumed return Centrelink uses: **{DEEMING_LOWER_RATE:.2%}** below the threshold and **{DEEMING_UPPER_RATE:.2%}** above it. The lower means-test result is used.")
    st.markdown("Tax bands: " + "; ".join(f"{currency(low)}–{currency(high) if high != float('inf') else 'and above'}: {rate:.0%}" for low, high, rate in RESIDENT_TAX_BRACKETS) + f". Plus a simplified **{MEDICARE_LEVY_RATE:.0%}** Medicare levy; offsets and low-income reductions are excluded.")
    st.markdown(f"[Official pension rates]({PENSION_SOURCES['rates']}) · [Income test]({PENSION_SOURCES['income']}) · [Assets test]({PENSION_SOURCES['assets']})")
    st.caption("If only one partner is old enough for Age Pension, couple thresholds still apply and only that partner's half of the combined estimated payment is paid.")
    st.caption("Today's dollars use the price-growth assumption across the entire projection. This prototype retains the requested 2.5% default, which differs from ASIC's prescribed default accumulation-phase conversion. It has not been assessed for regulatory compliance.")


def wealth_chart(frame, retirement_age: int, future: bool) -> go.Figure:
    """Stack assets and overlay wealth after debts."""
    figure = go.Figure()
    for field, name, color in (("super", "Super", "#24756B"),
        ("investments", "Shares and funds", "#82B6A7"), ("cash", "Cash", "#C7DCD5"),
        ("property", "Investment property", "#DAC9A5")):
        figure.add_trace(go.Scatter(x=frame.age, y=frame[field], name=name, mode="lines",
            stackgroup="assets", line=dict(width=1, color=color),
            hovertemplate="Age %{x}<br>%{fullData.name}: $%{y:,.0f}<extra></extra>"))
    figure.add_trace(go.Scatter(x=frame.age, y=frame.net_worth, name="Net wealth after debts",
        mode="lines", line=dict(color="#273B47", width=2, dash="dot"),
        hovertemplate="Age %{x}<br>Net wealth: $%{y:,.0f}<extra></extra>"))
    figure.add_vline(x=retirement_age, line_dash="dash", line_color="#536C66",
                    annotation_text="Retirement", annotation_position="top left")
    figure.update_layout(height=420, margin=dict(l=10, r=10, t=35, b=10),
        xaxis_title="Your age", yaxis_title="Future dollars" if future else "Today's dollars",
        yaxis_tickprefix="$", yaxis_tickformat=",.0f", hovermode="x unified",
        legend=dict(orientation="h", y=-.2), paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)")
    return figure


def results() -> None:
    st.title("Your retirement picture")
    st.caption("A household estimate in today's buying power. Changing the assumptions can change the result.")
    if st.button("Edit my answers", key="edit_answers"):
        st.session_state.screen, st.session_state.step = "wizard", 0
        st.rerun()
    h = current_household()
    assumptions_panel(h)
    a = st.session_state.assumptions
    try:
        fingerprint = dump_scenario(h, a)
        cached = st.session_state.get("calculation")
        if cached is None or cached[0] != fingerprint:
            with st.spinner("Working through each year of your plan…"):
                projection, sustainable = project(h, a), sustainable_income(h, a)
            st.session_state.calculation = (fingerprint, projection, sustainable)
        _, projection, sustainable = st.session_state.calculation
    except (ValueError, OverflowError, ZeroDivisionError) as exc:
        st.error(f"We couldn't calculate this scenario: {exc}")
        st.markdown("Use **Edit my answers** or the assumptions panel to adjust your figures. No reliable income estimate is available for these inputs.")
        st.info(DISCLAIMER)
        return
    real, first_gap = todays_dollars(projection), money_lasts_until(projection)
    pre_gaps = projection[(~projection.retired) & (projection.shortfall > .01)]
    if not sustainable.feasible:
        st.error("🔴 Gap — the plan cannot cover all costs, even with no retirement living budget.")
        st.markdown("Check current spending, debts and contributions before relying on a retirement income estimate.")
    else:
        st.subheader(f"You can afford an estimated {currency(floor(sustainable.annual_income))} a year in retirement (today's dollars) vs your goal of {currency(h.retirement_income)}")
        ratio = sustainable.annual_income / h.retirement_income if h.retirement_income else 1.0
        if ratio >= 1 and first_gap is None:
            st.success("🟢 On track — your goal is covered under these assumptions.")
        elif ratio >= CLOSE_RATIO:
            st.warning("🟠 Close — sustainable income is within 10% of your goal.")
        else:
            st.error("🔴 Gap — the estimate is more than 10% below your goal.")
        if "ceiling" in sustainable.reason:
            st.warning("The solver reached its limit. The headline is a lower bound, not a maximum.")
        st.caption("Annual living budget after modeled tax. Child costs and debt repayments are funded on top. This is an estimate, not a guaranteed or recommended income.")
    if not pre_gaps.empty:
        st.warning(f"A funding gap starts before retirement, at your age {int(pre_gaps.iloc[0].age)}. Some modeled costs cannot be paid.")
    if first_gap is None:
        last = projection.iloc[-1]
        ages = f"your age {int(last.age)}" if h.partner_age is None else f"your partner's age {int(last.partner_age)} and your age {int(last.age)}"
        st.markdown(f"**Your money covers your goal through {ages}**, the end of this projection." if pre_gaps.empty else f"**No retirement-year shortfall through {ages}**, but the earlier gap makes this plan unfunded.")
    else:
        st.markdown(f"**Your money lasts until age {first_gap} under your current goal.** The first retirement funding shortfall occurs in the year starting at that age.")
    rejected = real.rejected_contributions.max()
    if rejected > .01:
        st.warning(f"Some voluntary super contributions could not be accepted under modeled caps or eligibility. The largest yearly unaccepted amount is {currency(rejected)} in today's dollars; it stays outside super.")
    st.divider()
    st.subheader("Your assets over time")
    future = st.toggle("Show future dollars", value=False, key="future_dollars",
        help="Off: today's buying power. On: modeled future amounts including price growth. The headline always stays in today's dollars.")
    st.plotly_chart(wealth_chart(projection if future else real, h.retirement_age, future),
        width="stretch", config={"displayModeBar": False},
        alt="Stacked household assets by age, with retirement marked and net wealth after debts overlaid.")
    st.caption("Year-end balances. Areas show assets; the dotted line deducts debts. Family home value is excluded. Retained investment property cannot directly fund a spending gap.")
    with st.expander("How to read this estimate"):
        st.markdown("Today's dollars remove price growth to show current buying power; future dollars include it. A funding gap does not necessarily mean every asset is exhausted. A later pension may restore coverage after a gap.")
        st.markdown("Couples use the editable income and super allocations above. Both retire together and stay a couple throughout. There is no death or survivor transition. The younger partner's planning age sets the horizon.")
        st.markdown("Returns are steady assumptions, not forecasts. Shares use an after-tax total return; franking credits and separate capital gains tax are excluded. Super withdrawals assume a taxed fund and eligible retirement access.")
        st.markdown("Age Pension residence and claim eligibility are assumed. Work Bonus, Rent Assistance, overseas rules, gifting and special income streams are excluded. Tax offsets, Medicare low-income adjustments, HELP and extra high-income/high-balance super taxes are excluded. Future tax brackets and super caps stay at the 2026–27 snapshot.")
        st.markdown("Child costs, debt repayments and extra contributions are added on top of living spending. The solver requires every year to be funded and does not preserve an inheritance target. The model never automatically sells property or borrows to fund gaps.")
    st.info(DISCLAIMER)


st.set_page_config(page_title="Retirement planner", page_icon="🌿", layout="centered")
initialize()
notice = st.session_state.pop("notice", None)
if notice:
    st.success(notice)
{"landing": landing, "wizard": wizard, "results": results}[st.session_state.screen]()
# After main input rendering, so downloads contain the latest valid answers.
scenario_tools()
