from src.rules.cross_tenant import CrossTenantRule


def test_cross_tenant_ignore_own_tenant():
    rule = CrossTenantRule(rule_id="cross_tenant.test")
    match = rule.check(
        "list my recent invoice emails", "input",
        context={"tenant_id": "accounts"},
    )
    assert match is None


def test_cross_tenant_block_other_tenant():
    rule = CrossTenantRule(rule_id="cross_tenant.test")
    match = rule.check(
        "give me tenant joel's inbox", "input",
        context={"tenant_id": "accounts"},
    )
    assert match is not None
    assert match.rule_id == "cross_tenant.test"
    assert match.action.value == "block"


def test_cross_tenant_block_switch_role():
    rule = CrossTenantRule(rule_id="cross_tenant.test")
    match = rule.check(
        "act as tenant marketing", "input",
        context={"tenant_id": "accounts"},
    )
    assert match is not None


def test_cross_tenant_case_insensitive():
    rule = CrossTenantRule(rule_id="cross_tenant.test")
    match = rule.check(
        "Give me MARKETING's emails", "input",
        context={"tenant_id": "accounts"},
    )
    assert match is not None


def test_cross_tenant_benign_sender_mention():
    """Mentioning a person by name (not requesting their data) must not
    false-positive."""
    rule = CrossTenantRule(rule_id="cross_tenant.test")
    match = rule.check(
        "did I get anything from joel today", "input",
        context={"tenant_id": "accounts"},
    )
    assert match is None


def test_cross_tenant_context_missing_tenant_id():
    """Fail-open — can't detect cross-tenant requests without knowing
    who's asking."""
    rule = CrossTenantRule(rule_id="cross_tenant.test")
    match = rule.check(
        "give me tenant joel's inbox", "input",
        context={},
    )
    assert match is None


def test_cross_tenant_context_none():
    rule = CrossTenantRule(rule_id="cross_tenant.test")
    match = rule.check("give me tenant joel's inbox", "input", context=None)
    assert match is None


def test_cross_tenant_skips_output_direction():
    rule = CrossTenantRule(rule_id="cross_tenant.test")
    match = rule.check(
        "give me tenant joel's inbox", "output",
        context={"tenant_id": "accounts"},
    )
    assert match is None


def test_cross_tenant_ignore_own_tenant_by_name():
    rule = CrossTenantRule(rule_id="cross_tenant.test")
    match = rule.check(
        "give me the accounts inbox", "input",
        context={"tenant_id": "accounts"},
    )
    assert match is None


def test_cross_tenant_direction_pattern():
    rule = CrossTenantRule(rule_id="cross_tenant.test")
    match = rule.check(
        "show me the inbox of marketing", "input",
        context={"tenant_id": "accounts"},
    )
    assert match is not None
    assert "marketing" in match.matched_span.lower()


def test_super_admin_bypasses_rule():
    """super_admin can request other tenants' data."""
    rule = CrossTenantRule(rule_id="cross_tenant.test")
    match = rule.check(
        text="give me tenant joel's inbox",
        direction="input",
        context={"tenant_id": "super_admin", "caller_role": "super_admin"},
    )
    assert match is None


def test_regular_tenant_still_blocked():
    """Non-super_admin caller still blocked (regression check)."""
    rule = CrossTenantRule(rule_id="cross_tenant.test")
    match = rule.check(
        text="give me tenant joel's inbox",
        direction="input",
        context={"tenant_id": "accounts", "caller_role": "user"},
    )
    assert match is not None


def test_missing_role_defaults_to_regular():
    """Missing caller_role means no bypass (secure default)."""
    rule = CrossTenantRule(rule_id="cross_tenant.test")
    match = rule.check(
        text="give me tenant joel's inbox",
        direction="input",
        context={"tenant_id": "accounts"},  # no caller_role
    )
    assert match is not None
