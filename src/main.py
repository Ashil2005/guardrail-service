import logging
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from . import audit
from .engine import load_rules, evaluate
from .rules.base import Action, RuleMatch

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
)
logger = logging.getLogger("guardrail")

app = FastAPI(title="Guardrail Service", version="0.1.0")

CONFIG_PATH = Path(__file__).parent.parent / "config" / "rules.yaml"
_rules = load_rules(CONFIG_PATH)
logger.info(f"Loaded {len(_rules)} rules from {CONFIG_PATH}")


class CheckRequest(BaseModel):
    text: str
    direction: str  # 'input' or 'output'
    tenant_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    # Whether this text was generated with retrieval context behind it
    # (e.g. retrieved emails). Used by contextual_grounding rules — defaults
    # to False so ungrounded claims are flagged unless the caller says
    # otherwise.
    has_retrieval_context: bool = False


class CheckResponse(BaseModel):
    allowed: bool
    action: Action
    matches: list[RuleMatch]
    final_text: str  # text after redaction if any


class AuditRecord(BaseModel):
    id: int
    timestamp: datetime
    request_id: str
    session_id: str
    tenant_id: Optional[str] = None
    direction: str
    rule_id: str
    category: str
    action: str
    matched_span: Optional[str] = None
    text_sample: Optional[str] = None
    reason: Optional[str] = None


class AuditListResponse(BaseModel):
    audit: list[AuditRecord]
    count: int


class StatBucket(BaseModel):
    key: str
    count: int


class StatsResponse(BaseModel):
    stats: list[StatBucket]
    since: Optional[str] = None
    group_by: str


@app.on_event("startup")
def _on_startup():
    audit.init_audit_table()


@app.get("/health")
def health():
    return {"status": "ok", "rules_loaded": len(_rules)}


@app.post("/guardrails/check", response_model=CheckResponse)
def check(req: CheckRequest):
    context = {
        "has_retrieval_context": req.has_retrieval_context,
        "tenant_id": req.tenant_id,
    }
    matches = evaluate(_rules, req.text, req.direction, context=context)

    logger.info(
        f"check tenant={req.tenant_id} direction={req.direction} "
        f"matches={len(matches)} rules={[m.rule_id for m in matches]}"
    )

    if not matches:
        return CheckResponse(
            allowed=True, action=Action.PERMIT, matches=[],
            final_text=req.text,
        )

    # Determine overall action: BLOCK > REDACT > WARN > PERMIT
    action_priority = {Action.BLOCK: 3, Action.REDACT: 2,
                       Action.WARN: 1, Action.PERMIT: 0}
    overall_action = max(matches, key=lambda m: action_priority[m.action]).action

    # If any redaction happened, apply it to the text
    final_text = req.text
    for m in matches:
        if m.redacted_text:
            final_text = m.redacted_text

    audit.write_audit(
        request_id=req.request_id,
        session_id=req.session_id,
        tenant_id=req.tenant_id,
        direction=req.direction,
        matches=matches,
        text_sample=req.text,
    )

    return CheckResponse(
        allowed=(overall_action != Action.BLOCK),
        action=overall_action,
        matches=matches,
        final_text=final_text,
    )


@app.get("/guardrails/audit", response_model=AuditListResponse)
def get_audit(
    session_id: Optional[str] = None,
    rule_id: Optional[str] = None,
    category: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    if since is not None:
        try:
            datetime.fromisoformat(since)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid 'since' date: {since}")

    try:
        records, count = audit.query_audit(
            session_id=session_id, rule_id=rule_id, category=category,
            since=since, limit=limit,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Audit query failed: {e}")

    return AuditListResponse(audit=records, count=count)


@app.get("/guardrails/stats", response_model=StatsResponse)
def get_stats(
    since: Optional[str] = None,
    group_by: str = "rule_id",
):
    if since is not None:
        try:
            datetime.fromisoformat(since)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid 'since' date: {since}")

    if group_by not in audit.GROUP_BY_COLUMNS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid group_by: {group_by}. Must be one of {sorted(audit.GROUP_BY_COLUMNS)}",
        )

    try:
        buckets = audit.query_stats(since=since, group_by=group_by)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Stats query failed: {e}")

    return StatsResponse(stats=buckets, since=since, group_by=group_by)
