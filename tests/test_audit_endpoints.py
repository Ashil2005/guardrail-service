from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def _seed(text, direction, tenant_id, session_id, request_id):
    r = client.post("/guardrails/check", json={
        "text": text, "direction": direction,
        "tenant_id": tenant_id, "session_id": session_id, "request_id": request_id,
    })
    assert r.status_code == 200
    return r


def test_audit_list_filters(pg_test_conn):
    _seed("dammit that is annoying", "input", "accounts", "sess-a", "req-a")
    _seed("should I take this medication", "input", "marketing", "sess-b", "req-b")
    _seed("My Aadhaar is 1234 5678 9012", "output", "accounts", "sess-c", "req-c")

    r = client.get("/guardrails/audit", params={"session_id": "sess-a"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["audit"][0]["rule_id"] == "word_filter.default_blocklist"

    r = client.get("/guardrails/audit", params={"rule_id": "denied_topics.medical_advice"})
    body = r.json()
    assert body["count"] == 1
    assert body["audit"][0]["session_id"] == "sess-b"

    r = client.get("/guardrails/audit", params={"category": "sensitive_info"})
    body = r.json()
    assert body["count"] == 1
    assert body["audit"][0]["tenant_id"] == "accounts"

    r = client.get("/guardrails/audit", params={"limit": 2})
    body = r.json()
    assert len(body["audit"]) == 2
    assert body["count"] == 3  # count reflects total matches, not the page size


def test_audit_stats_by_rule(pg_test_conn):
    _seed("dammit that is annoying", "input", "accounts", "sess-a", "req-a")
    _seed("dammit again", "input", "accounts", "sess-a2", "req-a2")
    _seed("should I take this medication", "input", "marketing", "sess-b", "req-b")

    r = client.get("/guardrails/stats", params={"group_by": "rule_id"})
    assert r.status_code == 200
    body = r.json()
    assert body["group_by"] == "rule_id"
    buckets = {b["key"]: b["count"] for b in body["stats"]}
    assert buckets["word_filter.default_blocklist"] == 2
    assert buckets["denied_topics.medical_advice"] == 1


def test_audit_stats_invalid_group_by_rejected(pg_test_conn):
    r = client.get("/guardrails/stats", params={"group_by": "'; DROP TABLE guardrail_audit; --"})
    assert r.status_code == 400
