"""Runs the SQL models (raw -> staged -> object) and the SQL assertions.

All transformation logic lives in the .sql files under sql/. This module
only orders them, hands DuckDB the source locations, and reports results.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import duckdb
from openpyxl import load_workbook

from . import config

LAYERS = ("raw", "staged", "object")
ROSTER_COLUMNS = {
    "medicaid id": "medicaid_id",
    "last name": "last_name",
    "first name": "first_name",
    "dob": "dob",
    "elig start": "elig_start",
    "elig end": "elig_end",
    "plan": "plan",
}


@dataclass(frozen=True)
class AssertionResult:
    name: str
    severity: str          # "error" fails the build, "warn" is reported
    description: str
    failing_rows: int

    @property
    def passed(self) -> bool:
        return self.failing_rows == 0


class AssertionFailure(RuntimeError):
    def __init__(self, results: list[AssertionResult]):
        self.results = results
        failed = [r for r in results if r.severity == "error" and not r.passed]
        super().__init__("data quality assertions failed: " + ", ".join(
            f"{r.name} ({r.failing_rows} rows)" for r in failed))


def connect(db_path: Path | str = ":memory:") -> duckdb.DuckDBPyConnection:
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path))


def _cell_text(value: object) -> str | None:
    """Spreadsheet cells are typed; flatten each to the text a person would see."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def read_roster_workbook(path: Path) -> list[tuple]:
    """Rows from every sheet as (sheet, row number, *ROSTER_COLUMNS values) text tuples.

    Sheets start with title lines, so the header is found by its first
    column. It is not always on row 1.
    """
    rows: list[tuple] = []
    workbook = load_workbook(path, read_only=True, data_only=True)
    for sheet in workbook.worksheets:
        positions: dict[str, int] | None = None
        for row_number, cells in enumerate(sheet.iter_rows(values_only=True), start=1):
            texts = [_cell_text(c) for c in cells]
            if positions is None:
                labels = [(t or "").strip().lower() for t in texts]
                if "medicaid id" in labels:
                    positions = {ROSTER_COLUMNS[label]: i for i, label in enumerate(labels) if label in ROSTER_COLUMNS}
                continue
            if not any(texts):
                continue
            rows.append((sheet.title, row_number, *(
                texts[positions[column]] if column in positions and positions[column] < len(texts) else None
                for column in ROSTER_COLUMNS.values())))
    workbook.close()
    return rows


def stage_roster_workbook(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    columns = ", ".join(f"{c} VARCHAR" for c in ROSTER_COLUMNS.values())
    con.execute(f"CREATE OR REPLACE TEMP TABLE _xlsx_member_roster (sheet_name VARCHAR, row_number INTEGER, {columns})")
    rows = read_roster_workbook(path)
    if rows:
        placeholders = ", ".join("?" for _ in rows[0])
        con.executemany(f"INSERT INTO _xlsx_member_roster VALUES ({placeholders})", rows)


def run_macros(con: duckdb.DuckDBPyConnection) -> None:
    con.execute((config.SQL_DIR / "macros.sql").read_text())


def run_layer(con: duckdb.DuckDBPyConnection, layer: str) -> list[str]:
    """Execute every model in a layer, in file-name order."""
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {layer}")
    executed = []
    for model in sorted((config.SQL_DIR / layer).glob("*.sql")):
        try:
            con.execute(model.read_text())
        except duckdb.Error as error:
            raise RuntimeError(f"model {layer}/{model.name} failed: {error}") from error
        executed.append(model.name)
    return executed


def run_assertions(con: duckdb.DuckDBPyConnection) -> list[AssertionResult]:
    """Each file under sql/tests selects the rows that violate one expectation."""
    results = []
    for test in sorted((config.SQL_DIR / "tests").glob("*.sql")):
        text = test.read_text()
        severity = re.search(r"^-- severity: (\w+)", text, re.MULTILINE)
        comments = [line[3:].strip() for line in text.splitlines() if line.startswith("-- ")]
        failing = con.execute(f"SELECT count(*) FROM ({text.rstrip().rstrip(';')})").fetchone()[0]
        results.append(AssertionResult(
            name=test.stem,
            severity=severity.group(1) if severity else "error",
            description=comments[1] if len(comments) > 1 else "",
            failing_rows=failing,
        ))
    return results


def record_build(con: duckdb.DuckDBPyConnection, data_dir: Path | None) -> None:
    """Remember the as-of date the dataset was generated for, if it has one."""
    as_of = None
    manifest = data_dir / "manifest.json" if data_dir else None
    if manifest and manifest.exists():
        as_of = json.loads(manifest.read_text()).get("as_of")
    con.execute("CREATE OR REPLACE TABLE object.build_info AS SELECT CAST(? AS DATE) AS as_of, now() AS built_at", [as_of])


def build(db_path: Path | str | None = None, data_dir: Path | None = None,
          con: duckdb.DuckDBPyConnection | None = None, strict: bool = True) -> list[AssertionResult]:
    """Run the full pipeline against the files in <data_dir>/raw."""
    data_dir = Path(data_dir or config.DATA_DIR)
    raw_dir = data_dir / "raw"
    own_connection = con is None
    con = con or connect(db_path or config.DB_PATH)
    try:
        run_macros(con)
        con.execute("SET VARIABLE data_dir = ?", [str(raw_dir)])
        stage_roster_workbook(con, raw_dir / "member_roster.xlsx")
        for layer in LAYERS:
            run_layer(con, layer)
        record_build(con, data_dir)
        results = run_assertions(con)
    finally:
        if own_connection:
            con.close()
    if strict and any(r.severity == "error" and not r.passed for r in results):
        raise AssertionFailure(results)
    return results


def format_results(results: list[AssertionResult]) -> str:
    lines = []
    for r in results:
        mark = "ok  " if r.passed else ("FAIL" if r.severity == "error" else "warn")
        detail = "" if r.passed else f"  ({r.failing_rows} rows)"
        lines.append(f"  {mark}  {r.name}{detail}")
    return "\n".join(lines)
