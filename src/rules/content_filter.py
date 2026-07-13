import re
from .base import Rule, Category, Action, RuleMatch


class PromptInjectionRule(Rule):
    """
    Detects common prompt injection patterns.
    Phase 2 will add Llama Guard 3 for broader content moderation.
    """

    INJECTION_PATTERNS = [
        r'ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts)',
        r'disregard\s+the\s+(above|previous)',
        r'you\s+are\s+now\s+',
        r'system\s*[:\-]\s*',
        r'</?system>',
        r'<\|.*?\|>',  # llama-style special tokens
        r'reveal\s+(your\s+)?(system\s+prompt|instructions)',
        # Instruction-override paraphrases — attackers rarely use the exact
        # "ignore previous instructions" wording the patterns above expect.
        r'ignore\s+(all\s+)?(the\s+|your\s+|previous\s+|above\s+|that\s+)?(system\s+)?(instructions?|directions?|rules?|prompts?)',
        r'disregard\s+(the\s+|all\s+|your\s+|previous\s+|above\s+|that\s+)?(system\s+)?(instructions?|directions?|rules?|prompts?)',
        r'forget\s+(the\s+|all\s+|your\s+|previous\s+|above\s+|that\s+)?(system\s+)?(instructions?|directions?|rules?|prompts?|system)',
        r'override\s+(the\s+|all\s+|your\s+|previous\s+|that\s+)?(system\s+)?(instructions?|directions?|rules?|prompts?|system)',
        r'do\s+not\s+follow\s+(the\s+|any\s+|your\s+|previous\s+|that\s+)?(instructions?|rules?|guidelines?)',
        # System-prompt / rules disclosure paraphrases
        r'(reveal|show|print|display|give|tell)\s+(me\s+)?(the\s+|your\s+)?(system\s+)?(prompts?|instructions?|rules?|configuration)',
        r'what\s+(is|are)\s+(the\s+|your\s+)?(system\s+)?(prompts?|instructions?|rules?)',
        r'repeat\s+(the\s+|your\s+)?(system\s+)?(prompts?|instructions?)',
        # Role-hijack paraphrases ("you are now" above already covers the
        # broadest form of this attack)
        r'act\s+as\s+(a\s+)?(different|new|jailbroken|unrestricted)',
        r'pretend\s+to\s+be\s+(a\s+)?(different|new|jailbroken)',
    ]

    def __init__(self, rule_id: str = "content_filter.prompt_injection",
                 action: Action = Action.BLOCK):
        self.rule_id = rule_id
        self.category = Category.CONTENT_FILTER
        self.default_action = action
        self._pattern = re.compile(
            '|'.join(f'({p})' for p in self.INJECTION_PATTERNS),
            re.IGNORECASE,
        )

    def check(self, text: str, direction: str, context: dict | None = None):
        # Only check input direction — injection is a user input issue
        if direction != 'input':
            return None
        match = self._pattern.search(text)
        if match:
            return RuleMatch(
                rule_id=self.rule_id,
                category=self.category,
                action=self.default_action,
                reason="Prompt injection pattern detected",
                matched_span=match.group(),
            )
        return None
