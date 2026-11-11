from __future__ import annotations

import copy
from datetime import date

import pytest
import yaml

from triage import config
from triage.rules import RULES
from triage.ruleset import RulesetError, load_ruleset, parse_ruleset


def document() -> dict:
    return yaml.safe_load(config.RULES_PATH.read_text())


def test_shipped_ruleset_loads_with_all_six_rules():
    ruleset = load_ruleset()
    assert ruleset.version
    assert isinstance(ruleset.effective_date, date)
    assert [spec.rule_id for spec in ruleset.rules] == list(RULES)
    assert ruleset.services["H0004"].requires_auth is True
    assert ruleset.services["90837"].max_units_per_day == 1       # numeric-looking code stays a string
    assert ruleset.risk_weights["fail"] == 1.0


def test_thresholds_come_from_the_file():
    spec = {s.rule_id: s for s in load_ruleset().rules}["timely_filing"]
    assert spec.params == {"limit_days": 90, "warn_days_remaining": 15}


def test_disabled_rule_is_left_out():
    doc = document()
    doc["rules"][0]["enabled"] = False
    assert "eligibility_on_dos" not in [s.rule_id for s in parse_ruleset(doc).rules]


def test_unknown_rule_is_rejected():
    doc = document()
    doc["rules"].append({"id": "made_up_rule"})
    with pytest.raises(RulesetError, match="unknown rule 'made_up_rule'"):
        parse_ruleset(doc)


def test_rule_listed_twice_is_rejected():
    doc = document()
    doc["rules"].append(copy.deepcopy(doc["rules"][0]))
    with pytest.raises(RulesetError, match="listed twice"):
        parse_ruleset(doc)


@pytest.mark.parametrize("key", ["version", "payer", "effective_date", "rules"])
def test_missing_top_level_key_is_rejected(key):
    doc = document()
    del doc[key]
    with pytest.raises(RulesetError, match=key):
        parse_ruleset(doc)
