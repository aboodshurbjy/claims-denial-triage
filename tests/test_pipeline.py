"""The generator and the full pipeline, end to end on generated data."""

from __future__ import annotations

import csv
from collections import Counter

import duckdb
import pytest

from triage import pipeline
from triage.generator import generate
from triage.service import TriageService


@pytest.fixture(scope="module")
def con(dataset):
    connection = duckdb.connect(str(dataset["db_path"]))
    yield connection
    connection.close()


def test_generator_is_reproducible_for_a_seed(dataset, tmp_path):
    generate(tmp_path, seed=42)
    for name in ("claims_export.csv", "authorizations.json"):
        assert (tmp_path / "raw" / name).read_bytes() == (dataset["data_dir"] / "raw" / name).read_bytes()
    assert pipeline.read_roster_workbook(tmp_path / "raw" / "member_roster.xlsx") == \
        pipeline.read_roster_workbook(dataset["data_dir"] / "raw" / "member_roster.xlsx")


def test_generator_output_changes_with_the_seed(dataset, tmp_path):
    generate(tmp_path, seed=7)
    assert (tmp_path / "raw" / "claims_export.csv").read_bytes() != \
        (dataset["data_dir"] / "raw" / "claims_export.csv").read_bytes()


def test_sources_are_actually_messy(con):
    """The defects the pipeline exists to handle are present in the raw layer."""
    date_shapes = con.execute(
        "SELECT count(DISTINCT regexp_replace(dos, '[0-9]', '9', 'g')) FROM raw.claims").fetchone()[0]
    repeated_rows = con.execute(
        "SELECT count(*) - count(DISTINCT claim_number) FROM raw.claims").fetchone()[0]
    blank_auth = con.execute("SELECT count(*) FROM raw.claims WHERE auth_number IS NULL").fetchone()[0]
    short_ids = con.execute("SELECT count(*) FROM raw.member_roster WHERE length(medicaid_id) = 9").fetchone()[0]
    blank_ids = con.execute("SELECT count(*) FROM raw.member_roster WHERE medicaid_id IS NULL").fetchone()[0]
    auth_revisions = con.execute(
        "SELECT count(*) - count(DISTINCT json_extract_string(payload, '$.authNumber')) FROM raw.authorizations"
    ).fetchone()[0]
    assert date_shapes >= 4
    assert repeated_rows > 0 and blank_auth > 0 and short_ids > 0 and blank_ids > 0 and auth_revisions > 0


def test_every_layer_is_populated(con):
    for table in ("raw.claims", "raw.member_roster", "raw.authorizations",
                  "staged.claims", "staged.member_roster", "staged.authorizations",
                  "object.member", "object.authorization", "object.claim", "object.provider"):
        assert con.execute(f"SELECT count(*) FROM {table}").fetchone()[0] > 0, table


def test_object_counts_match_what_was_generated(con, dataset):
    manifest = dataset["manifest"]
    assert con.execute("SELECT count(*) FROM object.claim").fetchone()[0] == manifest["claims"]
    assert con.execute("SELECT count(*) FROM object.member").fetchone()[0] == manifest["people"]
    assert con.execute("SELECT count(*) FROM raw.claims").fetchone()[0] == manifest["claim_rows"] > manifest["claims"]


def test_sql_assertions_hold(dataset):
    results = {r.name: r for r in dataset["assertions"]}
    assert len(results) >= 15
    assert [r.name for r in results.values() if r.severity == "error" and not r.passed] == []
    # the six patients who are not on the roster are reported, not hidden
    assert results["claim_member_resolved"].severity == "warn"
    assert results["claim_member_resolved"].failing_rows == 6


def test_a_broken_model_output_fails_the_build(dataset, tmp_path):
    con = pipeline.connect()
    pipeline.build(data_dir=dataset["data_dir"], con=con)
    con.execute("INSERT INTO object.claim SELECT * FROM object.claim LIMIT 1")
    failed = [r.name for r in pipeline.run_assertions(con) if not r.passed and r.severity == "error"]
    assert failed == ["claim_id_unique"]


def test_rules_find_every_planted_defect_and_nothing_else(dataset):
    """Against the answer key: each defect trips its rule, clean claims pass all six."""
    service = TriageService(db_path=dataset["db_path"])
    try:
        mismatches, seen = [], Counter()
        with (dataset["data_dir"] / "truth" / "claims_truth.csv").open() as handle:
            for row in csv.DictReader(handle):
                evaluation = service.evaluations[row["claim_id"]]
                seen[row["defect"]] += 1
                if row["defect"] == "none":
                    if evaluation.status.value != "pass":
                        mismatches.append((row["claim_id"], "clean claim was flagged"))
                    continue
                result = next(r for r in evaluation.results if r.rule_id == row["expected_rule"])
                if result.status.value != row["expected_status"]:
                    mismatches.append((row["claim_id"], row["defect"], result.status.value))
        assert mismatches == []
        assert len(seen) >= 14, "every defect family is represented"
    finally:
        service.close()
