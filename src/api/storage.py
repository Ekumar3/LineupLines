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

PLAYER_DATA_DIR = Path("data/players")
PLAYER_DATA_FILE = PLAYER_DATA_DIR / "nfl_players.json"


def save_player_universe(players: Dict[str, Dict[str, Any]]) -> None:
    """Save player universe to local JSON file.

    Args:
        players: Dictionary mapping player_id to player data
    """
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

    Returns:
        Dictionary mapping player_id to player data, or None if file doesn't exist
    """
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
