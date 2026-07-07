import re
from .base import Rule, Category, Action, RuleMatch


class ContextualGroundingRule(Rule):
    """
    Stub for Bedrock-style contextual grounding: flags monetary claims made
    with no retrieval context behind them (i.e. the answer wasn't backed by
    any retrieved emails/documents). A real amount cited without a source is
    exactly the shape of hallucination this category exists to catch.

    Phase 2 will replace the "was any context passed at all" heuristic with
    real semantic grounding (embedding similarity between the claim and the
    retrieved source text).
    """

    MONEY_PATTERN = re.compile(
        r'\b(?:USD|QAR|AED|SAR|Rs\.?|\$)\s?\d[\d,]*(?:\.\d+)?\b',
        re.IGNORECASE,
    )

    def __init__(self, rule_id: str = "contextual_grounding.monetary_claims",
                 action: Action = Action.WARN):
        self.rule_id = rule_id
        self.category = Category.CONTEXTUAL_GROUNDING
        self.default_action = action

    def check(self, text: str, direction: str, context: dict | None = None):
        # Only meaningful on the agent's own output — a user is always
        # "grounded" in their own claims.
        if direction != 'output':
            return None

        has_context = bool(context) and context.get('has_retrieval_context', False)
        if has_context:
            return None

        match = self.MONEY_PATTERN.search(text)
        if match:
            return RuleMatch(
                rule_id=self.rule_id,
                category=self.category,
                action=self.default_action,
                reason="Monetary claim made with no retrieval context to ground it",
                matched_span=match.group(),
            )
        return None
