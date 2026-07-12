"""
Shared pytest fixtures for audit tests.

Postgres fixtures require:
  - guardrail_test database exists
  - TEST_POSTGRES_DB (or POSTGRES_DB) / POSTGRES_* credentials in .env

Mirrors email-agent-prototype's tests/conftest.py pattern (separate test
database, schema created once per session) but truncates between tests
instead of rolling back a transaction — the audit connection runs with
autocommit=True (matching write_audit's fire-and-forget style), so there's
no open transaction to roll back.
"""
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# Redirect the app under test at the test database *before* any test module
# imports src.main / src.audit — python-dotenv's load_dotenv() inside audit.py
# won't override an env var that's already set, so this wins.
os.environ["POSTGRES_DB"] = os.environ.get("TEST_POSTGRES_DB", "guardrail_test")


@pytest.fixture(scope="session")
def pg_test_conn():
    pytest.importorskip("psycopg2")
    from src import audit as audit_module

    try:
        conn = audit_module._get_pg_conn()
    except Exception as exc:
        pytest.skip(f"Cannot connect to guardrail_test database: {exc}")

    audit_module.init_audit_table()
    yield conn


@pytest.fixture(autouse=True)
def _clean_audit_table(pg_test_conn):
    """Every test starts with an empty guardrail_audit table."""
    with pg_test_conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE guardrail_audit RESTART IDENTITY")
    yield
