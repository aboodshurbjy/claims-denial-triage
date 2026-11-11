"""HTTP API over the triage service."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from .service import TriageService


class CheckRequest(BaseModel):
    """A claim to check before it is entered or submitted."""

    medicaid_id: str | None = Field(None, description="Medicaid ID as written on the claim")
    member_id: str | None = Field(None, description="Internal member ID, if already known")
    provider_npi: str | None = None
    service_code: str = Field(min_length=1)
    date_of_service: date
    units: int = Field(gt=0)
    billed_amount: float = Field(ge=0)
    auth_number: str | None = None

    @model_validator(mode="after")
    def needs_a_member(self) -> "CheckRequest":
        if not self.medicaid_id and not self.member_id:
            raise ValueError("provide medicaid_id or member_id")
        return self


class ActionRequest(BaseModel):
    action: Literal["fix", "escalate", "reopen"]
    note: str | None = Field(None, max_length=500)


def create_app(db_path: Path | str | None = None, rules_path: Path | str | None = None,
               as_of: date | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        override = as_of or (date.fromisoformat(os.environ["TRIAGE_AS_OF"]) if os.environ.get("TRIAGE_AS_OF") else None)
        app.state.service = TriageService(db_path, rules_path, override)
        yield
        app.state.service.close()

    app = FastAPI(title="Claims Denial Triage", version="0.1.0", lifespan=lifespan)

    def service() -> TriageService:
        return app.state.service

    @app.get("/health")
    def health() -> dict:
        svc = service()
        return {"status": "ok", "claims": len(svc.evaluations), "ruleset_version": svc.ruleset.version,
                "as_of": svc.as_of.isoformat()}

    @app.post("/check")
    def check(request: CheckRequest) -> dict:
        """Run every rule against one claim and return the trace."""
        return service().check(**request.model_dump())

    @app.get("/queue")
    def queue(
        work_status: Literal["open", "escalated", "fixed", "all"] = "open",
        limit: int | None = Query(None, ge=1),
    ) -> dict:
        """Claims with findings, ranked by dollars at risk."""
        return service().queue(work_status, limit)

    @app.get("/claims/{claim_id}")
    def claim(claim_id: str) -> dict:
        """One claim with its full rule trace."""
        detail = service().claim_detail(claim_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"claim {claim_id} not found")
        return detail

    @app.post("/claims/{claim_id}/actions")
    def act(claim_id: str, request: ActionRequest) -> dict:
        """Mark a claim fixed, escalate it, or reopen it."""
        detail = service().record_action(claim_id, request.action, request.note)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"claim {claim_id} not found")
        return detail

    return app


app = create_app()
