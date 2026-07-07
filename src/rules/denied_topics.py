import re
from .base import Rule, Category, Action, RuleMatch


class DeniedTopicRule(Rule):
    """
    Pattern-based topic detection using phrase matching.
    Phase 2 will upgrade to LLM-based intent classification.
    """

    def __init__(self, rule_id: str, topic_name: str,
                 trigger_phrases: list[str],
                 action: Action = Action.BLOCK):
        self.rule_id = rule_id
        self.topic_name = topic_name
        self.category = Category.DENIED_TOPICS
        self.default_action = action
        # Match any trigger phrase, case insensitive
        self._pattern = re.compile(
            '|'.join(re.escape(p) for p in trigger_phrases),
            re.IGNORECASE,
        )

    def check(self, text: str, direction: str, context: dict | None = None):
        match = self._pattern.search(text)
        if match:
            return RuleMatch(
                rule_id=self.rule_id,
                category=self.category,
                action=self.default_action,
                reason=f"Denied topic: {self.topic_name}",
                matched_span=match.group(),
            )
        return None
