import logging
from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

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


@app.get("/health")
def health():
    return {"status": "ok", "rules_loaded": len(_rules)}


@app.post("/guardrails/check", response_model=CheckResponse)
def check(req: CheckRequest):
    context = {"has_retrieval_context": req.has_retrieval_context}
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

    return CheckResponse(
        allowed=(overall_action != Action.BLOCK),
        action=overall_action,
        matches=matches,
        final_text=final_text,
    )
