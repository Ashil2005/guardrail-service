from src.rules.automated_reasoning import ArithmeticCheckRule


def test_arithmetic_catches_wrong_addition():
    rule = ArithmeticCheckRule()
    match = rule.check("Total: 40 + 5 = 46", "output")
    assert match is not None
    assert "actual result is 45" in match.reason


def test_arithmetic_passes_correct_addition():
    rule = ArithmeticCheckRule()
    match = rule.check("Total: 40 + 5 = 45", "output")
    assert match is None


def test_arithmetic_skips_input_direction():
    """A user's own (possibly wrong) arithmetic isn't the agent's error."""
    rule = ArithmeticCheckRule()
    match = rule.check("Isn't 40 + 5 = 46?", "input")
    assert match is None


def test_arithmetic_no_match_without_expression():
    rule = ArithmeticCheckRule()
    match = rule.check("You have 3 unread emails from accounting", "output")
    assert match is None
