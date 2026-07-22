import re
from .base import Rule, Category, Action, RuleMatch


# Hardcoded tenant list for MVP — must match email-agent-prototype's
# config/tenants.py registry. Config-driven sync is a fast-follow;
# until then a new tenant added there needs a matching edit here.
TENANT_ALIASES = ["accounts", "joel", "marketing", "askme"]


class CrossTenantRule(Rule):
    """
    Detects requests that reference another tenant's data by name —
    e.g. "give me tenant joel's inbox" from a caller in "accounts".

    Tools already scope strictly to the caller's own tenant, so this
    isn't a data-leak defense — it stops the confused-deputy case where
    the agent answers with the caller's own data but a response that
    reads as if it were the other tenant's.

    The caller's own tenant is excluded from matching at check time
    (via context['tenant_id']), so self-references never false-positive.
    """

    def __init__(self, rule_id: str, action: Action = Action.BLOCK):
        self.rule_id = rule_id
        self.category = Category.CROSS_TENANT
        self.default_action = action
        alias_group = '|'.join(re.escape(t) for t in TENANT_ALIASES)
        self._patterns = [
            re.compile(
                rf"\b(?:tenant\s+)?({alias_group})(?:'s|s)?\s+"
                rf"(?:inbox|emails?|mailbox|messages|data|account)\b",
                re.IGNORECASE,
            ),
            re.compile(
                rf"\b(?:inbox|emails?|mailbox|messages|data|account)\s+"
                rf"(?:of|for|belonging\s+to)\s+(?:tenant\s+)?({alias_group})\b",
                re.IGNORECASE,
            ),
            re.compile(
                rf"\b(?:act\s+as|switch\s+to|log\s+in\s+as|pretend\s+to\s+be|impersonate)\s+"
                rf"(?:tenant\s+)?({alias_group})\b",
                re.IGNORECASE,
            ),
        ]

    def check(self, text: str, direction: str, context: dict | None = None):
        # Only the caller's own request text is relevant — not the
        # agent's response.
        if direction != 'input':
            return None

        if (context or {}).get('caller_role') == 'super_admin':
            return None

        caller_tenant = (context or {}).get('tenant_id')
        if not caller_tenant:
            # Can't tell what's cross-tenant without knowing who's asking.
            return None

        for pattern in self._patterns:
            for match in pattern.finditer(text):
                if match.group(1).lower() != caller_tenant.lower():
                    return RuleMatch(
                        rule_id=self.rule_id,
                        category=self.category,
                        action=self.default_action,
                        reason=(
                            f"Cross-tenant request detected: references "
                            f"'{match.group(1)}' but caller is '{caller_tenant}'"
                        ),
                        matched_span=match.group(0),
                    )
        return None
