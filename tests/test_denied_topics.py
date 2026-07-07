from src.rules.denied_topics import DeniedTopicRule

RULE_KWARGS = dict(
    rule_id="denied_topics.medical_advice",
    topic_name="personal medical advice",
    trigger_phrases=["should I take", "medical advice", "diagnose my", "my symptoms are"],
)


def test_denied_topic_matches_trigger_phrase():
    rule = DeniedTopicRule(**RULE_KWARGS)
    match = rule.check("should I take ibuprofen for this headache", "input")
    assert match is not None
    assert match.category == "denied_topics"


def test_denied_topic_case_insensitive():
    rule = DeniedTopicRule(**RULE_KWARGS)
    match = rule.check("Can you give me MEDICAL ADVICE about this rash", "input")
    assert match is not None


def test_denied_topic_no_match_on_business_query():
    rule = DeniedTopicRule(**RULE_KWARGS)
    match = rule.check("what emails did I receive from accounting this week", "input")
    assert match is None


def test_denied_topic_reason_includes_topic_name():
    rule = DeniedTopicRule(**RULE_KWARGS)
    match = rule.check("please diagnose my condition", "input")
    assert match is not None
    assert "personal medical advice" in match.reason
