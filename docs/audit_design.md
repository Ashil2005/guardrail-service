# Guardrail Audit + Statistics — Design

Planning doc from the design session preceding implementation. Written up
after the fact (implementation shipped first) so the rationale behind the
schema and endpoint choices isn't lost.

## Background

Mentor Eby Kuriakose asked for, during his reply to the demo video:

1. Count how many times each guardrail was hit, when, why (audit) —
   required for improving rules over time
2. Statistics per guardrail as a dashboard
3. Reference to context to trace back to the original conversation from
   history
4. Improve guardrails as another API to call (interpreted as: add
   admin/query endpoints so guardrail-service is a more polished
   standalone product)

Other Eby items (token accounting, latency instrumentation, LangFuse) are
separate work streams, not covered here.

## Read-only audit findings (pre-implementation)

- `src/main.py`'s `/guardrails/check` endpoint had no persistence at all —
  only a `logger.info(...)` call. `session_id`/`request_id` were accepted
  on `CheckRequest` but never read anywhere.
- `RuleMatch` objects (`src/rules/base.py`) are built inside each `Rule`
  subclass's `.check()`, not in `main.py`.
- `src/engine.py`'s `evaluate()` is a pure function — no I/O, no access to
  `tenant_id`/`session_id`/`request_id` (those only exist on
  `CheckRequest` in `main.py`).
- `requirements.txt` had no DB driver at all (no psycopg2, asyncpg, or
  SQLAlchemy).
- 6 rules existed across `word_filter`, `sensitive_info` (Aadhaar),
  `denied_topics`, `content_filter` (prompt injection),
  `contextual_grounding`, `automated_reasoning`.
- email-agent-prototype already runs Postgres in production
  (`USE_POSTGRES=true`), via psycopg3 + `psycopg_pool.ConnectionPool`
  (`db.py`), with a plain-SQL migration convention
  (`db/apply_migrations.py` + `db/migrations/*.sql`, tracked in an
  `_migrations` table).
- email-agent's `app.py` is a single-file Streamlit app with no native
  `pages/` multipage directory — page-like content lives in separate
  modules (e.g. `flow_page.py`) called conditionally, not via Streamlit's
  multipage convention.

## Data model

```sql
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
```

Plus indexes on `(session_id, timestamp DESC)`, `(rule_id, timestamp DESC)`,
`(category, timestamp DESC)`, and `(timestamp DESC)` alone — matching the
query patterns the audit/stats endpoints need.

One row per rule **match**, not per request — a single `/guardrails/check`
call can produce 0..N matches, and the audit table mirrors that.

`request_id`/`session_id` are `NOT NULL` in the schema; since both are
`Optional` on `CheckRequest` (existing callers don't always set them),
`write_audit()` coalesces missing values (`request_id` → generated UUID,
`session_id` → `"unknown"`) rather than silently dropping the audit row.

## Write path

Implemented in `src/main.py`'s `/guardrails/check` handler, after
`overall_action` is computed — not inside `src/engine.py`. `evaluate()` is
pure and has no access to `tenant_id`/`session_id`/`request_id`; threading
those through just to persist would leak API-layer concerns into the
evaluation core. `main.py` already has every field the audit row needs in
one place.

Audit writes fail open: `write_audit()` catches all exceptions, logs a
warning, and returns — a Postgres outage must never turn a guardrail
decision into a 500. Same philosophy as `guardrail_client.py`'s existing
network fail-open behavior on the caller side.

## Privacy: truncation defaults

- `matched_span`: truncated to `first_6_chars…last_2_chars` by default
  (e.g. `"1234 5678 9012"` → `"1234 5…12"`).
- `text_sample`: truncated to the first 22 characters + `"..."` by default
  (e.g. `"My Aadhaar 1234 5678 9012"` →
  `"My Aadhaar 1234 5678 9..."`). This is a plain prefix truncation, not a
  first-N/last-N split — unlike `matched_span`, `text_sample` is the whole
  input text, and there's no way to know where in it the PII sits, so a
  prefix cut can't guarantee it's excluded (a message with PII up front
  would still expose it). Full redaction of `text_sample` (stripping each
  match's own span out of the sample, the way `redacted_text` already
  works) is a known gap, not yet implemented.
- Both are controlled by `GUARDRAIL_AUDIT_STORE_RAW_SPAN` (default
  `false`); set to `true` only if full forensic detail is needed.
- The API *response* from `/guardrails/check` still contains the raw
  text — only the persisted audit row is truncated. Caller consumption
  and long-term storage have different privacy models.

## Endpoints

`GET /guardrails/audit` — params: `session_id`, `rule_id`, `category`,
`since`, `limit` (default 100, max 500, validated via FastAPI `Query`).
Returns `{"audit": [...], "count": N}`.

`GET /guardrails/stats` — params: `since`, `group_by` (one of `rule_id`,
`category`, `tenant_id`, `action`, `day`, validated against a strict
allowlist — never string-formatted into the SQL column position). Returns
`{"stats": [{"key": ..., "count": ...}], "since": ..., "group_by": ...}`.

## Postgres wiring

psycopg2 + a lazy singleton connection (not psycopg3/`psycopg_pool` or
SQLAlchemy) — a deliberate deviation from email-agent's driver choice,
per explicit instruction. A separate `guardrail` database on the same
Postgres instance (not email-agent's `email_agent` schema), so
guardrail-service stays independently deployable. Table creation is
`CREATE TABLE IF NOT EXISTS` run from a FastAPI startup hook — no Alembic,
no migration framework, per explicit scope constraint.

## Scope shipped

Full scope (audit table + write path + `/guardrails/audit` +
`/guardrails/stats` + pytest coverage). The Streamlit dashboard in
email-agent-prototype and further follow-ups (token accounting, latency
instrumentation, LangFuse/LangSmith tracing) are separate, later arcs.

## Open questions

- Should `text_sample` redact matched spans out of the sample rather than
  just truncating by position, to close the "PII at the front of the
  message" gap noted above?
- Retention policy for `guardrail_audit` — not yet defined.
- Tenant-scoped access to `/guardrails/audit` and `/guardrails/stats`, or
  global for now?
