import re
from .base import Rule, Category, Action, RuleMatch


class WordFilterRule(Rule):
    def __init__(self, rule_id: str, banned_words: list[str],
                 action: Action = Action.BLOCK):
        self.rule_id = rule_id
        self.category = Category.WORD_FILTER
        self.default_action = action
        # Compile once — word boundary to avoid matching substrings
        self._pattern = re.compile(
            r'\b(' + '|'.join(re.escape(w) for w in banned_words) + r')\b',
            re.IGNORECASE,
        )

    def check(self, text: str, direction: str, context: dict | None = None):
        match = self._pattern.search(text)
        if match:
            return RuleMatch(
                rule_id=self.rule_id,
                category=self.category,
                action=self.default_action,
                reason=f"Banned word matched: {match.group()!r}",
                matched_span=match.group(),
            )
        return None
