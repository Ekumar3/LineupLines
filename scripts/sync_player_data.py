"""Script to fetch and sync player universe data from Sleeper API.

Fetches the complete NFL player universe and saves it to local storage.
Can be run manually or scheduled as a daily cron job.

Usage:
    python scripts/sync_player_data.py
"""

import sys
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_sources.sleeper_client import SleeperClient
from src.api.storage import save_player_universe, get_player_universe_age

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """Fetch and save player universe from Sleeper API."""
    logger.info("Starting player data sync...")

    # Show current player data age
    current_age = get_player_universe_age()
    if current_age:
        logger.info(f"Current player data last updated: {current_age}")
    else:
        logger.info("No existing player data found")

    # Fetch fresh data from Sleeper
    client = SleeperClient()
    logger.info("Fetching players from Sleeper API...")

    try:
        players = client.get_players(force_refresh=True)

        if not players:
            logger.error("Failed to fetch players from Sleeper API")
            return 1

        logger.info(f"Fetched {len(players)} players from Sleeper")

        # Save to local storage
        save_player_universe(players)
        logger.info("Player data sync complete")

        # Show new player data age
        new_age = get_player_universe_age()
        logger.info(f"New player data last updated: {new_age}")

        return 0

    except Exception as e:
        logger.error(f"Error during player data sync: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
