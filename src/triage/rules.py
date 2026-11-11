"""Payer rules as pure functions.

Standard library only: no database, no web framework, no YAML, no clock.
Each rule takes a claim, the facts surrounding it and its parameters, and
returns pass, warn or fail with a reason a biller can act on. Everything a
rule needs arrives as an argument, so the same inputs always produce the
same result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Any, Callable, Mapping


class Status(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


_SEVERITY = {Status.PASS: 0, Status.WARN: 1, Status.FAIL: 2}


@dataclass(frozen=True)
class Claim:
    service_code: str
    date_of_service: date
    units: int
    billed_amount: float
    claim_id: str | None = None           # None for a claim not yet in the system
    member_id: str | None = None
    member_match: str | None = None       # "medicaid_id", "name_dob" or None
    medicaid_id_on_claim: str | None = None
    provider_id: str | None = None
    auth_number: str | None = None
    created_date: date | None = None


@dataclass(frozen=True)
class Member:
    member_id: str
    name: str
    medicaid_id: str | None = None


@dataclass(frozen=True)
class EligibilitySpan:
    start: date
    end: date


@dataclass(frozen=True)
class Authorization:
    auth_number: str
    member_id: str | None
    service_code: str
    start_date: date
    end_date: date | None                 # None means open-ended
    units_approved: int | None
    status: str = "approved"              # approved | pending | denied


@dataclass(frozen=True)
class ServiceCode:
    code: str
    description: str = ""
    requires_auth: bool = False
    max_units_per_day: int | None = None


@dataclass(frozen=True)
class ClaimContext:
    """Everything known about a claim's surroundings at evaluation time."""

    as_of: date
    member: Member | None = None
    eligibility: tuple[EligibilitySpan, ...] = ()
    auth_on_claim: Authorization | None = None            # the auth the claim cites, if it exists
    member_authorizations: tuple[Authorization, ...] = ()
    member_claims: tuple[Claim, ...] = ()                 # the member's other claims


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    status: Status
    reason: str


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    name: str
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Ruleset:
    version: str
    payer: str
    effective_date: date
    services: Mapping[str, ServiceCode]
    rules: tuple[RuleSpec, ...]
    risk_weights: Mapping[str, float] = field(default_factory=lambda: {"fail": 1.0, "warn": 0.25})


Rule = Callable[[Claim, ClaimContext, Mapping[str, Any], Mapping[str, ServiceCode]], RuleResult]


# --------------------------------------------------------------------- helpers

def _fmt(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def _covers(auth: Authorization, d: date) -> bool:
    return auth.start_date <= d and (auth.end_date is None or d <= auth.end_date)


def _window(auth: Authorization) -> str:
    return f"{_fmt(auth.start_date)} to {_fmt(auth.end_date) if auth.end_date else 'open-ended'}"


def _requires_auth(claim: Claim, services: Mapping[str, ServiceCode]) -> bool:
    service = services.get(claim.service_code)
    return bool(service and service.requires_auth)


def _on_file_auth(claim: Claim, ctx: ClaimContext) -> Authorization | None:
    """An approved auth for this member and service, preferring one that covers the date."""
    candidates = [a for a in ctx.member_authorizations
                  if a.service_code == claim.service_code and a.status == "approved"]
    if not candidates:
        return None
    covering = [a for a in candidates if _covers(a, claim.date_of_service)]
    return max(covering or candidates, key=lambda a: (a.start_date, a.auth_number))


def applicable_authorization(claim: Claim, ctx: ClaimContext) -> Authorization | None:
    """The authorization this claim would be paid against, if one can be identified.

    The auth cited on the claim is used when it belongs to this member and
    service. A claim with no auth number falls back to an approved auth on
    file. A claim citing an unusable number gets none: guessing a different
    auth would hide the real problem.
    """
    cited = ctx.auth_on_claim
    if cited is not None:
        same_member = cited.member_id is not None and cited.member_id == claim.member_id
        if same_member and cited.service_code == claim.service_code:
            return cited
        return None
    if claim.auth_number:
        return None
    return _on_file_auth(claim, ctx)


def _order_key(claim: Claim) -> tuple:
    # claims not yet in the system sort after everything on the same day
    return (claim.date_of_service, claim.claim_id is None, claim.claim_id or "")


def _was_entered_before(other: Claim, claim: Claim) -> bool:
    if claim.claim_id is None:
        return True
    if other.claim_id is None:
        return False
    return (other.created_date or date.min, other.claim_id) < (claim.created_date or date.min, claim.claim_id)


# ----------------------------------------------------------------------- rules

def eligibility_on_dos(claim, ctx, params, services) -> RuleResult:
    rule_id = "eligibility_on_dos"
    dos = claim.date_of_service
    if ctx.member is None:
        shown = claim.medicaid_id_on_claim or "missing"
        return RuleResult(rule_id, Status.FAIL,
                          f"No one on the eligibility roster matches this patient (Member ID on claim: {shown}). "
                          "Verify the ID and enrollment before submitting.")
    name = ctx.member.name
    span = next((s for s in ctx.eligibility if s.start <= dos <= s.end), None)
    if span is None:
        earlier = [s.end for s in ctx.eligibility if s.end < dos]
        later = [s.start for s in ctx.eligibility if s.start > dos]
        detail = f"Coverage ended {_fmt(max(earlier))}." if earlier else ""
        if later:
            detail = (detail + " " if detail else "") + f"Coverage resumes {_fmt(min(later))}."
        return RuleResult(rule_id, Status.FAIL,
                          f"{name} was not eligible on {_fmt(dos)}. {detail or 'No coverage on file.'}".strip())
    if claim.member_match == "name_dob":
        return RuleResult(rule_id, Status.WARN,
                          f"{name} was eligible on {_fmt(dos)}, but the Member ID on the claim "
                          f"({claim.medicaid_id_on_claim or 'missing'}) is not the roster ID "
                          f"({ctx.member.medicaid_id or 'unknown'}). Matched by name and date of birth; "
                          "correct the ID before submitting.")
    return RuleResult(rule_id, Status.PASS,
                      f"{name} was eligible on {_fmt(dos)} (coverage {_fmt(span.start)} to {_fmt(span.end)}).")


def auth_exists(claim, ctx, params, services) -> RuleResult:
    rule_id = "auth_exists"
    code = claim.service_code
    if code not in services:
        return RuleResult(rule_id, Status.WARN,
                          f"{code} is not in the ruleset's service catalog, so its authorization "
                          "requirement is unknown. Confirm with the payer.")
    if not _requires_auth(claim, services):
        return RuleResult(rule_id, Status.PASS, f"{code} does not require prior authorization.")

    if claim.auth_number:
        cited = ctx.auth_on_claim
        if cited is None:
            return RuleResult(rule_id, Status.FAIL,
                              f"Auth number {claim.auth_number} on the claim is not in the authorization feed. "
                              "Check for a typo or request the authorization.")
        if cited.member_id is None or cited.member_id != claim.member_id:
            return RuleResult(rule_id, Status.FAIL,
                              f"Auth {cited.auth_number} was issued for a different member.")
        if cited.service_code != code:
            return RuleResult(rule_id, Status.FAIL,
                              f"Auth {cited.auth_number} covers {cited.service_code}, not {code}.")
        if cited.status == "approved":
            return RuleResult(rule_id, Status.PASS, f"Auth {cited.auth_number} is approved for {code}.")
        if cited.status == "pending":
            return RuleResult(rule_id, Status.WARN,
                              f"Auth {cited.auth_number} is still pending. Hold the claim until it is approved.")
        return RuleResult(rule_id, Status.FAIL,
                          f"Auth {cited.auth_number} has status '{cited.status}'; it will not support payment.")

    on_file = _on_file_auth(claim, ctx)
    if on_file is not None:
        return RuleResult(rule_id, Status.WARN,
                          f"{code} requires prior authorization and the claim has no auth number. "
                          f"Approved auth {on_file.auth_number} is on file for this member; add it to the claim.")
    return RuleResult(rule_id, Status.FAIL,
                      f"{code} requires prior authorization and none is on file for this member.")


def service_inside_auth_window(claim, ctx, params, services) -> RuleResult:
    rule_id = "service_inside_auth_window"
    auth = applicable_authorization(claim, ctx)
    if auth is None:
        if _requires_auth(claim, services):
            return RuleResult(rule_id, Status.PASS,
                              "Not checked: no usable authorization to compare against (see the authorization rule).")
        return RuleResult(rule_id, Status.PASS, f"Not applicable: {claim.service_code} needs no authorization.")
    dos = claim.date_of_service
    if dos < auth.start_date:
        return RuleResult(rule_id, Status.FAIL,
                          f"Date of service {_fmt(dos)} is before auth {auth.auth_number} starts "
                          f"({_window(auth)}).")
    if auth.end_date is not None and dos > auth.end_date:
        return RuleResult(rule_id, Status.FAIL,
                          f"Date of service {_fmt(dos)} is {(dos - auth.end_date).days} days after auth "
                          f"{auth.auth_number} ended ({_window(auth)}). Request an extension or a new auth.")
    return RuleResult(rule_id, Status.PASS,
                      f"Date of service {_fmt(dos)} is inside auth {auth.auth_number} ({_window(auth)}).")


def units_under_cap(claim, ctx, params, services) -> RuleResult:
    rule_id = "units_under_cap"
    service = services.get(claim.service_code)
    daily_cap = service.max_units_per_day if service else None
    if daily_cap is not None and claim.units > daily_cap:
        return RuleResult(rule_id, Status.FAIL,
                          f"{claim.units} units billed; {claim.service_code} is capped at {daily_cap} per day.")

    auth = applicable_authorization(claim, ctx)
    if auth is None or auth.units_approved is None:
        limit = f"the daily cap of {daily_cap}" if daily_cap is not None else "any cap on file"
        return RuleResult(rule_id, Status.PASS, f"{claim.units} units is within {limit}.")

    used_before = 0
    for other in ctx.member_claims:
        if other.service_code != auth.service_code:
            continue
        if other.auth_number and other.auth_number != auth.auth_number:
            continue
        if not other.auth_number and not _covers(auth, other.date_of_service):
            continue
        if _order_key(other) < _order_key(claim):
            used_before += other.units
    total = used_before + claim.units
    approved = auth.units_approved
    if total > approved:
        return RuleResult(rule_id, Status.FAIL,
                          f"Auth {auth.auth_number} approves {approved} units; {used_before} already used, "
                          f"so this claim's {claim.units} would exceed it by {total - approved}.")
    warn_pct = float(params.get("utilization_warn_pct", 90))
    if approved > 0 and total * 100 >= warn_pct * approved:
        return RuleResult(rule_id, Status.WARN,
                          f"Auth {auth.auth_number} will be {total * 100 // approved}% used after this claim "
                          f"({total} of {approved} units). Request more units before the next visit.")
    return RuleResult(rule_id, Status.PASS,
                      f"{total} of {approved} units used on auth {auth.auth_number} after this claim.")


def duplicate_claim(claim, ctx, params, services) -> RuleResult:
    rule_id = "duplicate_claim"
    same_service = [o for o in ctx.member_claims
                    if o.service_code == claim.service_code
                    and o.date_of_service == claim.date_of_service
                    and _was_entered_before(o, claim)]
    exact = sorted(o.claim_id or "" for o in same_service if o.provider_id == claim.provider_id)
    if exact:
        return RuleResult(rule_id, Status.FAIL,
                          f"Duplicate of claim {exact[0]}: same member, provider, {claim.service_code} and "
                          f"date of service {_fmt(claim.date_of_service)}.")
    if same_service:
        other = sorted(o.claim_id or "" for o in same_service)[0]
        return RuleResult(rule_id, Status.WARN,
                          f"Possible duplicate of claim {other}: same member, {claim.service_code} and date of "
                          "service, billed by a different provider. Confirm both services were delivered.")
    return RuleResult(rule_id, Status.PASS, "No earlier claim for this member, service and date.")


def timely_filing(claim, ctx, params, services) -> RuleResult:
    rule_id = "timely_filing"
    limit = int(params.get("limit_days", 90))
    warn_days = int(params.get("warn_days_remaining", 15))
    dos = claim.date_of_service
    age = (ctx.as_of - dos).days
    deadline = dos + timedelta(days=limit)
    if age < 0:
        return RuleResult(rule_id, Status.FAIL,
                          f"Date of service {_fmt(dos)} is in the future as of {_fmt(ctx.as_of)}.")
    remaining = limit - age
    if remaining < 0:
        return RuleResult(rule_id, Status.FAIL,
                          f"Service was {age} days ago; the {limit}-day filing limit passed on {_fmt(deadline)}.")
    if remaining <= warn_days:
        days = "day" if remaining == 1 else "days"
        return RuleResult(rule_id, Status.WARN,
                          f"{remaining} {days} left to file (deadline {_fmt(deadline)}). Submit this one first.")
    return RuleResult(rule_id, Status.PASS, f"{remaining} days left to file (deadline {_fmt(deadline)}).")


RULES: dict[str, Rule] = {
    "eligibility_on_dos": eligibility_on_dos,
    "auth_exists": auth_exists,
    "service_inside_auth_window": service_inside_auth_window,
    "units_under_cap": units_under_cap,
    "duplicate_claim": duplicate_claim,
    "timely_filing": timely_filing,
}


# ------------------------------------------------------------------ evaluation

def evaluate(claim: Claim, ctx: ClaimContext, ruleset: Ruleset) -> tuple[RuleResult, ...]:
    """Run every rule in the ruleset, in the order the ruleset lists them."""
    return tuple(RULES[spec.rule_id](claim, ctx, spec.params, ruleset.services) for spec in ruleset.rules)


def overall_status(results: tuple[RuleResult, ...] | list[RuleResult]) -> Status:
    return max((r.status for r in results), key=_SEVERITY.__getitem__, default=Status.PASS)


def dollars_at_risk(claim: Claim, results: tuple[RuleResult, ...] | list[RuleResult],
                    risk_weights: Mapping[str, float]) -> float:
    """Billed amount weighted by the worst outcome: a failure risks all of it."""
    weight = float(risk_weights.get(overall_status(results).value, 0.0))
    return round(claim.billed_amount * weight, 2)
