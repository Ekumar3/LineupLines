"""Script to fetch and process FantasyPros ADP data locally.

Usage:
    python scripts/fetch_adp_data.py
    python scripts/fetch_adp_data.py --format ppr
    python scripts/fetch_adp_data.py --format ppr --save-file data/ppr_adp.json
"""

import sys
import logging
import argparse
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_sources.fantasypros_client import FantasyProsClient
from src.analytics.adp_analyzer import ADPAnalyzer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    """Fetch and analyze ADP data."""
    parser = argparse.ArgumentParser(
        description="Fetch FantasyPros ADP data and analyze draft patterns"
    )
    parser.add_argument(
        "--format",
        choices=["ppr", "standard", "half_ppr"],
        default="ppr",
        help="Scoring format (default: ppr)"
    )
    parser.add_argument(
        "--save-file",
        type=str,
        help="Save ADP data to JSON file"
    )
    parser.add_argument(
        "--load-file",
        type=str,
        help="Load ADP data from JSON file instead of fetching"
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        default=True,
        help="Analyze patterns (default: True)"
    )

    args = parser.parse_args()

    # Initialize client
    client = FantasyProsClient()

    # Fetch or load data
    if args.load_file:
        logger.info(f"Loading ADP data from {args.load_file}")
        players = client.load_from_file(args.load_file, args.format)
    else:
        logger.info(f"Fetching {args.format} ADP data from FantasyPros...")
        try:
            players = client.fetch_adp_data(args.format)
        except Exception as e:
            logger.error(f"Failed to fetch data: {e}")
            logger.info("Note: This requires requests and beautifulsoup4")
            logger.info("Install with: pip install requests beautifulsoup4")
            return 1

    if not players:
        logger.warning("No players fetched")
        return 1

    logger.info(f"Fetched {len(players)} players")
    logger.info(f"ADP range: {min(p.adp_overall for p in players):.1f} - {max(p.adp_overall for p in players):.1f}")

    # Show sample data
    logger.info("\nTop 10 players by ADP:")
    sorted_players = sorted(players, key=lambda p: p.adp_overall)
    for i, player in enumerate(sorted_players[:10], 1):
        logger.info(
            f"  {i:2d}. {player.player_name:25s} {player.position:4s} "
            f"ADP: {player.adp_overall:5.1f} Round: {player.round}"
        )

    # Show position distribution
    positions = {}
    for player in players:
        positions[player.position] = positions.get(player.position, 0) + 1

    logger.info("\nPosition distribution:")
    for pos in sorted(positions.keys()):
        logger.info(f"  {pos}: {positions[pos]:3d}")

    # Analyze patterns if requested
    if args.analyze:
        logger.info("\nAnalyzing draft patterns...")
        analyzer = ADPAnalyzer()
        analyzer.analyze(players)

        summary = analyzer.get_analysis_summary()
        logger.info(f"Analysis complete:")
        logger.info(f"  Total players: {summary['total_players_analyzed']}")
        logger.info(f"  Rounds analyzed: {summary['rounds_analyzed']}")
        logger.info(f"  Positions with tiers: {summary['positions_with_tiers']}")
        logger.info(f"  Value rounds identified: {summary['value_rounds_identified']}")

        # Show top value rounds
        logger.info("\nTop 5 value opportunities:")
        for i, value_round in enumerate(analyzer.value_rounds[:5], 1):
            logger.info(
                f"  {i}. Round {value_round.round_num} {value_round.position} "
                f"(value: {value_round.value_score:.2f}) - {value_round.reasoning}"
            )

        # Show round patterns
        logger.info("\nRound 1-5 position frequencies:")
        for round_num in range(1, 6):
            pattern = analyzer.get_round_pattern(round_num)
            if pattern:
                freqs = pattern.position_frequencies
                positions_str = ", ".join(
                    f"{p}: {freqs.get(p, 0)}" for p in ["QB", "RB", "WR", "TE"]
                )
                logger.info(f"  Round {round_num}: {positions_str}")

    # Save if requested
    if args.save_file:
        logger.info(f"Saving to {args.save_file}")
        success = client.save_to_file(args.save_file, args.format)
        if success:
            logger.info("Data saved successfully")
        else:
            logger.error("Failed to save data")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
