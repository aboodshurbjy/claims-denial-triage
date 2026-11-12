"""The rules scored against the generator's answer key."""

from __future__ import annotations

import pytest

from triage.validation import format_validation, validate


@pytest.fixture(scope="module")
def result(dataset):
    return validate(db_path=dataset["db_path"],
                    truth_path=dataset["data_dir"] / "truth" / "claims_truth.csv",
                    seed=dataset["manifest"]["seed"])


def test_every_claim_in_the_answer_key_is_scored(result, dataset):
    assert result.total_claims == dataset["manifest"]["claims"]
    assert result.planted + result.clean_claims == result.total_claims


def test_every_rule_has_planted_defects(result):
    assert [s.rule_id for s in result.scores if s.planted == 0] == []


def test_no_planted_defect_is_missed(result):
    assert {s.rule_id: s.missed for s in result.scores if s.missed} == {}
    assert result.caught == result.planted


def test_no_clean_claim_is_flagged(result):
    assert {s.rule_id: s.wrongly_flagged for s in result.scores if s.wrongly_flagged} == {}
    assert result.clean_flagged == 0


def test_table_has_one_row_per_rule_and_a_total(result):
    table = format_validation(result).splitlines()
    assert table[0] == "| Rule | Defects planted | Defects caught | Clean claims wrongly flagged |"
    assert len([line for line in table if line.startswith("| ")]) == 1 + len(result.scores) + 1
    assert result.ok
