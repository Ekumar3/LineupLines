import os
import json
import logging
from datetime import datetime, timezone
from .fetchers.the_odds_api import fetch_odds
from .fetchers.opticodds_fetcher import fetch_season_props

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


def _get_utc_iso_timestamp():
    """Get current UTC timestamp in ISO format with Z suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _get_utc_filename_timestamp():
    """Get current UTC timestamp for use in filenames (YYYYMMDDTHHMMSSZ format)."""
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def handler(event, context):
    """
    Lambda entrypoint: fetches odds or season props and stores results.

    Event parameters:
    - mode: 'game_odds' (default) or 'season_props'
    - sport: sport code (default: 'americanfootball_nfl')
    - season: season year for season props (default: '2026')
    """
    logger.info("Event: %s", json.dumps(event or {}))

    # Parse event parameters
    if not isinstance(event, dict):
        event = {}

    mode = event.get("mode", "game_odds")
    sport = event.get("sport", "americanfootball_nfl")
    season = event.get("season", "2026")

    if mode == "season_props":
        return _handle_season_props(sport, season)
    else:
        return _handle_game_odds(sport)


def _handle_game_odds(sport: str):
    """Fetch and store game-level odds (existing behavior)."""
    try:
        results = fetch_odds(sport=sport)
    except Exception as exc:
        logger.exception("Error fetching game odds: %s", exc)
        raise

    payload = {
        "fetched_at": _get_utc_iso_timestamp(),
        "sport": sport,
        "results": results,
    }

    body = json.dumps(payload, default=str)

    # Try S3 first
    key = f"vegas_lines/{sport}/{_get_utc_filename_timestamp()}.json"
    uploaded = store_to_s3(key, body)

    if not uploaded:
        # Fallback to local storage
        local_path = store_local("latest.json", body)
        return {"status": "stored_local", "path": local_path}

    return {"status": "stored_s3", "s3_key": key}


def _handle_season_props(sport: str, season: str):
    """Fetch and store season-long player props."""
    try:
        results = fetch_season_props(sport=sport, season=season)
    except Exception as exc:
        logger.exception("Error fetching season props: %s", exc)
        raise

    # Season props already have the desired structure, so use as-is
    # Update fetched_at to current time
    results["fetched_at"] = _get_utc_iso_timestamp()

    body = json.dumps(results, default=str)

    # Try S3 first
    key = f"season_props/{sport}/{season}/{_get_utc_filename_timestamp()}.json"
    uploaded = store_to_s3(key, body)

    # Also store latest.json for quick access
    if uploaded:
        store_to_s3(f"season_props/{sport}/{season}/latest.json", body)
    else:
        # Fallback to local storage
        local_path = store_local("season_props_latest.json", body)
        return {"status": "stored_local", "path": local_path}

    return {"status": "stored_s3", "s3_key": key}
