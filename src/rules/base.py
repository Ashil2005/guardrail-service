from enum import Enum
from typing import Optional
from pydantic import BaseModel


class Category(str, Enum):
    WORD_FILTER = "word_filter"
    SENSITIVE_INFO = "sensitive_info"
    DENIED_TOPICS = "denied_topics"
    CONTENT_FILTER = "content_filter"
    CONTEXTUAL_GROUNDING = "contextual_grounding"
    AUTOMATED_REASONING = "automated_reasoning"
    CROSS_TENANT = "cross_tenant"


class Action(str, Enum):
    BLOCK = "block"
    REDACT = "redact"
    WARN = "warn"
    PERMIT = "permit"


class RuleMatch(BaseModel):
    rule_id: str
    category: Category
    action: Action
    reason: str
    redacted_text: Optional[str] = None  # if action == redact
    matched_span: Optional[str] = None    # for logging/debugging


class Rule:
    """Base class for all guardrail rules."""
    rule_id: str
    category: Category
    default_action: Action

    def check(
        self, text: str, direction: str, context: Optional[dict] = None
    ) -> Optional[RuleMatch]:
        """Return RuleMatch if this rule fires, None otherwise.
        direction is 'input' or 'output'. context carries optional metadata
        (e.g. whether retrieval context backed the answer) — most rules
        ignore it; ContextualGroundingRule is the current exception."""
        raise NotImplementedError
