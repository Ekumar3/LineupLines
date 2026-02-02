import os
import json
import logging
from datetime import datetime
from .fetchers.the_odds_api import fetch_odds

try:
    import boto3
except Exception:
    boto3 = None

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3_BUCKET = os.environ.get("S3_BUCKET")
DATA_DIR = os.environ.get("LOCAL_DATA_DIR", "data")


def store_to_s3(key: str, body: str):
    if not boto3:
        logger.warning("boto3 not available; skipping S3 upload")
        return False
    if not S3_BUCKET:
        logger.warning("S3_BUCKET not configured; skipping S3 upload")
        return False
    s3 = boto3.client("s3")
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=body)
    logger.info(f"Stored object s3://{S3_BUCKET}/{key}")
    return True


def store_local(filename: str, body: str):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    logger.info(f"Wrote local file {path}")
    return path


def handler(event, context):
    """Lambda entrypoint: fetches odds and stores results."""
    logger.info("Event: %s", json.dumps(event or {}))

    sport = event.get("sport") if isinstance(event, dict) else None
    sport = sport or "americanfootball_nfl"

    try:
        results = fetch_odds(sport=sport)
    except Exception as exc:
        logger.exception("Error fetching odds: %s", exc)
        raise

    payload = {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "sport": sport,
        "results": results,
    }

    body = json.dumps(payload, default=str)

    # Try S3 first
    key = f"vegas_lines/{sport}/{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.json"
    uploaded = store_to_s3(key, body)

    if not uploaded:
        # Fallback to local storage
        local_path = store_local("latest.json", body)
        return {"status": "stored_local", "path": local_path}

    return {"status": "stored_s3", "s3_key": key}
