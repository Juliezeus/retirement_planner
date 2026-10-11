"""Ensure JSON restores scenarios exactly and rejects unsafe/invalid data."""

from dataclasses import replace
import json

import pytest

from config import DEFAULT_ASSUMPTIONS, SCENARIO_MAX_BYTES
from engine.projection import Household
from scenarios import dump_scenario, load_scenario


def test_round_trip_preserves_couple_children_and_assumptions() -> None:
    h = replace(Household(), partner_age=42, children_ages=(3, 12), cash=12_345.67)
    a = replace(DEFAULT_ASSUMPTIONS, primary_income_share=.7, inflation=.03)
    assert load_scenario(dump_scenario(h, a)) == (h, a)


@pytest.mark.parametrize("data", [b"not json", b"[]", b"{}", b"\xff",
    b'{"schema_version":1,"schema_version":1}', b" " * (SCENARIO_MAX_BYTES + 1)],
    ids=["text", "array", "empty", "encoding", "duplicate", "oversized"])
def test_malformed_files(data) -> None:
    with pytest.raises(ValueError):
        load_scenario(data)


@pytest.mark.parametrize("section, field, value", [
    (None, "schema_version", 99), (None, "schema_version", True),
    (None, "model_year", "2020-21"), ("household", "name", "Unexpected field"),
    ("household", "cash", -1), ("household", "cash", float("nan")),
    ("household", "children_ages", "3, 5"), ("household", "children_ages", [True]),
    ("household", "retirement_age", 40), ("household", "partner_age", 120),
    ("household", "age", 120), ("assumptions", "primary_super_share", 1.2),
    ("assumptions", "life_expectancy", "ninety"),
])
def test_invalid_fields(section, field, value) -> None:
    p = json.loads(dump_scenario(Household(), DEFAULT_ASSUMPTIONS))
    target = p if section is None else p[section]
    target[field] = value
    with pytest.raises(ValueError):
        load_scenario(json.dumps(p).encode())
