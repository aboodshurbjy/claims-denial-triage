"""Scores the rules against the generator's answer key.

The answer key (truth/claims_truth.csv) says which defect the generator
planted in which claim and which rule should report it. This module runs the
rules over the built database and counts, per rule, how many planted defects
the rule reported with the expected status and how many clean claims it
flagged. It checks that the rules behave as specified on synthetic data;
it says nothing about real claims.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .service import TriageService


@dataclass
class RuleScore:
    rule_id: str
    name: str
    planted: int = 0
    caught: int = 0
    clean_flagged: int = 0
    missed: list[str] = field(default_factory=list)          # claim IDs
    wrongly_flagged: list[str] = field(default_factory=list)  # claim IDs


@dataclass
class Validation:
    seed: int | None
    total_claims: int
    clean_claims: int
    scores: list[RuleScore]

    @property
    def planted(self) -> int:
        return sum(s.planted for s in self.scores)

    @property
    def caught(self) -> int:
        return sum(s.caught for s in self.scores)

    @property
    def clean_flagged(self) -> int:
        return sum(s.clean_flagged for s in self.scores)

    @property
    def ok(self) -> bool:
        return self.caught == self.planted and self.clean_flagged == 0


def validate(db_path: Path | str | None = None, truth_path: Path | str | None = None,
             rules_path: Path | str | None = None, seed: int | None = None) -> Validation:
    """Compare every rule result with the answer key.

    A planted defect counts as caught when the rule named in the answer key
    returns the status the answer key expects (warn or fail). A clean claim
    counts as wrongly flagged by a rule when that rule returns anything
    other than pass.
    """
    truth_path = Path(truth_path or config.DATA_DIR / "truth" / "claims_truth.csv")
    service = TriageService(db_path=db_path, rules_path=rules_path)
    try:
        scores = {spec.rule_id: RuleScore(spec.rule_id, spec.name) for spec in service.ruleset.rules}
        total = clean = 0
        with truth_path.open() as handle:
            for row in csv.DictReader(handle):
                total += 1
                claim_id = row["claim_id"]
                results = {r.rule_id: r.status.value for r in service.evaluations[claim_id].results}
                if row["defect"] == "none":
                    clean += 1
                    for rule_id, status in results.items():
                        if status != "pass":
                            scores[rule_id].clean_flagged += 1
                            scores[rule_id].wrongly_flagged.append(claim_id)
                    continue
                score = scores[row["expected_rule"]]
                score.planted += 1
                if results[row["expected_rule"]] == row["expected_status"]:
                    score.caught += 1
                else:
                    score.missed.append(claim_id)
        return Validation(seed, total, clean, list(scores.values()))
    finally:
        service.close()


def format_validation(validation: Validation) -> str:
    """The result as a Markdown table, ready to paste into the README."""
    lines = [
        "| Rule | Defects planted | Defects caught | Clean claims wrongly flagged |",
        "|---|---:|---:|---:|",
    ]
    for s in validation.scores:
        lines.append(f"| {s.name} | {s.planted} | {s.caught} | {s.clean_flagged} |")
    lines.append(f"| **Total** | **{validation.planted}** | **{validation.caught}** "
                 f"| **{validation.clean_flagged}** |")
    seed = f"seed {validation.seed}, " if validation.seed is not None else ""
    lines.append("")
    lines.append(f"{seed}{validation.total_claims} claims: {validation.planted} with a planted defect, "
                 f"{validation.clean_claims} clean.")
    for s in validation.scores:
        if s.missed:
            lines.append(f"{s.name}: missed {', '.join(s.missed)}")
        if s.wrongly_flagged:
            lines.append(f"{s.name}: wrongly flagged {', '.join(s.wrongly_flagged)}")
    return "\n".join(lines)
