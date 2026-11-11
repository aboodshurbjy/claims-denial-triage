"""Reads the object layer out of DuckDB and into the plain data the rules consume."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

import duckdb

from .rules import Authorization, Claim, ClaimContext, EligibilitySpan, Member


def clean_medicaid_id(value: str | None) -> str | None:
    """Same normalisation as the clean_medicaid_id SQL macro."""
    digits = re.sub(r"[^0-9]", "", value or "")
    return digits.zfill(10) if digits else None


def clean_code(value: str | None) -> str | None:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value or "").upper()
    return cleaned or None


class Repository:
    """An in-memory snapshot of the object layer. Small agency, small data."""

    def __init__(self, con: duckdb.DuckDBPyConnection):
        self.members: dict[str, Member] = {}
        self.member_by_medicaid_id: dict[str, str] = {}
        self.eligibility: dict[str, list[EligibilitySpan]] = defaultdict(list)
        self.authorizations: dict[str, Authorization] = {}
        self.authorizations_by_member: dict[str, list[Authorization]] = defaultdict(list)
        self.claims: dict[str, Claim] = {}
        self.claims_by_member: dict[str, list[Claim]] = defaultdict(list)
        self.patient_name_on_claim: dict[str, str | None] = {}
        self.providers: dict[str, str] = {}
        self.as_of: date | None = None
        self._load(con)

    def _load(self, con: duckdb.DuckDBPyConnection) -> None:
        for member_id, medicaid_id, first, last in con.execute(
                "SELECT member_id, medicaid_id, first_name, last_name FROM object.member").fetchall():
            self.members[member_id] = Member(member_id, f"{first} {last}".strip(), medicaid_id)
        for member_id, medicaid_id in con.execute(
                "SELECT member_id, medicaid_id FROM object.member_identifier").fetchall():
            self.member_by_medicaid_id[medicaid_id] = member_id
        for member_id, start, end in con.execute(
                "SELECT member_id, coverage_start, coverage_end FROM object.member_eligibility "
                "ORDER BY member_id, coverage_start").fetchall():
            self.eligibility[member_id].append(EligibilitySpan(start, end))
        for number, member_id, code, start, end, units, status in con.execute(
                "SELECT auth_number, member_id, service_code, start_date, end_date, units_approved, status "
                "FROM object.authorization").fetchall():
            auth = Authorization(number, member_id, code, start, end, units, status)
            self.authorizations[number] = auth
            if member_id:
                self.authorizations_by_member[member_id].append(auth)
        for row in con.execute(
                "SELECT claim_id, member_id, member_match_method, medicaid_id_on_claim, provider_id, service_code, "
                "date_of_service, units, billed_amount, auth_number, created_date, patient_name_on_claim "
                "FROM object.claim").fetchall():
            claim = Claim(
                claim_id=row[0], member_id=row[1], member_match=row[2], medicaid_id_on_claim=row[3],
                provider_id=row[4], service_code=row[5], date_of_service=row[6], units=row[7],
                billed_amount=float(row[8]), auth_number=row[9], created_date=row[10],
            )
            self.claims[claim.claim_id] = claim
            self.patient_name_on_claim[claim.claim_id] = row[11]
            if claim.member_id:
                self.claims_by_member[claim.member_id].append(claim)
        self.providers = dict(con.execute("SELECT provider_id, provider_name FROM object.provider").fetchall())
        try:
            self.as_of = con.execute("SELECT as_of FROM object.build_info").fetchone()[0]
        except (duckdb.Error, TypeError):
            self.as_of = None

    def context_for(self, claim: Claim, as_of: date) -> ClaimContext:
        member_id = claim.member_id
        return ClaimContext(
            as_of=as_of,
            member=self.members.get(member_id) if member_id else None,
            eligibility=tuple(self.eligibility.get(member_id, ())) if member_id else (),
            auth_on_claim=self.authorizations.get(claim.auth_number) if claim.auth_number else None,
            member_authorizations=tuple(self.authorizations_by_member.get(member_id, ())) if member_id else (),
            member_claims=tuple(c for c in self.claims_by_member.get(member_id, ())
                                if c.claim_id != claim.claim_id) if member_id else (),
        )

    def find_member(self, member_id: str | None = None, medicaid_id: str | None = None) -> str | None:
        if member_id and member_id in self.members:
            return member_id
        return self.member_by_medicaid_id.get(clean_medicaid_id(medicaid_id) or "")
