from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from triage.api import create_app


@pytest.fixture
def client(dataset, tmp_path):
    """Each test gets its own copy of the database, so recorded actions do not leak."""
    db_path = tmp_path / "triage.duckdb"
    shutil.copy(dataset["db_path"], db_path)
    with TestClient(create_app(db_path=db_path)) as test_client:
        yield test_client


def member_with_auth(client) -> tuple:
    repo = client.app.state.service.repo
    auth = next(a for a in repo.authorizations.values()
                if a.status == "approved" and a.units_approved >= 300 and a.end_date is not None)
    return repo.members[auth.member_id], auth


def test_health_reports_dataset_date_and_ruleset(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["as_of"] == "2025-06-30"
    assert body["claims"] == 622
    assert body["ruleset_version"]


def test_queue_is_ranked_by_dollars_at_risk(client):
    body = client.get("/queue").json()
    at_risk = [item["dollars_at_risk"] for item in body["items"]]
    assert at_risk == sorted(at_risk, reverse=True)
    assert at_risk[0] > 0
    assert body["count"] == len(body["items"]) == body["summary"]["open"]["count"]
    assert body["total_claims"] == body["clean_claims"] + body["count"]


def test_queue_holds_only_claims_with_findings(client):
    items = client.get("/queue").json()["items"]
    assert {item["status"] for item in items} == {"fail", "warn"}
    assert all(item["findings"] and item["top_reason"] for item in items)
    failing = next(item for item in items if item["status"] == "fail")
    assert failing["dollars_at_risk"] == failing["billed_amount"]
    warned = next(item for item in items if item["status"] == "warn")
    assert warned["dollars_at_risk"] == round(warned["billed_amount"] * 0.25, 2)


def test_queue_limit(client):
    assert len(client.get("/queue", params={"limit": 5}).json()["items"]) == 5
    assert client.get("/queue", params={"limit": 0}).status_code == 422
    assert client.get("/queue", params={"work_status": "nonsense"}).status_code == 422


def test_claim_detail_carries_the_full_rule_trace(client):
    claim_id = client.get("/queue").json()["items"][0]["claim_id"]
    body = client.get(f"/claims/{claim_id}").json()
    assert [step["rule_id"] for step in body["trace"]] == [
        "eligibility_on_dos", "auth_exists", "service_inside_auth_window",
        "units_under_cap", "duplicate_claim", "timely_filing"]
    assert all(step["status"] in {"pass", "warn", "fail"} and step["reason"] and step["rule_name"]
               for step in body["trace"])
    assert body["ruleset_version"] and body["as_of"] == "2025-06-30"
    assert body["claim"]["provider_name"]
    assert body["history"] == []


def test_clean_claim_is_retrievable_but_not_queued(client):
    service = client.app.state.service
    clean_id = next(cid for cid, e in service.evaluations.items() if e.status.value == "pass")
    assert client.get(f"/claims/{clean_id}").json()["status"] == "pass"
    assert clean_id not in {item["claim_id"] for item in client.get("/queue", params={"work_status": "all"}).json()["items"]}


def test_unknown_claim_is_404(client):
    assert client.get("/claims/CLM-NOPE").status_code == 404
    assert client.post("/claims/CLM-NOPE/actions", json={"action": "fix"}).status_code == 404


def test_check_passes_a_clean_claim(client):
    member, auth = member_with_auth(client)
    body = client.post("/check", json={
        "medicaid_id": member.medicaid_id, "provider_npi": "1900000014", "service_code": auth.service_code,
        "date_of_service": "2025-06-28", "units": 1, "billed_amount": 24.5, "auth_number": auth.auth_number,
    }).json()
    assert body["status"] == "pass", body["trace"]
    assert body["dollars_at_risk"] == 0
    assert body["member"]["member_id"] == member.member_id
    assert len(body["trace"]) == 6


def test_check_normalises_identifiers_the_way_the_pipeline_does(client):
    member, auth = member_with_auth(client)
    hyphenated = f"{member.medicaid_id[:4]}-{member.medicaid_id[4:7]}-{member.medicaid_id[7:]}"
    body = client.post("/check", json={
        "medicaid_id": hyphenated, "service_code": auth.service_code.lower(), "date_of_service": "2025-06-28",
        "units": 1, "billed_amount": 24.5, "auth_number": f"{auth.auth_number[:2]} {auth.auth_number[2:]}".lower(),
    }).json()
    assert body["status"] == "pass", body["trace"]


def test_check_explains_failures(client):
    member, auth = member_with_auth(client)
    body = client.post("/check", json={
        "medicaid_id": member.medicaid_id, "service_code": auth.service_code, "date_of_service": "2025-02-03",
        "units": 40, "billed_amount": 980.0, "auth_number": "PA0000000",
    }).json()
    statuses = {step["rule_id"]: step["status"] for step in body["trace"]}
    assert body["status"] == "fail"
    assert body["dollars_at_risk"] == 980.0
    assert statuses["auth_exists"] == "fail"
    assert statuses["units_under_cap"] == "fail"
    assert statuses["timely_filing"] == "fail"


def test_check_for_someone_not_on_the_roster(client):
    body = client.post("/check", json={
        "medicaid_id": "0000000001", "service_code": "T1017", "date_of_service": "2025-06-20",
        "units": 2, "billed_amount": 38.5,
    }).json()
    assert body["member"] is None
    assert body["trace"][0]["status"] == "fail"


@pytest.mark.parametrize("patch", [
    {"units": 0}, {"billed_amount": -1}, {"date_of_service": "not a date"}, {"medicaid_id": None},
    {"service_code": ""},
])
def test_check_rejects_invalid_input(client, patch):
    payload = {"medicaid_id": "0000000001", "service_code": "T1017", "date_of_service": "2025-06-20",
               "units": 2, "billed_amount": 38.5} | patch
    assert client.post("/check", json=payload).status_code == 422


def test_marking_fixed_moves_a_claim_out_of_the_open_queue(client):
    before = client.get("/queue").json()
    target = before["items"][0]
    detail = client.post(f"/claims/{target['claim_id']}/actions", json={"action": "fix", "note": "added auth"}).json()
    assert detail["work_status"] == "fixed"
    assert [(h["action"], h["note"]) for h in detail["history"]] == [("fix", "added auth")]

    after = client.get("/queue").json()
    assert target["claim_id"] not in {item["claim_id"] for item in after["items"]}
    assert after["summary"]["open"]["count"] == before["summary"]["open"]["count"] - 1
    assert after["summary"]["fixed"] == {"count": 1, "dollars_at_risk": target["dollars_at_risk"]}
    assert [item["claim_id"] for item in client.get("/queue", params={"work_status": "fixed"}).json()["items"]] == \
        [target["claim_id"]]


def test_escalate_then_reopen(client):
    claim_id = client.get("/queue").json()["items"][1]["claim_id"]
    assert client.post(f"/claims/{claim_id}/actions", json={"action": "escalate"}).json()["work_status"] == "escalated"
    assert client.get("/queue", params={"work_status": "escalated"}).json()["count"] == 1
    detail = client.post(f"/claims/{claim_id}/actions", json={"action": "reopen"}).json()
    assert detail["work_status"] == "open"
    assert [h["action"] for h in detail["history"]] == ["escalate", "reopen"]


def test_invalid_action_is_rejected(client):
    claim_id = client.get("/queue").json()["items"][0]["claim_id"]
    assert client.post(f"/claims/{claim_id}/actions", json={"action": "delete"}).status_code == 422


def test_actions_survive_a_restart(dataset, tmp_path):
    db_path = tmp_path / "triage.duckdb"
    shutil.copy(dataset["db_path"], db_path)
    with TestClient(create_app(db_path=db_path)) as first:
        claim_id = first.get("/queue").json()["items"][0]["claim_id"]
        first.post(f"/claims/{claim_id}/actions", json={"action": "escalate"})
    with TestClient(create_app(db_path=db_path)) as second:
        assert second.get(f"/claims/{claim_id}").json()["work_status"] == "escalated"
