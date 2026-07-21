"""Tests for the self-hosted usage analytics endpoints."""

from fastapi.testclient import TestClient

from src.api.main import app


def test_record_event_without_table_configured_returns_success(monkeypatch):
    """When ANALYTICS_TABLE_NAME isn't set, events are logged, not dropped as errors."""
    monkeypatch.delenv("ANALYTICS_TABLE_NAME", raising=False)
    client = TestClient(app)
    body = {"event_type": "page_view", "anonymous_id": "abc-123", "page": "/"}

    r = client.post("/api/v1/events", json=body, headers={"X-Forwarded-For": "198.51.100.1"})

    assert r.status_code == 200
    assert r.json() == {"success": True}


def test_record_event_rejects_invalid_event_type(monkeypatch):
    monkeypatch.delenv("ANALYTICS_TABLE_NAME", raising=False)
    client = TestClient(app)
    body = {"event_type": "not_a_real_event", "anonymous_id": "abc-123", "page": "/"}

    r = client.post("/api/v1/events", json=body, headers={"X-Forwarded-For": "198.51.100.2"})

    assert r.status_code == 400


def test_record_event_writes_to_dynamodb(monkeypatch):
    """When the table is configured, put_item is called with the event payload."""
    monkeypatch.setenv("ANALYTICS_TABLE_NAME", "lineuplines-analytics-events")
    put_items = []

    class FakeTable:
        def put_item(self, Item):
            put_items.append(Item)

    class FakeResource:
        def Table(self, name):
            return FakeTable()

    monkeypatch.setattr("src.api.analytics_tracking.boto3.resource", lambda *a, **kw: FakeResource())

    client = TestClient(app)
    body = {
        "event_type": "feature_used",
        "anonymous_id": "abc-123",
        "page": "/draftassist/1/2",
        "metadata": {"feature": "best_available_click"},
    }
    r = client.post("/api/v1/events", json=body, headers={"X-Forwarded-For": "198.51.100.3"})

    assert r.status_code == 200
    assert len(put_items) == 1
    assert put_items[0]["event_type"] == "feature_used"
    assert put_items[0]["anonymous_id"] == "abc-123"
    assert put_items[0]["metadata"] == {"feature": "best_available_click"}


def test_summary_requires_admin_token(monkeypatch):
    monkeypatch.setenv("ANALYTICS_TABLE_NAME", "lineuplines-analytics-events")
    monkeypatch.setenv("ANALYTICS_ADMIN_TOKEN", "secret-token")
    client = TestClient(app)

    r = client.get("/api/v1/summary")
    assert r.status_code == 401

    r = client.get("/api/v1/summary", headers={"Authorization": "Bearer wrong-token"})
    assert r.status_code == 401


def test_summary_returns_aggregated_counts(monkeypatch):
    monkeypatch.setenv("ANALYTICS_TABLE_NAME", "lineuplines-analytics-events")
    monkeypatch.setenv("ANALYTICS_ADMIN_TOKEN", "secret-token")

    items = [
        {"event_type": "page_view", "anonymous_id": "visitor-1", "metadata": {}},
        {"event_type": "page_view", "anonymous_id": "visitor-2", "metadata": {}},
        {"event_type": "draft_completed", "anonymous_id": "visitor-1", "metadata": {}},
        {"event_type": "feature_used", "anonymous_id": "visitor-2", "metadata": {"feature": "vor_click"}},
    ]

    class FakeTable:
        def query(self, **kwargs):
            return {"Items": items}

    class FakeResource:
        def Table(self, name):
            return FakeTable()

    monkeypatch.setattr("src.api.analytics_tracking.boto3.resource", lambda *a, **kw: FakeResource())

    client = TestClient(app)
    r = client.get("/api/v1/summary", headers={"Authorization": "Bearer secret-token"})

    assert r.status_code == 200
    data = r.json()
    assert data["unique_visitors"] == 2
    assert data["page_views"] == 2
    assert data["draft_sessions_completed"] == 1
    assert data["feature_usage"] == {"vor_click": 1}
