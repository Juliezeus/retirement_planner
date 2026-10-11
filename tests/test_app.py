"""Exercise real wizard navigation, validation, results and session isolation."""

from dataclasses import asdict, replace
from pathlib import Path

from streamlit.testing.v1 import AppTest

from config import ASFA_ANNUAL_SPENDING, DEFAULT_ASSUMPTIONS
from engine.projection import Household

APP = Path(__file__).resolve().parents[1] / "app.py"


def open_app() -> AppTest:
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    return app


def finish_wizard(app: AppTest) -> AppTest:
    app.button(key="get_started").click().run()
    for _ in range(6):
        app.button(key="wizard_next").click().run()
        assert not app.exception
    return app


def test_complete_single_flow_and_display_toggle_preserves_headline() -> None:
    app = finish_wizard(open_app())
    assert app.title[0].value == "Your retirement picture"
    assert app.success
    assert any("licensed financial adviser" in x.value for x in app.info)
    headline = next(x.value for x in app.subheader if "You can afford" in x.value)
    calculation = app.session_state["calculation"]
    app.toggle(key="future_dollars").set_value(True).run()
    assert not app.exception
    assert next(x.value for x in app.subheader if "You can afford" in x.value) == headline
    assert app.session_state["calculation"][2] == calculation[2]


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
