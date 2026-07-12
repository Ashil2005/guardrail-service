"""
audit.py — Postgres-backed audit trail for guardrail rule fires.

Fail-open by design: a Postgres outage must never turn a guardrail
decision into a 500. Every write function here catches all exceptions,
logs a warning, and returns — the caller (main.py) always gets its
guardrail response regardless of audit health.
"""
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from .rules.base import RuleMatch

load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger("guardrail.audit")

_conn = None

# text_sample is a preview, not a full-text dump — matches the design's
# open question (raw vs. redacted preview) with the privacy-conservative
# default until that's answered. Short by design: the whole point is to
# cut off before whatever PII the matched rule found, wherever in the
# text it sits — a longer preview just moves the leak, it doesn't fix it.
TEXT_SAMPLE_PREVIEW_LEN = 22

GROUP_BY_COLUMNS = {
    "rule_id": "rule_id",
    "category": "category",
    "tenant_id": "tenant_id",
    "action": "action",
    "day": "DATE_TRUNC('day', timestamp)",
}


def _build_dsn() -> str:
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = os.environ.get("POSTGRES_DB", "guardrail")
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    return (
        f"host={host} port={port} dbname={dbname} "
        f"user={user} password={password}"
    )


def _get_pg_conn():
    """Lazy singleton psycopg2 connection. Reconnects if the existing
    connection was closed or broken (e.g. after a prior failed write)."""
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(_build_dsn())
        _conn.autocommit = True
    return _conn


def init_audit_table() -> None:
    """Create guardrail_audit + indexes if they don't exist yet.

    Called once from main.py's FastAPI startup event. Fails open (logs
    a warning, doesn't raise) so a Postgres outage at boot doesn't stop
    the guardrail service itself from starting — guardrail checks must
    keep working even if the audit trail can't be initialized.
    """
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS guardrail_audit (
                    id BIGSERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    request_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    tenant_id TEXT,
                    direction TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL,
                    matched_span TEXT,
                    text_sample TEXT,
                    reason TEXT
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_guardrail_audit_session
                    ON guardrail_audit(session_id, timestamp DESC);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_guardrail_audit_rule
                    ON guardrail_audit(rule_id, timestamp DESC);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_guardrail_audit_category
                    ON guardrail_audit(category, timestamp DESC);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_guardrail_audit_timestamp
                    ON guardrail_audit(timestamp DESC);
            """)
        logger.info("guardrail_audit table ready")
    except Exception:
        logger.warning("init_audit_table failed — audit trail unavailable", exc_info=True)


def _should_store_raw_span() -> bool:
    # Read fresh (not cached at import) so tests can toggle via monkeypatch.
    return os.environ.get("GUARDRAIL_AUDIT_STORE_RAW_SPAN", "false").lower() == "true"


def _truncate_span(span: Optional[str], store_raw: bool) -> Optional[str]:
    if span is None:
        return None
    if store_raw:
        return span
    return f"{span[:6]}…{span[-2:]}" if span else span


def _truncate_text_sample(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    if len(text) <= TEXT_SAMPLE_PREVIEW_LEN:
        return text
    return text[:TEXT_SAMPLE_PREVIEW_LEN] + "..."


def write_audit(
    request_id: Optional[str],
    session_id: Optional[str],
    tenant_id: Optional[str],
    direction: str,
    matches: list[RuleMatch],
    text_sample: Optional[str],
) -> None:
    """Insert one row per rule match. Fail-open: any exception is logged
    as a warning and swallowed — an audit gap is better than blocking chat.

    request_id/session_id are NOT NULL in the schema but Optional on the
    request model (existing callers don't always set them yet) — coalesce
    rather than let a missing value silently drop the whole audit row.
    """
    if not matches:
        return

    resolved_request_id = request_id or str(uuid.uuid4())
    resolved_session_id = session_id or "unknown"
    store_raw = _should_store_raw_span()
    sample = _truncate_text_sample(text_sample)

    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO guardrail_audit
                    (request_id, session_id, tenant_id, direction, rule_id,
                     category, action, matched_span, text_sample, reason)
                VALUES %s
                """,
                [
                    (
                        resolved_request_id,
                        resolved_session_id,
                        tenant_id,
                        direction,
                        m.rule_id,
                        m.category.value,
                        m.action.value,
                        _truncate_span(m.matched_span, store_raw),
                        sample,
                        m.reason,
                    )
                    for m in matches
                ],
            )
    except Exception:
        logger.warning("write_audit failed — audit gap for this request", exc_info=True)


def query_audit(
    session_id: Optional[str] = None,
    rule_id: Optional[str] = None,
    category: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 100,
) -> tuple[list[dict], int]:
    """Return (records, count) for /guardrails/audit. Parameterized SQL only."""
    conditions = []
    params: list = []

    if session_id is not None:
        conditions.append("session_id = %s")
        params.append(session_id)
    if rule_id is not None:
        conditions.append("rule_id = %s")
        params.append(rule_id)
    if category is not None:
        conditions.append("category = %s")
        params.append(category)
    if since is not None:
        conditions.append("timestamp >= %s")
        params.append(since)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    conn = _get_pg_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT id, timestamp, request_id, session_id, tenant_id, direction,
                   rule_id, category, action, matched_span, text_sample, reason
            FROM guardrail_audit
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            params + [limit],
        )
        rows = [dict(r) for r in cur.fetchall()]

        cur.execute(f"SELECT COUNT(*) AS count FROM guardrail_audit {where_clause}", params)
        count = cur.fetchone()["count"]

    return rows, count


def query_stats(since: Optional[str] = None, group_by: str = "rule_id") -> list[dict]:
    """Return [{"key": ..., "count": ...}] for /guardrails/stats.

    group_by is validated against a strict allowlist before use — never
    string-formatted from the raw query param into the SQL column position.
    """
    if group_by not in GROUP_BY_COLUMNS:
        raise ValueError(f"Invalid group_by: {group_by}")

    column_expr = GROUP_BY_COLUMNS[group_by]
    where_clause = ""
    params: list = []
    if since is not None:
        where_clause = "WHERE timestamp >= %s"
        params.append(since)

    conn = _get_pg_conn()
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {column_expr} AS key, COUNT(*) AS count
            FROM guardrail_audit
            {where_clause}
            GROUP BY {column_expr}
            ORDER BY count DESC
            """,
            params,
        )
        return [{"key": str(key), "count": count} for key, count in cur.fetchall()]
