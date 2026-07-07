from src.rules.contextual_grounding import ContextualGroundingRule


def test_grounding_warns_on_monetary_claim_without_context():
    rule = ContextualGroundingRule()
    match = rule.check("Your outstanding balance is QAR 4500", "output")
    assert match is not None
    assert match.action == "warn"


def test_grounding_no_warn_when_context_provided():
    rule = ContextualGroundingRule()
    match = rule.check(
        "Your outstanding balance is QAR 4500", "output",
        context={"has_retrieval_context": True},
    )
    assert match is None


def test_grounding_no_warn_on_input_direction():
    """A user stating a monetary figure isn't a grounding problem."""
    rule = ContextualGroundingRule()
    match = rule.check("I was charged QAR 4500 last month", "input")
    assert match is None


def test_grounding_no_match_without_monetary_claim():
    rule = ContextualGroundingRule()
    match = rule.check("Your emails have been indexed successfully", "output")
    assert match is None
