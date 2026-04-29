"""Feedback endpoint — accepts user submissions and sends them via AWS SES.

The ECS task role must have ses:SendEmail permission on the verified SES domain.
No AWS credentials are hardcoded; boto3 uses the task's IAM role automatically.

Required environment variables:
  SES_FROM_EMAIL  — verified sender address (e.g. feedback@lineuplines.com)
  SES_TO_EMAIL    — your inbox address (e.g. neokl2000@gmail.com)
  AWS_REGION      — defaults to us-east-1 if unset
"""

import logging
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


class FeedbackRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="Feedback text")
    page: str = Field(default="/", max_length=200, description="Page path where feedback was submitted")
    email: str | None = Field(default=None, max_length=200, description="Optional reply-to email from user")


class FeedbackResponse(BaseModel):
    success: bool
    detail: str


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    summary="Submit user feedback",
    tags=["Feedback"],
)
async def submit_feedback(body: FeedbackRequest) -> FeedbackResponse:
    """Receive a feedback submission and forward it to the configured SES address."""
    from_email = os.environ.get("SES_FROM_EMAIL")
    to_email = os.environ.get("SES_TO_EMAIL")

    if not from_email or not to_email:
        # Log the feedback so it isn't lost even if SES isn't configured yet
        logger.warning(
            "SES not configured (SES_FROM_EMAIL/SES_TO_EMAIL missing). "
            "Feedback from page=%s: %s",
            body.page,
            body.message,
        )
        # Return success to the user anyway — don't expose config gaps
        return FeedbackResponse(success=True, detail="Feedback received.")

    region = os.environ.get("AWS_REGION", "us-east-1")

    subject = f"[LineupLines Feedback] from {body.page}"

    reply_section = f"\nReply-to: {body.email}" if body.email else "\nNo reply email provided."

    html_body = f"""
    <html><body>
    <h2>LineupLines Feedback</h2>
    <p><strong>Page:</strong> {body.page}</p>
    <p><strong>Message:</strong></p>
    <blockquote style="border-left: 3px solid #ccc; padding-left: 12px; color: #333;">
      {body.message.replace(chr(10), '<br>')}
    </blockquote>
    <p><strong>User email:</strong> {body.email or '(not provided)'}</p>
    </body></html>
    """

    text_body = (
        f"LineupLines Feedback\n"
        f"Page: {body.page}\n"
        f"Message:\n{body.message}"
        f"{reply_section}"
    )

    try:
        ses = boto3.client("ses", region_name=region)
        ses.send_email(
            Source=from_email,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                },
            },
            ReplyToAddresses=[body.email] if body.email else [],
        )
        logger.info("Feedback email sent for page=%s", body.page)
        return FeedbackResponse(success=True, detail="Feedback received. Thanks!")
    except (BotoCoreError, ClientError) as exc:
        logger.error("SES send_email failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to send feedback. Please try again.")
