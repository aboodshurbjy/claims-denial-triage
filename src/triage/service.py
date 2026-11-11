"""Triage service: evaluates claims, ranks the work queue, records biller actions."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from . import config
from .repository import Repository, clean_code
from .rules import Claim, RuleResult, Ruleset, Status, dollars_at_risk, evaluate, overall_status
from .ruleset import load_ruleset

# action -> the work status it leaves the claim in
ACTIONS = {"fix": "fixed", "escalate": "escalated", "reopen": "open"}


@dataclass(frozen=True)
class Evaluation:
    claim: Claim
    results: tuple[RuleResult, ...]
    status: Status
    dollars_at_risk: float


class TriageService:
    def __init__(self, db_path: Path | str | None = None, rules_path: Path | str | None = None,
                 as_of: date | None = None):
        self.con = duckdb.connect(str(db_path or config.DB_PATH))
        self.lock = threading.Lock()
        self.ruleset: Ruleset = load_ruleset(rules_path)
        self.repo = Repository(self.con)
        # Rules never read the clock. The date comes from the caller, else
        # from the dataset, else from today.
        self.as_of: date = as_of or self.repo.as_of or date.today()
        self.con.execute("CREATE SCHEMA IF NOT EXISTS app")
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS app.claim_action ("
            "claim_id VARCHAR, action VARCHAR, note VARCHAR, acted_at TIMESTAMP)")  # UTC
        self.evaluations: dict[str, Evaluation] = {
            claim_id: self._evaluate(claim) for claim_id, claim in self.repo.claims.items()}
        self.work_status: dict[str, str] = {}
        for claim_id, action in self.con.execute(
                "SELECT claim_id, action FROM app.claim_action ORDER BY acted_at").fetchall():
            self.work_status[claim_id] = ACTIONS.get(action, "open")

    def close(self) -> None:
        self.con.close()

    # ------------------------------------------------------------ evaluation

    def _evaluate(self, claim: Claim) -> Evaluation:
        results = evaluate(claim, self.repo.context_for(claim, self.as_of), self.ruleset)
        return Evaluation(claim, results, overall_status(results),
                          dollars_at_risk(claim, results, self.ruleset.risk_weights))

    def check(self, *, service_code: str, date_of_service: date, units: int, billed_amount: float,
              medicaid_id: str | None = None, member_id: str | None = None, provider_npi: str | None = None,
              auth_number: str | None = None) -> dict:
        """Evaluate a claim that is not in the system yet."""
        resolved = self.repo.find_member(member_id, medicaid_id)
        claim = Claim(
            service_code=clean_code(service_code) or service_code,
            date_of_service=date_of_service, units=units, billed_amount=billed_amount,
            member_id=resolved, member_match="medicaid_id" if resolved else None,
            medicaid_id_on_claim=medicaid_id, provider_id=clean_code(provider_npi),
            auth_number=clean_code(auth_number),
        )
        evaluation = self._evaluate(claim)
        return {
            **self._header(),
            "status": evaluation.status.value,
            "dollars_at_risk": evaluation.dollars_at_risk,
            "member": self._member(resolved),
            "trace": self._trace(evaluation),
        }

    # ----------------------------------------------------------------- views

    def _header(self) -> dict:
        return {"as_of": self.as_of.isoformat(), "ruleset_version": self.ruleset.version,
                "payer": self.ruleset.payer}

    def _member(self, member_id: str | None) -> dict | None:
        member = self.repo.members.get(member_id) if member_id else None
        if member is None:
            return None
        return {"member_id": member.member_id, "name": member.name, "medicaid_id": member.medicaid_id}

    def _trace(self, evaluation: Evaluation) -> list[dict]:
        names = {spec.rule_id: spec.name for spec in self.ruleset.rules}
        return [{"rule_id": r.rule_id, "rule_name": names.get(r.rule_id, r.rule_id),
                 "status": r.status.value, "reason": r.reason} for r in evaluation.results]

    def _summary_row(self, evaluation: Evaluation) -> dict:
        claim = evaluation.claim
        member = self.repo.members.get(claim.member_id) if claim.member_id else None
        service = self.ruleset.services.get(claim.service_code)
        findings = [r for r in evaluation.results if r.status is not Status.PASS]
        findings.sort(key=lambda r: r.status is not Status.FAIL)
        names = {spec.rule_id: spec.name for spec in self.ruleset.rules}
        return {
            "claim_id": claim.claim_id,
            "member_name": member.name if member else self.repo.patient_name_on_claim.get(claim.claim_id),
            "member_resolved": member is not None,
            "service_code": claim.service_code,
            "service_description": service.description if service else None,
            "date_of_service": claim.date_of_service.isoformat(),
            "units": claim.units,
            "billed_amount": claim.billed_amount,
            "dollars_at_risk": evaluation.dollars_at_risk,
            "status": evaluation.status.value,
            "work_status": self.work_status.get(claim.claim_id, "open"),
            "findings": [{"rule_id": r.rule_id, "rule_name": names.get(r.rule_id, r.rule_id),
                          "status": r.status.value} for r in findings],
            "top_reason": findings[0].reason if findings else None,
        }

    def queue(self, work_status: str = "open", limit: int | None = None) -> dict:
        """Claims with at least one finding, most dollars at risk first."""
        flagged = [e for e in self.evaluations.values() if e.status is not Status.PASS]
        flagged.sort(key=lambda e: (-e.dollars_at_risk, e.claim.claim_id))
        summary = {name: {"count": 0, "dollars_at_risk": 0.0} for name in ("open", "escalated", "fixed")}
        for e in flagged:
            bucket = summary[self.work_status.get(e.claim.claim_id, "open")]
            bucket["count"] += 1
            bucket["dollars_at_risk"] = round(bucket["dollars_at_risk"] + e.dollars_at_risk, 2)
        items = [self._summary_row(e) for e in flagged
                 if work_status == "all" or self.work_status.get(e.claim.claim_id, "open") == work_status]
        return {
            **self._header(),
            "total_claims": len(self.evaluations),
            "clean_claims": len(self.evaluations) - len(flagged),
            "summary": summary,
            "count": len(items),
            "items": items[:limit] if limit else items,
        }

    def claim_detail(self, claim_id: str) -> dict | None:
        evaluation = self.evaluations.get(claim_id)
        if evaluation is None:
            return None
        claim = evaluation.claim
        auth = self.repo.authorizations.get(claim.auth_number) if claim.auth_number else None
        with self.lock:
            history = self.con.execute(
                "SELECT action, note, acted_at FROM app.claim_action WHERE claim_id = ? ORDER BY acted_at",
                [claim_id]).fetchall()
        return {
            **self._header(),
            **self._summary_row(evaluation),
            "claim": {
                "claim_id": claim.claim_id,
                "patient_name_on_claim": self.repo.patient_name_on_claim.get(claim_id),
                "medicaid_id_on_claim": claim.medicaid_id_on_claim,
                "member_match": claim.member_match,
                "provider_id": claim.provider_id,
                "provider_name": self.repo.providers.get(claim.provider_id),
                "auth_number": claim.auth_number,
                "created_date": claim.created_date.isoformat() if claim.created_date else None,
            },
            "member": self._member(claim.member_id),
            "authorization": None if auth is None else {
                "auth_number": auth.auth_number,
                "service_code": auth.service_code,
                "start_date": auth.start_date.isoformat() if auth.start_date else None,
                "end_date": auth.end_date.isoformat() if auth.end_date else None,
                "units_approved": auth.units_approved,
                "status": auth.status,
            },
            "trace": self._trace(evaluation),
            "history": [{"action": a, "note": n, "acted_at": t.isoformat(timespec="seconds") + "Z"} for a, n, t in history],
        }

    # --------------------------------------------------------------- actions

    def record_action(self, claim_id: str, action: str, note: str | None = None) -> dict | None:
        if action not in ACTIONS:
            raise ValueError(f"unknown action '{action}'; expected one of {', '.join(ACTIONS)}")
        if claim_id not in self.evaluations:
            return None
        with self.lock:
            self.con.execute("INSERT INTO app.claim_action VALUES (?, ?, ?, ?)",
                             [claim_id, action, note or None, datetime.now(timezone.utc).replace(tzinfo=None)])
            self.work_status[claim_id] = ACTIONS[action]
        return self.claim_detail(claim_id)
