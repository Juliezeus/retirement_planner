"""Validated JSON downloads/uploads; no filesystem or database access."""

from dataclasses import asdict, fields
import json

from config import (Assumptions, FINANCIAL_YEAR, MAX_CHILDREN, MAX_INPUT_MONEY,
                    SCENARIO_MAX_BYTES, SCENARIO_SCHEMA_VERSION)
from engine.projection import Household, validate_scenario


def validate_inputs(h: Household, a: Assumptions) -> None:
    """Validate app limits for both widgets and uploaded scenarios."""
    validate_scenario(h, a)
    if not 18 <= h.age <= 119 or (h.partner_age is not None and not 18 <= h.partner_age <= 119):
        raise ValueError("Adult ages must be between 18 and 119.")
    if h.retirement_age <= h.age:
        raise ValueError("Choose a retirement age older than your current age.")
    if len(h.children_ages) > MAX_CHILDREN:
        raise ValueError(f"Enter at most {MAX_CHILDREN} children.")
    for field in fields(h):
        value = getattr(h, field.name)
        if field.name not in {"children_ages", "homeowner", "partner_age"} and value > MAX_INPUT_MONEY:
            raise ValueError("Amounts exceed the supported input limit.")
    if h.mortgage_rate > 1 or h.mortgage_years > 100 or a.other_debt_years > 100:
        raise ValueError("Debt rates must be at most 100% and terms at most 100 years.")
    if h.mortgage_balance and not h.homeowner:
        raise ValueError("This first model supports a mortgage on your own home only.")
    if any(getattr(a, name) > 1 for name in (
        "inflation", "wage_growth", "super_return", "investment_return",
        "cash_return", "property_growth", "pension_indexation", "other_debt_rate",
    )) or a.annual_child_cost > MAX_INPUT_MONEY:
        raise ValueError("An assumption exceeds the supported range.")


def dump_scenario(h: Household, a: Assumptions) -> bytes:
    """Encode only explicit non-identifying scenario fields."""
    validate_inputs(h, a)
    return json.dumps({"schema_version": SCENARIO_SCHEMA_VERSION,
        "model_year": FINANCIAL_YEAR, "household": asdict(h),
        "assumptions": asdict(a)}, indent=2, allow_nan=False).encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Scenario contains a repeated field.")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("Scenario numbers must be finite.")


def load_scenario(data: bytes) -> tuple[Household, Assumptions]:
    """Reject oversized, malformed, unexpected or incompatible JSON data."""
    if len(data) > SCENARIO_MAX_BYTES:
        raise ValueError("Scenario file must be smaller than 100 KB.")
    try:
        p = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                       parse_constant=_reject_constant)
        if not isinstance(p, dict) or set(p) != {"schema_version", "model_year", "household", "assumptions"}:
            raise ValueError("Choose a scenario JSON downloaded from this app.")
        if type(p["schema_version"]) is not int or p["schema_version"] != SCENARIO_SCHEMA_VERSION:
            raise ValueError("This scenario version is not supported.")
        if p["model_year"] != FINANCIAL_YEAR:
            raise ValueError("This scenario uses a different model year. Rates need review before loading it.")
        for name, kind in (("household", Household), ("assumptions", Assumptions)):
            if not isinstance(p[name], dict) or set(p[name]) != {f.name for f in fields(kind)}:
                raise ValueError("Scenario fields do not match this app version.")
        if not isinstance(p["household"]["children_ages"], list):
            raise ValueError("Child ages must be a list.")
        p["household"]["children_ages"] = tuple(p["household"]["children_ages"])
        h, a = Household(**p["household"]), Assumptions(**p["assumptions"])
        validate_inputs(h, a)
        return h, a
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, RecursionError, OverflowError) as exc:
        raise ValueError("The file is not a valid retirement scenario. Choose an app JSON download.") from exc
