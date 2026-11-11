"""Filesystem locations, overridable through environment variables."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("TRIAGE_HOME", Path(__file__).resolve().parents[2]))

SQL_DIR = ROOT / "sql"
DATA_DIR = Path(os.environ.get("TRIAGE_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
DB_PATH = Path(os.environ.get("TRIAGE_DB_PATH", DATA_DIR / "triage.duckdb"))
RULES_PATH = Path(os.environ.get("TRIAGE_RULES_PATH", ROOT / "rules" / "medicaid_bh.yaml"))
