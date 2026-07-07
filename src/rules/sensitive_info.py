import re
from .base import Rule, Category, Action, RuleMatch


class AadhaarFilterRule(Rule):
    """Detects 12-digit Aadhaar numbers (with or without spaces)."""

    def __init__(self, rule_id: str = "sensitive_info.aadhaar",
                 action: Action = Action.REDACT):
        self.rule_id = rule_id
        self.category = Category.SENSITIVE_INFO
        self.default_action = action
        # 4-4-4 with optional spaces/hyphens between groups
        self._pattern = re.compile(
            r'\b(\d{4}[\s-]?\d{4}[\s-]?\d{4})\b'
        )

    def check(self, text: str, direction: str, context: dict | None = None):
        match = self._pattern.search(text)
        if match:
            redacted = self._pattern.sub('[REDACTED-AADHAAR]', text)
            return RuleMatch(
                rule_id=self.rule_id,
                category=self.category,
                action=self.default_action,
                reason="Aadhaar number pattern detected",
                redacted_text=redacted,
                matched_span=match.group(),
            )
        return None
