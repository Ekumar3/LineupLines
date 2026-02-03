import os
import json
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

try:
    import boto3
except Exception:
    boto3 = None


def get_latest_lines():
    """Return the latest game odds as a parsed dict.

    Priority: S3 (if S3_BUCKET set and boto3 available) -> local file `data/latest.json`.
    """
    s3_bucket = os.environ.get("S3_BUCKET")
    if s3_bucket and boto3:
        s3 = boto3.client("s3")
        # Try common key pattern; callers should ensure this key exists
        keys = ["vegas_lines/latest.json", "latest.json"]
        for key in keys:
            try:
                obj = s3.get_object(Bucket=s3_bucket, Key=key)
                body = obj["Body"].read()
                return json.loads(body)
            except Exception:
                logger.debug("S3 key %s not found or unreadable", key)
        logger.warning("S3 fetch failed; falling back to local file")

    local_path = os.path.join(os.getcwd(), "data", "latest.json")
    with open(local_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_season_props(sport: str = "nfl", season: str = "2026"):
    """Return the latest season-long player props as a parsed dict.

    Priority: S3 (if S3_BUCKET set and boto3 available) -> local file `data/season_props_latest.json`.

    Args:
        sport: Sport code (default: 'nfl')
        season: Season year (default: '2026')

    Returns:
        Dict with structure:
        {
            "fetched_at": ISO timestamp,
            "data_source": "opticodds",
            "sport": sport,
            "season": season,
            "props": [...]
        }

    Raises:
        FileNotFoundError: If no season props data is found in S3 or local storage
    """
    s3_bucket = os.environ.get("S3_BUCKET")
    if s3_bucket and boto3:
        s3 = boto3.client("s3")
        # Try to get the latest.json file for this sport/season
        keys = [
            f"season_props/{sport}/{season}/latest.json",
            f"season_props/{sport}/latest.json",
        ]
        for key in keys:
            try:
                obj = s3.get_object(Bucket=s3_bucket, Key=key)
                body = obj["Body"].read()
                return json.loads(body)
            except Exception:
                logger.debug("S3 key %s not found or unreadable", key)
        logger.warning("S3 fetch failed; falling back to local file")

    # Fallback to local file
    local_path = os.path.join(os.getcwd(), "data", "season_props_latest.json")
    try:
        with open(local_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("Season props file not found at %s", local_path)
        raise


def get_player_props(player_name: str, sport: str = "nfl", season: str = "2026"):
    """Return all season props for a specific player.

    Args:
        player_name: Player name to filter by
        sport: Sport code (default: 'nfl')
        season: Season year (default: '2026')

    Returns:
        List of prop dicts for the specified player
    """
    try:
        season_data = get_season_props(sport=sport, season=season)
    except FileNotFoundError:
        logger.warning("Season props not available for %s/%s", sport, season)
        return []

    props = season_data.get("props", [])
    return [p for p in props if p.get("player_name", "").lower() == player_name.lower()]


def get_props_by_category(category: str, sport: str = "nfl", season: str = "2026"):
    """Return all props for a specific stat category.

    Args:
        category: Stat category (e.g., 'passing_yards', 'rushing_yards')
        sport: Sport code (default: 'nfl')
        season: Season year (default: '2026')

    Returns:
        List of prop dicts for the specified category, sorted by player name
    """
    try:
        season_data = get_season_props(sport=sport, season=season)
    except FileNotFoundError:
        logger.warning("Season props not available for %s/%s", sport, season)
        return []

    props = season_data.get("props", [])
    filtered = [p for p in props if p.get("stat_category") == category]
    return sorted(filtered, key=lambda p: p.get("player_name", ""))
