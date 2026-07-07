from src.rules.sensitive_info import AadhaarFilterRule


def test_aadhaar_matches_spaced():
    rule = AadhaarFilterRule()
    match = rule.check("My Aadhaar is 1234 5678 9012", "output")
    assert match is not None
    assert match.matched_span == "1234 5678 9012"


def test_aadhaar_matches_unspaced():
    rule = AadhaarFilterRule()
    match = rule.check("Aadhaar: 123456789012", "output")
    assert match is not None


def test_aadhaar_redacts_text():
    rule = AadhaarFilterRule()
    match = rule.check("My Aadhaar is 1234 5678 9012, thanks", "output")
    assert match is not None
    assert match.redacted_text == "My Aadhaar is [REDACTED-AADHAAR], thanks"


def test_aadhaar_no_match_on_clean_text():
    rule = AadhaarFilterRule()
    match = rule.check("how many emails do i have today", "input")
    assert match is None
