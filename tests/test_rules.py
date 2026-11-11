"""Every rule, exercised directly: plain data in, pass / warn / fail out."""

from __future__ import annotations

import ast
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from triage import rules
from triage.rules import (Authorization, Claim, ClaimContext, EligibilitySpan, Member, RuleSpec, Ruleset,
                          ServiceCode, Status)

AS_OF = date(2025, 6, 30)
SERVICES = {
    "H0004": ServiceCode("H0004", "Counseling", requires_auth=True, max_units_per_day=8),
    "T1017": ServiceCode("T1017", "Case management", requires_auth=False, max_units_per_day=8),
}
MEMBER = Member("M00001", "Katherine Moore", "0123456789")
COVERAGE = (EligibilitySpan(date(2025, 1, 1), date(2025, 6, 30)),)
AUTH = Authorization("PA1000001", "M00001", "H0004", date(2025, 4, 1), date(2025, 9, 30), 40, "approved")


def claim(**overrides) -> Claim:
    base = dict(claim_id="CLM-000100", member_id="M00001", member_match="medicaid_id",
                medicaid_id_on_claim="0123456789", provider_id="1900000014", service_code="H0004",
                date_of_service=date(2025, 6, 10), units=4, billed_amount=98.0,
                auth_number="PA1000001", created_date=date(2025, 6, 11))
    return Claim(**(base | overrides))


def context(**overrides) -> ClaimContext:
    base = dict(as_of=AS_OF, member=MEMBER, eligibility=COVERAGE, auth_on_claim=AUTH,
                member_authorizations=(AUTH,), member_claims=())
    return ClaimContext(**(base | overrides))


def run(rule, c: Claim, ctx: ClaimContext, **params):
    result = rule(c, ctx, params, SERVICES)
    assert len(result.reason) > 15 and result.reason.endswith("."), "every result carries a plain-English reason"
    return result


# ------------------------------------------------------- eligibility_on_dos

def test_eligibility_passes_when_covered_on_date_of_service():
    result = run(rules.eligibility_on_dos, claim(), context())
    assert result.status is Status.PASS
    assert "Katherine Moore" in result.reason


@pytest.mark.parametrize("dos", [date(2025, 1, 1), date(2025, 6, 30)])
def test_eligibility_span_boundaries_are_inclusive(dos):
    assert run(rules.eligibility_on_dos, claim(date_of_service=dos), context()).status is Status.PASS


def test_eligibility_fails_after_coverage_ended():
    ctx = context(eligibility=(EligibilitySpan(date(2025, 1, 1), date(2025, 4, 30)),))
    result = run(rules.eligibility_on_dos, claim(), ctx)
    assert result.status is Status.FAIL
    assert "Coverage ended Apr 30, 2025" in result.reason


def test_eligibility_fails_inside_a_coverage_gap():
    ctx = context(eligibility=(EligibilitySpan(date(2025, 1, 1), date(2025, 4, 30)),
                               EligibilitySpan(date(2025, 6, 15), date(2025, 6, 30))))
    result = run(rules.eligibility_on_dos, claim(), ctx)
    assert result.status is Status.FAIL
    assert "resumes Jun 15, 2025" in result.reason


def test_eligibility_fails_when_patient_is_not_on_the_roster():
    c = claim(member_id=None, member_match=None, medicaid_id_on_claim="9999999999")
    result = run(rules.eligibility_on_dos, c, context(member=None, eligibility=()))
    assert result.status is Status.FAIL
    assert "9999999999" in result.reason


def test_eligibility_warns_when_matched_by_name_because_the_id_is_wrong():
    c = claim(member_match="name_dob", medicaid_id_on_claim="0123456780")
    result = run(rules.eligibility_on_dos, c, context())
    assert result.status is Status.WARN
    assert "0123456780" in result.reason and "0123456789" in result.reason


# --------------------------------------------------------------- auth_exists

def test_auth_exists_passes_for_an_approved_auth_on_the_claim():
    assert run(rules.auth_exists, claim(), context()).status is Status.PASS


def test_auth_exists_passes_when_the_service_needs_no_auth():
    c = claim(service_code="T1017", auth_number=None)
    result = run(rules.auth_exists, c, context(auth_on_claim=None, member_authorizations=()))
    assert result.status is Status.PASS
    assert "does not require" in result.reason


def test_auth_exists_warns_when_number_is_missing_but_an_auth_is_on_file():
    result = run(rules.auth_exists, claim(auth_number=None), context(auth_on_claim=None))
    assert result.status is Status.WARN
    assert "PA1000001" in result.reason


def test_auth_exists_fails_when_nothing_is_on_file():
    result = run(rules.auth_exists, claim(auth_number=None), context(auth_on_claim=None, member_authorizations=()))
    assert result.status is Status.FAIL


def test_auth_exists_fails_when_the_number_is_not_in_the_feed():
    result = run(rules.auth_exists, claim(auth_number="PA9999999"), context(auth_on_claim=None))
    assert result.status is Status.FAIL
    assert "PA9999999" in result.reason


def test_auth_exists_fails_for_another_members_auth():
    other = replace(AUTH, member_id="M00002")
    assert run(rules.auth_exists, claim(), context(auth_on_claim=other)).status is Status.FAIL


def test_auth_exists_fails_for_an_auth_covering_a_different_service():
    other = replace(AUTH, service_code="H2017")
    result = run(rules.auth_exists, claim(), context(auth_on_claim=other))
    assert result.status is Status.FAIL
    assert "H2017" in result.reason


@pytest.mark.parametrize("status, expected", [("pending", Status.WARN), ("denied", Status.FAIL)])
def test_auth_exists_reflects_auth_status(status, expected):
    cited = replace(AUTH, status=status)
    assert run(rules.auth_exists, claim(), context(auth_on_claim=cited, member_authorizations=(cited,))).status is expected


def test_auth_exists_warns_for_a_code_missing_from_the_catalog():
    assert run(rules.auth_exists, claim(service_code="H9999"), context()).status is Status.WARN


# ------------------------------------------------ service_inside_auth_window

@pytest.mark.parametrize("dos", [date(2025, 4, 1), date(2025, 6, 10), date(2025, 9, 30)])
def test_window_passes_inside_and_on_the_boundaries(dos):
    assert run(rules.service_inside_auth_window, claim(date_of_service=dos), context()).status is Status.PASS


def test_window_fails_before_the_auth_starts():
    result = run(rules.service_inside_auth_window, claim(date_of_service=date(2025, 3, 31)), context())
    assert result.status is Status.FAIL
    assert "before" in result.reason


def test_window_fails_after_the_auth_ends():
    ended = replace(AUTH, end_date=date(2025, 5, 15))
    result = run(rules.service_inside_auth_window, claim(), context(auth_on_claim=ended))
    assert result.status is Status.FAIL
    assert "26 days after" in result.reason


def test_window_treats_a_missing_end_date_as_open_ended():
    open_ended = replace(AUTH, end_date=None)
    result = run(rules.service_inside_auth_window, claim(date_of_service=date(2026, 1, 5)),
                 context(auth_on_claim=open_ended))
    assert result.status is Status.PASS


def test_window_uses_the_on_file_auth_when_the_claim_has_no_number():
    ended = replace(AUTH, end_date=date(2025, 5, 15))
    ctx = context(auth_on_claim=None, member_authorizations=(ended,))
    assert run(rules.service_inside_auth_window, claim(auth_number=None), ctx).status is Status.FAIL


def test_window_is_not_checked_without_a_usable_auth():
    ctx = context(auth_on_claim=None, member_authorizations=())
    result = run(rules.service_inside_auth_window, claim(auth_number="PA9999999"), ctx)
    assert result.status is Status.PASS
    assert result.reason.startswith("Not checked")


# ----------------------------------------------------------- units_under_cap

def test_units_pass_under_both_caps():
    result = run(rules.units_under_cap, claim(), context())
    assert result.status is Status.PASS
    assert "4 of 40" in result.reason


def test_units_at_the_daily_cap_pass_and_one_over_fails():
    assert run(rules.units_under_cap, claim(units=8), context()).status is Status.PASS
    result = run(rules.units_under_cap, claim(units=9), context())
    assert result.status is Status.FAIL
    assert "capped at 8 per day" in result.reason


def test_units_fail_when_earlier_claims_used_up_the_auth():
    earlier = tuple(claim(claim_id=f"CLM-00000{i}", date_of_service=date(2025, 5, i), units=8) for i in range(1, 6))
    result = run(rules.units_under_cap, claim(), context(member_claims=earlier))
    assert result.status is Status.FAIL
    assert "40 already used" in result.reason and "exceed it by 4" in result.reason


def test_units_warn_when_the_auth_is_nearly_used():
    earlier = tuple(claim(claim_id=f"CLM-00000{i}", date_of_service=date(2025, 5, i), units=8) for i in range(1, 5))
    result = run(rules.units_under_cap, claim(), context(member_claims=earlier), utilization_warn_pct=90)
    assert result.status is Status.WARN
    assert "36 of 40" in result.reason


def test_units_only_count_claims_before_this_one_on_the_same_auth():
    others = (
        claim(claim_id="CLM-000200", date_of_service=date(2025, 6, 20), units=8),        # later visit
        claim(claim_id="CLM-000201", date_of_service=date(2025, 5, 1), units=8, auth_number="PA2000002"),
        claim(claim_id="CLM-000202", date_of_service=date(2025, 5, 2), units=8, service_code="T1017", auth_number=None),
    )
    result = run(rules.units_under_cap, claim(units=8), context(member_claims=others))
    assert result.status is Status.PASS
    assert "8 of 40" in result.reason


def test_units_without_an_auth_check_only_the_daily_cap():
    c = claim(service_code="T1017", auth_number=None)
    assert run(rules.units_under_cap, c, context(auth_on_claim=None, member_authorizations=())).status is Status.PASS


# ----------------------------------------------------------- duplicate_claim

def test_duplicate_passes_with_no_matching_claim():
    others = (claim(claim_id="CLM-000050", date_of_service=date(2025, 6, 9)),)
    assert run(rules.duplicate_claim, claim(), context(member_claims=others)).status is Status.PASS


def test_duplicate_fails_on_the_later_copy_and_names_the_original():
    original = claim(claim_id="CLM-000050", created_date=date(2025, 6, 10))
    result = run(rules.duplicate_claim, claim(), context(member_claims=(original,)))
    assert result.status is Status.FAIL
    assert "CLM-000050" in result.reason


def test_duplicate_does_not_flag_the_original():
    later_copy = claim(claim_id="CLM-000900", created_date=date(2025, 6, 13))
    assert run(rules.duplicate_claim, claim(), context(member_claims=(later_copy,))).status is Status.PASS


def test_duplicate_warns_when_another_provider_billed_the_same_service():
    other = claim(claim_id="CLM-000050", provider_id="1900000022", created_date=date(2025, 6, 10))
    result = run(rules.duplicate_claim, claim(), context(member_claims=(other,)))
    assert result.status is Status.WARN


def test_duplicate_treats_everything_on_file_as_earlier_than_a_new_claim():
    on_file = claim(claim_id="CLM-000900", created_date=date(2025, 6, 29))
    result = run(rules.duplicate_claim, claim(claim_id=None, created_date=None), context(member_claims=(on_file,)))
    assert result.status is Status.FAIL


# ------------------------------------------------------------- timely_filing

@pytest.mark.parametrize("dos, expected", [
    (date(2025, 6, 10), Status.PASS),     # 20 days old
    (date(2025, 4, 17), Status.PASS),     # 16 days left
    (date(2025, 4, 16), Status.WARN),     # 15 days left
    (date(2025, 4, 1), Status.WARN),      # deadline is today
    (date(2025, 3, 31), Status.FAIL),     # one day past
    (date(2025, 7, 4), Status.FAIL),      # in the future
])
def test_timely_filing_thresholds(dos, expected):
    result = run(rules.timely_filing, claim(date_of_service=dos), context(), limit_days=90, warn_days_remaining=15)
    assert result.status is expected


def test_timely_filing_limit_comes_from_parameters():
    c = claim(date_of_service=date(2025, 3, 1))
    assert run(rules.timely_filing, c, context(), limit_days=90).status is Status.FAIL
    assert run(rules.timely_filing, c, context(), limit_days=365).status is Status.PASS


def test_timely_filing_depends_on_the_as_of_date_not_the_clock():
    c = claim(date_of_service=date(2025, 6, 10))
    assert run(rules.timely_filing, c, context(as_of=date(2025, 6, 30))).status is Status.PASS
    assert run(rules.timely_filing, c, context(as_of=date(2025, 12, 1))).status is Status.FAIL


# ---------------------------------------------------------------- evaluation

RULESET = Ruleset(
    version="test", payer="Test payer", effective_date=date(2025, 1, 1), services=SERVICES,
    rules=tuple(RuleSpec(rule_id, rule_id) for rule_id in rules.RULES),
    risk_weights={"fail": 1.0, "warn": 0.25, "pass": 0.0},
)


def test_evaluate_runs_all_six_rules_in_ruleset_order():
    results = rules.evaluate(claim(), context(), RULESET)
    assert [r.rule_id for r in results] == [
        "eligibility_on_dos", "auth_exists", "service_inside_auth_window",
        "units_under_cap", "duplicate_claim", "timely_filing"]
    assert rules.overall_status(results) is Status.PASS


def test_dollars_at_risk_follow_the_worst_result():
    clean = rules.evaluate(claim(), context(), RULESET)
    warned = rules.evaluate(claim(auth_number=None), context(auth_on_claim=None), RULESET)
    failed = rules.evaluate(claim(units=9, billed_amount=220.5), context(), RULESET)
    assert rules.dollars_at_risk(claim(), clean, RULESET.risk_weights) == 0
    assert rules.overall_status(warned) is Status.WARN
    assert rules.dollars_at_risk(claim(), warned, RULESET.risk_weights) == 24.5
    assert rules.dollars_at_risk(claim(units=9, billed_amount=220.5), failed, RULESET.risk_weights) == 220.5


def test_rules_are_deterministic():
    assert rules.evaluate(claim(), context(), RULESET) == rules.evaluate(claim(), context(), RULESET)


def test_rules_module_imports_only_the_standard_library():
    tree = ast.parse(Path(rules.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "rules.py must not import from the rest of the package"
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)
