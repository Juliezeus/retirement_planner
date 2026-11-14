"""Exercise real wizard navigation, validation, results and session isolation."""

from dataclasses import asdict, replace
from pathlib import Path

from streamlit.testing.v1 import AppTest

from config import ASFA_ANNUAL_SPENDING, DEFAULT_ASSUMPTIONS
from engine.projection import (
    Household, LifestyleGoal, money_lasts_until, project, sustainable_income,
    todays_dollars,
)
from results_report import build_results_pdf

APP = Path(__file__).resolve().parents[1] / "app.py"


def open_app() -> AppTest:
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    return app


def finish_wizard(app: AppTest) -> AppTest:
    app.button(key="get_started").click().run()
    for _ in range(7):
        app.button(key="wizard_next").click().run()
        assert not app.exception
    return app


def test_complete_single_flow_and_display_toggle_preserves_headline() -> None:
    app = finish_wizard(open_app())
    assert app.title[0].value == "Your retirement picture"
    assert app.download_button(key="results_pdf").label == "Download results as PDF"
    assert app.success
    assert any("licensed financial adviser" in x.value for x in app.info)
    headline = next(x.value for x in app.subheader if "You can afford" in x.value)
    calculation = app.session_state["calculation"]
    app.toggle(key="future_dollars").set_value(True).run()
    assert not app.exception
    assert next(x.value for x in app.subheader if "You can afford" in x.value) == headline
    assert app.session_state["calculation"][2] == calculation[2]


def test_results_pdf_contains_a_valid_pdf_document() -> None:
    household = replace(
        Household(),
        partner_age=43,
        partner_retirement_age=63,
        lifestyle_goals=(
            LifestyleGoal("Holiday", 5_000, "Every year", 67, 72),
        ),
    )
    projection = todays_dollars(project(household))
    pdf = build_results_pdf(
        household, DEFAULT_ASSUMPTIONS, projection,
        sustainable_income(household), money_lasts_until(projection),
    )
    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")


def test_couple_children_back_navigation_and_budget_pick() -> None:
    app = open_app()
    app.button(key="get_started").click().run()
    app.radio(key="input_household_type").set_value("Me and my partner").run()
    app.number_input(key="input_partner_age").set_value(42).run()
    app.button(key="wizard_next").click().run()
    app.number_input(key="input_child_count").set_value(2).run()
    app.number_input(key="input_child_0").set_value(7).run()
    app.number_input(key="input_child_1").set_value(12).run()
    app.button(key="wizard_next").click().run()
    app.text_input(key="input_gross_salary").set_value("$150,000").run()
    app.button(key="wizard_back").click().run()
    assert app.number_input(key="input_child_0").value == 7
    assert app.number_input(key="input_child_1").value == 12
    app.button(key="wizard_next").click().run()
    assert app.text_input(key="input_gross_salary").value == "$150,000"
    for _ in range(3):
        app.button(key="wizard_next").click().run()
    assert app.text_input(key="input_retirement_income").value == "$78,998"
    app.button(key="goal_modest").click().run()
    assert app.session_state["draft"]["retirement_income"] == ASFA_ANNUAL_SPENDING["couple"]["modest"]
    assert not app.exception


def test_couple_retirement_ages_and_already_retired_options() -> None:
    app = open_app()
    app.button(key="get_started").click().run()
    app.radio(key="input_household_type").set_value("Me and my partner").run()
    app.checkbox(key="input_already_retired").set_value(True).run()
    app.checkbox(key="input_partner_already_retired").set_value(True).run()
    assert app.session_state["draft"]["already_retired"]
    assert app.session_state["draft"]["partner_already_retired"]
    assert app.session_state["draft"]["retirement_age"] == app.session_state["draft"]["age"]
    assert app.session_state["draft"]["partner_retirement_age"] == app.session_state["draft"]["partner_age"]
    assert not app.exception


def test_second_workflow_tab_opens_retirement_budget_before_lifestyle_goals() -> None:
    app = open_app()
    app.button(key="get_started").click().run()
    app.button(key="workflow_tab_1").click().run()
    assert app.session_state["screen"] == "wizard"
    assert app.session_state["step"] == 5
    assert any(element.value == "Retirement budget" for element in app.subheader)
    assert app.text_input(key="input_retirement_income")
    assert len(app.multiselect) == 0
    app.button(key="wizard_next").click().run()
    assert app.session_state["step"] == 6
    assert any(element.value == "Lifestyle goals" for element in app.subheader)
    assert app.multiselect(key="input_lifestyle_categories")
    assert not app.exception


def test_holiday_goal_is_included_in_projection() -> None:
    app = open_app()
    app.button(key="get_started").click().run()
    app.number_input(key="input_age").set_value(54).run()
    app.number_input(key="input_retirement_age").set_value(55).run()
    for _ in range(6):
        app.button(key="wizard_next").click().run()
    app.multiselect(key="input_lifestyle_categories").set_value(["Holiday"]).run()
    app.number_input(key="input_goal_holiday_amount").set_value(5_000).run()
    app.number_input(key="input_goal_holiday_start_age").set_value(56).run()
    app.number_input(key="input_goal_holiday_finish_age").set_value(57).run()
    app.button(key="wizard_next").click().run()
    assert not app.exception
    _, projection, _ = app.session_state["calculation"]
    goal_costs = todays_dollars(projection).set_index("age").lifestyle_goal_costs
    assert goal_costs.loc[55] == 0
    assert goal_costs.loc[56] == 5_000
    assert goal_costs.loc[57] == 5_000
    assert goal_costs.loc[58] == 0


def test_investment_property_loan_inputs_flow_into_results() -> None:
    app = open_app()
    app.button(key="get_started").click().run()
    for _ in range(4):
        app.button(key="wizard_next").click().run()
    app.text_input(key="input_property_value").set_value("$800,000").run()
    app.text_input(key="input_annual_rent").set_value("$36,000").run()
    app.text_input(key="input_investment_loan_balance").set_value("$500,000").run()
    app.number_input(key="input_investment_loan_rate").set_value(6.25).run()
    assert app.session_state["draft"]["investment_loan_balance"] == 500_000
    assert app.session_state["draft"]["investment_loan_rate"] == .0625
    assert not app.exception


def test_invalid_retirement_age_and_currency_block_next() -> None:
    app = open_app()
    app.button(key="get_started").click().run()
    app.number_input(key="input_retirement_age").set_value(40).run()
    assert app.error and app.button(key="wizard_next").disabled
    app.number_input(key="input_retirement_age").set_value(65).run()
    app.button(key="wizard_next").click().run()
    app.button(key="wizard_next").click().run()
    app.text_input(key="input_gross_salary").set_value("not a number").run()
    assert app.error and app.button(key="wizard_next").disabled
    assert not app.exception


def test_edit_assumptions_recalculates_and_invalid_edits_do_not_apply() -> None:
    app = finish_wizard(open_app())
    old_income = app.session_state["calculation"][2].annual_income
    app.number_input(key="assumption_super_return").set_value(3.0)
    submit = next(x for x in app.button if x.label == "Apply assumptions")
    submit.click().run()
    assert not app.exception
    assert app.session_state["assumptions"].super_return == .03
    assert app.session_state["calculation"][2].annual_income < old_income
    app.number_input(key="assumption_life_expectancy").set_value(30)
    next(x for x in app.button if x.label == "Apply assumptions").click().run()
    assert app.error
    assert app.session_state["assumptions"].life_expectancy == 92


def test_unfunded_plan_has_no_affordable_income_headline() -> None:
    app = open_app()
    app.session_state["draft"] = asdict(replace(Household(), gross_salary=0,
        cash=0, investments=0, super_balance=0, annual_spending=50_000))
    app.session_state["screen"] = "results"
    app.run()
    assert not app.exception
    assert app.error
    assert not any("You can afford" in x.value for x in app.subheader)


def test_reset_and_new_session_do_not_retain_answers() -> None:
    app = finish_wizard(open_app())
    app.button(key="reset_scenario").click().run()
    assert not app.exception
    assert app.session_state["screen"] == "landing"
    assert "calculation" not in app.session_state
    fresh = open_app()
    assert fresh.session_state["draft"] == asdict(Household())


def test_400k_results_warn_instead_of_error():
    app = open_app()
    app.session_state['draft'] = asdict(Household(age=60, retirement_age=61, gross_salary=400_000, salary_sacrifice=20_000))
    app.session_state['assumptions'] = replace(DEFAULT_ASSUMPTIONS, life_expectancy=62)
    app.session_state['screen'] = 'results'
    app.run()
    assert not app.exception
    assert not any("couldn't calculate" in x.value for x in app.error)
    assert any('Employer super exceeds' in x.value for x in app.warning)
    assert any('You can afford' in x.value for x in app.subheader)
