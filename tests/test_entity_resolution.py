"""Member entity resolution: which roster rows become the same person."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date

import duckdb
import pytest


def member_of(con, row_number: int, sheet: str = "2025-01") -> str:
    return con.execute("SELECT member_id FROM object.member_roster_xref WHERE roster_row_id = ?",
                       [f"{sheet}:{row_number}"]).fetchone()[0]


def member_count(con) -> int:
    return con.execute("SELECT count(*) FROM object.member").fetchone()[0]


def person(**overrides) -> dict:
    return {"medicaid_id": "0123456789", "first_name": "Katherine", "last_name": "Moore",
            "dob": "1987-03-05", **overrides}


def test_same_id_in_different_formats_is_one_member(build_rows):
    con = build_rows([
        person(),
        person(medicaid_id="123456789"),        # spreadsheet dropped the leading zero
        person(medicaid_id="0123-456-789"),
        person(medicaid_id=" 0123456789 ", first_name="KATHERINE", last_name="MOORE  "),
    ])
    assert member_count(con) == 1
    assert con.execute("SELECT medicaid_id, source_record_count FROM object.member").fetchone() == ("0123456789", 4)


def test_missing_id_matches_on_name_and_birth_date(build_rows):
    con = build_rows([person(), person(medicaid_id=None, dob="03/05/1987")])
    assert member_count(con) == 1


def test_nickname_matches_formal_name(build_rows):
    con = build_rows([person(), person(medicaid_id=None, first_name="Kate")])
    assert member_count(con) == 1


def test_first_name_typo_matches(build_rows):
    con = build_rows([person(), person(medicaid_id=None, first_name="Kahterine")])
    assert member_count(con) == 1


def test_middle_initial_is_ignored(build_rows):
    con = build_rows([person(), person(medicaid_id=None, first_name="Katherine J.")])
    assert member_count(con) == 1


def test_shortened_hyphenated_last_name_matches(build_rows):
    con = build_rows([
        person(last_name="Garcia-Lopez"),
        person(medicaid_id=None, last_name="GARCIA"),
    ])
    assert member_count(con) == 1
    assert con.execute("SELECT count(*) FROM object.member WHERE last_name IN ('Garcia-Lopez', 'Garcia')").fetchone()[0] == 1


def test_twins_stay_separate(build_rows):
    con = build_rows([
        person(medicaid_id="1111111111", first_name="Elena"),
        person(medicaid_id="2222222222", first_name="Tomas"),
        person(medicaid_id=None, first_name="Elena"),
    ])
    assert member_count(con) == 2
    assert member_of(con, 1) == member_of(con, 3) != member_of(con, 2)


def test_same_name_different_birth_date_stays_separate(build_rows):
    con = build_rows([
        person(medicaid_id="1111111111"),
        person(medicaid_id="2222222222", dob="1991-11-20"),
    ])
    assert member_count(con) == 2


def test_different_people_sharing_only_a_birth_date_stay_separate(build_rows):
    con = build_rows([
        person(medicaid_id="1111111111"),
        person(medicaid_id="2222222222", first_name="Marcus", last_name="Bell"),
    ])
    assert member_count(con) == 2


def test_reenrolled_member_keeps_one_identity_and_latest_id(build_rows):
    con = build_rows([
        person(medicaid_id="1111111111", sheet="2025-01"),
        person(medicaid_id="1111111111", sheet="2025-02"),
        person(medicaid_id="2222222222", sheet="2025-03"),
    ])
    assert member_count(con) == 1
    member_id, current_id, id_count = con.execute(
        "SELECT member_id, medicaid_id, medicaid_id_count FROM object.member").fetchone()
    assert (current_id, id_count) == ("2222222222", 2)
    assert con.execute("SELECT count(*) FROM object.member_identifier WHERE member_id = ?",
                       [member_id]).fetchone()[0] == 2


def test_matches_chain_transitively(build_rows):
    # row 3 matches row 2 on name + birth date, row 2 matches row 1 on ID;
    # rows 1 and 3 share nothing directly.
    con = build_rows([
        person(first_name="Robert", last_name="Hill", dob="1970-01-01"),
        person(first_name="Robert", last_name="Hill", dob="1970-01-10"),
        person(medicaid_id=None, first_name="Bob", last_name="Hill", dob="1970-01-10"),
    ])
    assert member_count(con) == 1


def test_two_digit_birth_year_is_not_read_as_the_future(build_rows):
    con = build_rows([person(dob="03/05/62")])
    assert con.execute("SELECT date_of_birth FROM object.member").fetchone()[0] == date(1962, 3, 5)


@pytest.mark.parametrize("text, expected", [
    ("2025-06-03", date(2025, 6, 3)),
    ("2025-06-03 00:00:00", date(2025, 6, 3)),
    ("06/03/2025", date(2025, 6, 3)),
    ("6/3/2025", date(2025, 6, 3)),
    ("06/03/25", date(2025, 6, 3)),
    ("03-Jun-2025", date(2025, 6, 3)),
    ("20250603", date(2025, 6, 3)),
    (" 2025-06-03 ", date(2025, 6, 3)),
    ("June 3rd", None),
    ("2025-13-45", None),
    ("", None),
])
def test_parse_date_handles_every_source_format(build_rows, text, expected):
    con = build_rows([])
    assert con.execute("SELECT parse_date(?)", [text]).fetchone()[0] == expected


def test_contiguous_months_merge_into_one_coverage_span(build_rows):
    con = build_rows([
        person(sheet="2025-01"),
        person(sheet="2025-02", elig_start="02/01/2025", elig_end="2025-02-28"),
        person(sheet="2025-03"),
        person(sheet="2025-05"),                                    # April is missing
        person(sheet="2025-06", elig_end="2025-06-15"),             # terminated mid-month
    ])
    spans = con.execute("SELECT coverage_start, coverage_end FROM object.member_eligibility ORDER BY 1").fetchall()
    assert spans == [(date(2025, 1, 1), date(2025, 3, 31)), (date(2025, 5, 1), date(2025, 6, 15))]


def test_claim_links_to_member_by_id(build_rows):
    con = build_rows([person()], claims=[
        {"claim_number": "CLM-1", "patient_name": "MOORE, KATHERINE", "member_id": "0123-456-789", "dob": "03/05/1987"},
    ])
    assert con.execute("SELECT member_id IS NOT NULL, member_match_method FROM object.claim").fetchone() == (True, "medicaid_id")


def test_claim_with_wrong_id_links_by_name_and_birth_date(build_rows):
    con = build_rows([person()], claims=[
        {"claim_number": "CLM-1", "patient_name": "Kate Moore", "member_id": "0123456780", "dob": "1987-03-05"},
    ])
    assert con.execute("SELECT member_id IS NOT NULL, member_match_method FROM object.claim").fetchone() == (True, "name_dob")


def test_claim_for_unknown_patient_is_kept_but_unlinked(build_rows):
    con = build_rows([person()], claims=[
        {"claim_number": "CLM-1", "patient_name": "Quentin Abernathy", "member_id": "9999999999", "dob": "1950-01-01"},
    ])
    assert con.execute("SELECT count(*), count(member_id) FROM object.claim").fetchone() == (1, 0)


def test_claim_name_fallback_picks_the_right_twin(build_rows):
    con = build_rows(
        [person(medicaid_id="1111111111", first_name="Elena"), person(medicaid_id="2222222222", first_name="Tomas")],
        claims=[{"claim_number": "CLM-1", "patient_name": "Moore, Tomas", "member_id": "3333333333", "dob": "1987-03-05"}],
    )
    assert con.execute("SELECT member_id FROM object.claim").fetchone()[0] == member_of(con, 2)


def test_repeated_export_rows_collapse_to_one_claim(build_rows):
    row = {"claim_number": "CLM-1", "patient_name": "Katherine Moore", "member_id": "0123456789", "dob": "1987-03-05"}
    con = build_rows([person()], claims=[row, dict(row)])
    assert con.execute("SELECT count(*) FROM object.claim").fetchone()[0] == 1


def test_latest_authorization_revision_wins(build_rows):
    def revision(status, units, updated):
        return {"authNumber": "pa 1234567", "status": status, "unitsApproved": units, "updatedAt": updated,
                "member": {"medicaidId": "123456789", "lastName": "Moore", "firstName": "Katherine", "dob": "1987-03-05"},
                "service": {"code": "H0004"}, "provider": {"npi": "1900000014", "name": "Lena Park, LCSW"},
                "effective": {"start": "04/01/2025", "end": None}}
    con = build_rows([person()], auths=[
        revision("APPROVED", "480", "2025-03-20T10:00:00Z"),
        revision("Pending", 240, "2025-03-11T09:00:00Z"),
    ])
    assert con.execute(
        "SELECT auth_number, status, units_approved, start_date, end_date, member_id IS NOT NULL FROM object.authorization"
    ).fetchall() == [("PA1234567", "approved", 480, date(2025, 4, 1), None, True)]


def test_generated_roster_resolves_to_exactly_the_people_generated(dataset):
    """Against the answer key: no person split in two, no two people merged."""
    con = duckdb.connect(str(dataset["db_path"]))
    xref = dict(con.execute("SELECT roster_row_id, member_id FROM object.member_roster_xref").fetchall())
    con.close()
    members_of_person, people_of_member = defaultdict(set), defaultdict(set)
    with (dataset["data_dir"] / "truth" / "roster_truth.csv").open() as handle:
        for row in csv.DictReader(handle):
            member_id = xref[f"{row['sheet_name']}:{row['row_number']}"]
            members_of_person[row["person_id"]].add(member_id)
            people_of_member[member_id].add(row["person_id"])
    assert [p for p, m in members_of_person.items() if len(m) > 1] == []
    assert [m for m, p in people_of_member.items() if len(p) > 1] == []
    assert len(people_of_member) == dataset["manifest"]["people"]
