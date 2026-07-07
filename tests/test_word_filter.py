from src.rules.word_filter import WordFilterRule


def test_word_filter_matches_exact():
    rule = WordFilterRule("test", ["banned"])
    match = rule.check("this contains banned word", "input")
    assert match is not None
    assert match.matched_span == "banned"


def test_word_filter_case_insensitive():
    rule = WordFilterRule("test", ["banned"])
    match = rule.check("this contains BANNED word", "input")
    assert match is not None


def test_word_filter_word_boundary():
    """Should NOT match substrings."""
    rule = WordFilterRule("test", ["ban"])
    match = rule.check("banana is fine", "input")
    assert match is None


def test_word_filter_no_match():
    rule = WordFilterRule("test", ["banned"])
    match = rule.check("this is clean text", "input")
    assert match is None
