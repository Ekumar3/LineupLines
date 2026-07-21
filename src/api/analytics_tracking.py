"""Self-hosted usage analytics — page views, draft completions, feature clicks.

Events are written to DynamoDB via the ECS task's IAM role (no hardcoded
credentials). If ANALYTICS_TABLE_NAME isn't set (e.g. local dev), events are
logged instead of written, mirroring how feedback.py degrades when SES isn't
configured.

Required environment variables:
  ANALYTICS_TABLE_NAME   — DynamoDB table name (from the analytics Terraform module)
  ANALYTICS_ADMIN_TOKEN  — bearer token required to read /summary
  AWS_REGION             — defaults to us-east-1 if unset
"""

import logging
import os
import secrets
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_EVENT_TYPES = {"page_view", "draft_completed", "feature_used"}


class EventRequest(BaseModel):
    event_type: str = Field(..., description="One of: page_view, draft_completed, feature_used")
    anonymous_id: str = Field(..., min_length=1, max_length=100)
    page: str = Field(default="/", max_length=200)
    metadata: dict[str, Any] | None = Field(default=None)


class EventResponse(BaseModel):
    success: bool


class SummaryResponse(BaseModel):
    days: int
    unique_visitors: int
    page_views: int
    draft_sessions_completed: int
    feature_usage: dict[str, int]


def _table():
    table_name = os.environ.get("ANALYTICS_TABLE_NAME")
    if not table_name:
        return None
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


@router.post("/events", response_model=EventResponse, summary="Record a usage event", tags=["Analytics"])
@limiter.limit("30/minute")
async def record_event(request: Request, body: EventRequest) -> EventResponse:
    """Record a page view, draft completion, or feature-use event."""
    if body.event_type not in VALID_EVENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid event_type: {body.event_type}")

    table = _table()
    if table is None:
        logger.info(
            "Analytics table not configured; dropping event type=%s page=%s",
            body.event_type,
            body.page,
        )
        return EventResponse(success=True)

    now = datetime.now(timezone.utc)
    item = {
        "pk": "EVENT",
        "sk": f"{now.isoformat()}#{body.anonymous_id}",
        "event_type": body.event_type,
        "anonymous_id": body.anonymous_id,
        "page": body.page,
        "timestamp": now.isoformat(),
        "metadata": body.metadata or {},
    }

    try:
        table.put_item(Item=item)
    except (BotoCoreError, ClientError) as exc:
        logger.error("Failed to record analytics event: %s", exc)
        # Never fail the request over a tracking write — the caller doesn't need to know.
        return EventResponse(success=True)

    return EventResponse(success=True)


@router.get("/summary", response_model=SummaryResponse, summary="Aggregate usage stats", tags=["Analytics"])
async def get_summary(days: int = 7, authorization: Optional[str] = Header(default=None)) -> SummaryResponse:
    """Return aggregated usage counts for the trailing `days` days. Requires a bearer token."""
    admin_token = os.environ.get("ANALYTICS_ADMIN_TOKEN")
    expected = f"Bearer {admin_token}" if admin_token else None
    if not admin_token or not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")

    table = _table()
    if table is None:
        raise HTTPException(status_code=503, detail="Analytics table not configured")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        response = table.query(
            KeyConditionExpression="pk = :pk AND sk >= :cutoff",
            ExpressionAttributeValues={":pk": "EVENT", ":cutoff": cutoff.isoformat()},
        )
        items = response.get("Items", [])
        while "LastEvaluatedKey" in response:
            response = table.query(
                KeyConditionExpression="pk = :pk AND sk >= :cutoff",
                ExpressionAttributeValues={":pk": "EVENT", ":cutoff": cutoff.isoformat()},
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))
    except (BotoCoreError, ClientError) as exc:
        logger.error("Failed to query analytics events: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load analytics")

    unique_visitors = {item["anonymous_id"] for item in items}
    page_views = sum(1 for item in items if item["event_type"] == "page_view")
    draft_completed = sum(1 for item in items if item["event_type"] == "draft_completed")
    feature_counts = Counter(
        item.get("metadata", {}).get("feature", "unknown")
        for item in items
        if item["event_type"] == "feature_used"
    )

    return SummaryResponse(
        days=days,
        unique_visitors=len(unique_visitors),
        page_views=page_views,
        draft_sessions_completed=draft_completed,
        feature_usage=dict(feature_counts),
    )
