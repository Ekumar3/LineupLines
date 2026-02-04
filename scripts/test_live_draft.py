"""Script to test live draft tracking with Sleeper API.

Usage:
    python scripts/test_live_draft.py <draft_id>
    python scripts/test_live_draft.py 123456789 --poll-interval 5
    python scripts/test_live_draft.py 123456789 --once
"""

import sys
import logging
import argparse
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_sources.sleeper_client import SleeperClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def format_draft_info(draft_id: str, client: SleeperClient) -> None:
    """Display draft information."""
    logger.info(f"\n{'='*60}")
    logger.info(f"DRAFT ID: {draft_id}")
    logger.info(f"{'='*60}")

    status = client.get_draft_status(draft_id)
    if not status:
        logger.error("Failed to get draft status")
        return

    logger.info(f"Status: {status.status}")
    logger.info(f"Picks made: {status.total_picks_made}")
    logger.info(f"Settings: {status.settings['teams']} teams, {status.settings['rounds']} rounds")

    picks = client.get_draft_picks(draft_id)
    if picks:
        logger.info(f"Last 5 picks:")
        for pick in picks[-5:]:
            logger.info(
                f"  Pick {pick.pick_no:3d} (Round {pick.round}, "
                f"Roster {pick.roster_id}): {pick.player_name:25s} "
                f"{pick.position:4s} ({pick.team})"
            )

    logger.info(f"{'='*60}\n")


def main():
    """Test live draft tracking."""
    parser = argparse.ArgumentParser(
        description="Test Sleeper API live draft tracking"
    )
    parser.add_argument(
        "draft_id",
        help="Sleeper draft ID to monitor"
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="Seconds between polls (default: 5)"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Fetch once and exit (don't continuously poll)"
    )
    parser.add_argument(
        "--max-polls",
        type=int,
        help="Maximum number of polls before stopping"
    )

    args = parser.parse_args()

    # Initialize client
    logger.info("Initializing Sleeper API client...")
    client = SleeperClient()

    # Fetch player universe
    logger.info("Loading player universe (this may take a moment)...")
    try:
        players = client.get_players()
        logger.info(f"Loaded {len(players)} players")
    except Exception as e:
        logger.warning(f"Failed to load player universe: {e}")
        logger.info("Continuing without player data...")

    # Display draft info
    format_draft_info(args.draft_id, client)

    # Fetch once or poll continuously
    if args.once:
        logger.info("Fetching draft data once...")
        try:
            picks = client.get_draft_picks(args.draft_id)
            logger.info(f"Fetched {len(picks)} total picks")

            if picks:
                logger.info("\nAll picks:")
                for pick in picks:
                    logger.info(
                        f"  {pick.pick_no:3d}. {pick.player_name:25s} "
                        f"{pick.position:4s} ({pick.team}) - "
                        f"Roster {pick.roster_id}"
                    )
        except Exception as e:
            logger.error(f"Failed to fetch picks: {e}")
            return 1

    else:
        logger.info(f"Starting live draft polling (interval: {args.poll_interval}s)...")
        logger.info("Press Ctrl+C to stop\n")

        try:
            client.poll_draft_picks(
                args.draft_id,
                poll_interval=args.poll_interval,
                max_polls=args.max_polls
            )
        except KeyboardInterrupt:
            logger.info("\nLive polling stopped")

        # Display final draft info
        format_draft_info(args.draft_id, client)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("\nExiting...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)
