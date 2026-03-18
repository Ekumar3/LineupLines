"""Storage layer for draft helper API.

Provides abstraction for reading/writing data from S3, DynamoDB, and local files.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

try:
    import boto3
except Exception:
    boto3 = None


# Player Universe Storage

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PLAYER_DATA_DIR = PROJECT_ROOT / "data" / "players"
PLAYER_DATA_FILE = PLAYER_DATA_DIR / "nfl_players.json"

# In-memory cache for player universe (avoids re-reading 19MB file per request)
_player_universe_cache: Optional[Dict[str, Dict[str, Any]]] = None


def save_player_universe(players: Dict[str, Dict[str, Any]]) -> None:
    """Save player universe to local JSON file.

    Args:
        players: Dictionary mapping player_id to player data
    """
    global _player_universe_cache
    _player_universe_cache = None  # Invalidate cache so next load picks up new data

    # Create parent directories for the file
    PLAYER_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "player_count": len(players),
        "players": players
    }

    with open(PLAYER_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

    logger.info(f"Saved {len(players)} players to {PLAYER_DATA_FILE}")


def load_player_universe() -> Optional[Dict[str, Dict[str, Any]]]:
    """Load player universe from local JSON file.

    Uses in-memory cache to avoid re-reading the 19MB file on every request.

    Returns:
        Dictionary mapping player_id to player data, or None if file doesn't exist
    """
    global _player_universe_cache

    if _player_universe_cache is not None:
        return _player_universe_cache

    if not PLAYER_DATA_FILE.exists():
        logger.warning(f"Player data file not found: {PLAYER_DATA_FILE}")
        return None

    try:
        with open(PLAYER_DATA_FILE, 'r') as f:
            data = json.load(f)

        updated_at = data.get("updated_at")
        player_count = data.get("player_count", 0)
        players = data.get("players", {})

        logger.info(f"Loaded {player_count} players (updated: {updated_at})")
        _player_universe_cache = players
        return players

    except Exception as e:
        logger.error(f"Failed to load player data: {e}")
        return None


def get_player_universe_age() -> Optional[str]:
    """Get the age of stored player data.

    Returns:
        ISO timestamp of when data was last updated, or None if no data
    """
    if not PLAYER_DATA_FILE.exists():
        return None

    try:
        with open(PLAYER_DATA_FILE, 'r') as f:
            data = json.load(f)
        return data.get("updated_at")
    except:
        return None
