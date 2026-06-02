"""Tests for IP-based rate limiting and DraftBroadcaster capacity caps.

These guard against the abuse vectors documented in the security audit:
- /api/v1/feedback spammed to flood SES (and rack up the bill)
- Default-protected endpoints (60/min) hammered to exhaust Sleeper quota
- DraftBroadcaster leaked via thousands of unique fake draft_ids

slowapi's in-memory storage is shared across tests in the same process, so
each test uses a distinct X-Forwarded-For value to keep its bucket isolated.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from src.api.draft_stream import BroadcasterCapacityError, DraftBroadcaster
from src.api.main import app


def test_feedback_rate_limit_blocks_after_5_requests():
    """The 6th feedback submission within a minute should be rejected with 429."""
    client = TestClient(app)
    headers = {"X-Forwarded-For": "203.0.113.10"}  # unique IP for this test
    body = {"message": "test feedback", "page": "/", "email": None}

    for i in range(5):
        r = client.post("/api/v1/feedback", json=body, headers=headers)
        assert r.status_code == 200, f"Request {i + 1} should succeed, got {r.status_code}"

    r = client.post("/api/v1/feedback", json=body, headers=headers)
    assert r.status_code == 429, "6th request within a minute should be rate-limited"


def test_default_rate_limit_blocks_after_60_requests():
    """A non-decorated endpoint should fall back to the 60/minute default."""
    client = TestClient(app)
    headers = {"X-Forwarded-For": "203.0.113.20"}  # unique IP for this test
    blocked = False
    for _ in range(75):
        r = client.get("/health", headers=headers)
        if r.status_code == 429:
            blocked = True
            break
    assert blocked, "Default 60/minute limit should reject requests beyond the threshold"


def test_xff_header_used_as_rate_limit_key():
    """Two different X-Forwarded-For IPs should each get their own bucket."""
    client = TestClient(app)
    body = {"message": "test", "page": "/", "email": None}

    # Exhaust the limit for client A.
    for _ in range(5):
        client.post("/api/v1/feedback", json=body, headers={"X-Forwarded-For": "203.0.113.30"})
    r_blocked = client.post(
        "/api/v1/feedback", json=body, headers={"X-Forwarded-For": "203.0.113.30"}
    )
    assert r_blocked.status_code == 429

    # Client B should still have a full bucket.
    r_other = client.post(
        "/api/v1/feedback", json=body, headers={"X-Forwarded-For": "203.0.113.31"}
    )
    assert r_other.status_code == 200, "Different IP should not be rate-limited"


def test_cors_locked_down_to_expected_methods():
    """CORS preflight should advertise only the allow-listed methods."""
    client = TestClient(app)
    r = client.options(
        "/api/v1/feedback",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert r.status_code == 200
    allowed = r.headers.get("access-control-allow-methods", "")
    # Methods we explicitly allow
    for method in ["GET", "POST", "OPTIONS"]:
        assert method in allowed, f"{method} should be in allow-methods"
    # Methods we explicitly rejected (no wildcard anymore)
    for method in ["PUT", "DELETE", "PATCH"]:
        assert method not in allowed, f"{method} should NOT be in allow-methods"


# ── DraftBroadcaster capacity tests ──────────────────────────────────────────


class _StubSleeperClient:
    """Minimal stub — broadcaster never actually polls in these tests."""

    def get_draft_picks(self, draft_id):
        return []

    def get_draft_details(self, draft_id):
        return None


def test_broadcaster_rejects_51st_unique_draft():
    """MAX_ACTIVE_DRAFTS=50 must hard-cap unique draft_id allocation."""
    async def _run():
        b = DraftBroadcaster(_StubSleeperClient())
        # Fill to the cap — these should all succeed.
        for i in range(DraftBroadcaster.MAX_ACTIVE_DRAFTS):
            await b.subscribe(f"draft-{i}")

        # 51st unique draft must be rejected.
        with pytest.raises(BroadcasterCapacityError):
            await b.subscribe("draft-overflow")

        # Cleanup so background tasks don't leak warnings.
        for i in range(DraftBroadcaster.MAX_ACTIVE_DRAFTS):
            draft_id = f"draft-{i}"
            for q in list(b._queues.get(draft_id, [])):
                await b.unsubscribe(draft_id, q)

    asyncio.run(_run())


def test_broadcaster_rejects_51st_subscriber_to_same_draft():
    """MAX_SUBSCRIBERS_PER_DRAFT=50 must hard-cap viewers on one draft."""
    async def _run():
        b = DraftBroadcaster(_StubSleeperClient())
        draft_id = "popular-draft"

        for _ in range(DraftBroadcaster.MAX_SUBSCRIBERS_PER_DRAFT):
            await b.subscribe(draft_id)

        with pytest.raises(BroadcasterCapacityError):
            await b.subscribe(draft_id)

        # Cleanup
        for q in list(b._queues.get(draft_id, [])):
            await b.unsubscribe(draft_id, q)

    asyncio.run(_run())


def test_broadcaster_reuses_slot_after_unsubscribe():
    """After all subscribers leave a draft, its slot should free up for a new draft."""
    async def _run():
        b = DraftBroadcaster(_StubSleeperClient())

        # Fill to cap.
        for i in range(DraftBroadcaster.MAX_ACTIVE_DRAFTS):
            await b.subscribe(f"draft-{i}")

        # Free one slot by unsubscribing all viewers from draft-0.
        for q in list(b._queues["draft-0"]):
            await b.unsubscribe("draft-0", q)

        # A new unique draft_id should now fit.
        new_q = await b.subscribe("draft-new")
        assert new_q is not None

        # Cleanup
        for i in range(1, DraftBroadcaster.MAX_ACTIVE_DRAFTS):
            draft_id = f"draft-{i}"
            for q in list(b._queues.get(draft_id, [])):
                await b.unsubscribe(draft_id, q)
        for q in list(b._queues.get("draft-new", [])):
            await b.unsubscribe("draft-new", q)

    asyncio.run(_run())
