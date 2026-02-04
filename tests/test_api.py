"""Tests for Draft Helper API."""

from fastapi.testclient import TestClient
import pytest

from src.api.main import app


def test_health():
    """Test health check endpoint."""
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "draft-helper"}
