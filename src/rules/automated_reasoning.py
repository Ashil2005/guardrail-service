import re
from .base import Rule, Category, Action, RuleMatch

_OPS = {
    '+': lambda a, b: a + b,
    '-': lambda a, b: a - b,
    '*': lambda a, b: a * b,
    '/': lambda a, b: a / b if b != 0 else None,
}


class ArithmeticCheckRule(Rule):
    """
    Stub for Bedrock-style automated reasoning: catches trivial arithmetic
    errors in the agent's own output by re-computing simple "a OP b = c"
    expressions and comparing against the claimed result.

    Phase 2 will extend this to multi-step logical/numeric consistency
    checks (e.g. a running total that doesn't match its line items) rather
    than single binary operations.
    """

    EXPR_PATTERN = re.compile(
        r'(-?\d+(?:\.\d+)?)\s*([+\-*/])\s*(-?\d+(?:\.\d+)?)\s*=\s*(-?\d+(?:\.\d+)?)'
    )

    def __init__(self, rule_id: str = "automated_reasoning.arithmetic_check",
                 action: Action = Action.WARN):
        self.rule_id = rule_id
        self.category = Category.AUTOMATED_REASONING
        self.default_action = action

    def check(self, text: str, direction: str, context: dict | None = None):
        # Reasoning errors are the agent's problem, not the user's — only
        # check the agent's generated output.
        if direction != 'output':
            return None

        for match in self.EXPR_PATTERN.finditer(text):
            a_str, op, b_str, claimed_str = match.groups()
            a, b, claimed = float(a_str), float(b_str), float(claimed_str)
            compute = _OPS[op]
            actual = compute(a, b)
            if actual is None:
                continue  # division by zero — not an arithmetic-accuracy issue
            if abs(actual - claimed) > 1e-9:
                return RuleMatch(
                    rule_id=self.rule_id,
                    category=self.category,
                    action=self.default_action,
                    reason=(
                        f"Arithmetic error: {a_str} {op} {b_str} = {claimed_str} "
                        f"claimed, but actual result is {actual:g}"
                    ),
                    matched_span=match.group(),
                )
        return None
