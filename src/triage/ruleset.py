"""Loads a versioned YAML ruleset into the plain data the rules consume."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from . import config
from .rules import RULES, RuleSpec, Ruleset, ServiceCode


class RulesetError(ValueError):
    pass


def parse_ruleset(document: dict) -> Ruleset:
    for key in ("version", "payer", "effective_date", "rules"):
        if key not in (document or {}):
            raise RulesetError(f"ruleset is missing '{key}'")

    effective = document["effective_date"]
    if not isinstance(effective, date):
        try:
            effective = date.fromisoformat(str(effective))
        except ValueError as error:
            raise RulesetError(f"effective_date is not a date: {effective!r}") from error

    services = {}
    for code, body in (document.get("service_codes") or {}).items():
        body = body or {}
        services[str(code)] = ServiceCode(
            code=str(code),
            description=str(body.get("description", "")),
            requires_auth=bool(body.get("requires_auth", False)),
            max_units_per_day=body.get("max_units_per_day"),
        )

    specs, seen = [], set()
    for entry in document["rules"]:
        rule_id = entry.get("id")
        if rule_id not in RULES:
            raise RulesetError(f"unknown rule '{rule_id}'; known rules: {', '.join(sorted(RULES))}")
        if rule_id in seen:
            raise RulesetError(f"rule '{rule_id}' is listed twice")
        seen.add(rule_id)
        if entry.get("enabled", True):
            specs.append(RuleSpec(rule_id, str(entry.get("name", rule_id)), dict(entry.get("params") or {})))

    weights = {"fail": 1.0, "warn": 0.25} | {k: float(v) for k, v in (document.get("risk_weights") or {}).items()}
    weights["pass"] = 0.0
    return Ruleset(
        version=str(document["version"]),
        payer=str(document["payer"]),
        effective_date=effective,
        services=services,
        rules=tuple(specs),
        risk_weights=weights,
    )


def load_ruleset(path: Path | str | None = None) -> Ruleset:
    path = Path(path or config.RULES_PATH)
    try:
        return parse_ruleset(yaml.safe_load(path.read_text()))
    except RulesetError as error:
        raise RulesetError(f"{path}: {error}") from error
