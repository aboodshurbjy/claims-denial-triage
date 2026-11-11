from __future__ import annotations

import json
from pathlib import Path

import pytest

from triage import pipeline
from triage.generator import generate

RAW_ROSTER_COLUMNS = ["_sheet_name", "_row_number", "medicaid_id", "last_name", "first_name",
                      "dob", "elig_start", "elig_end", "plan"]
RAW_CLAIM_COLUMNS = ["_row_number", "claim_number", "patient_name", "member_id", "dob", "rendering_npi",
                     "rendering_provider", "proc_code", "dos", "units", "charge", "auth_number", "created"]


@pytest.fixture(scope="session")
def dataset(tmp_path_factory) -> dict:
    """Generated source files and a database built from them, shared by the whole run."""
    data_dir = tmp_path_factory.mktemp("data")
    manifest = generate(data_dir, seed=42)
    db_path = data_dir / "triage.duckdb"
    results = pipeline.build(db_path=db_path, data_dir=data_dir)
    return {"data_dir": data_dir, "db_path": db_path, "manifest": manifest, "assertions": results}


def build_from_rows(roster: list[dict], claims: list[dict] | None = None, auths: list[dict] | None = None):
    """Run the staged and object layers over hand-written raw rows.

    Roster rows default to the 2025-01 sheet; pass `sheet` to place a row
    in another month.
    """
    con = pipeline.connect()
    pipeline.run_macros(con)
    con.execute("CREATE SCHEMA raw")
    con.execute("CREATE TABLE raw.member_roster (_sheet_name VARCHAR, _row_number INTEGER, "
                + ", ".join(f"{c} VARCHAR" for c in RAW_ROSTER_COLUMNS[2:]) + ")")
    con.execute("CREATE TABLE raw.claims (_row_number BIGINT, "
                + ", ".join(f"{c} VARCHAR" for c in RAW_CLAIM_COLUMNS[1:]) + ")")
    con.execute("CREATE TABLE raw.authorizations (_index BIGINT, _feed_generated_at VARCHAR, payload JSON)")
    for number, row in enumerate(roster, start=1):
        values = {"_sheet_name": row.get("sheet", "2025-01"), "_row_number": number, **row}
        con.execute(f"INSERT INTO raw.member_roster VALUES ({', '.join('?' * len(RAW_ROSTER_COLUMNS))})",
                    [values.get(c) for c in RAW_ROSTER_COLUMNS])
    for number, row in enumerate(claims or [], start=1):
        values = {"_row_number": number, "rendering_npi": "1900000014", "rendering_provider": "Lena Park, LCSW",
                  "proc_code": "T1017", "dos": "2025-01-10", "units": "2", "charge": "38.50",
                  "created": "2025-01-11", **row}
        con.execute(f"INSERT INTO raw.claims VALUES ({', '.join('?' * len(RAW_CLAIM_COLUMNS))})",
                    [values.get(c) for c in RAW_CLAIM_COLUMNS])
    for number, payload in enumerate(auths or [], start=1):
        con.execute("INSERT INTO raw.authorizations VALUES (?, NULL, ?)", [number, json.dumps(payload)])
    pipeline.run_layer(con, "staged")
    pipeline.run_layer(con, "object")
    return con


@pytest.fixture
def build_rows():
    return build_from_rows
