"""Convert a local DraftSharks ADP snapshot into the S3 schema adp_sources.py
expects, and upload it so the "DraftSharks" ADP source toggle has real data.

Reads from the same local snapshot DraftSharksClient already uses
(data/players/{format}_*_players.json, or live-scrapes if none exists), then
uploads s3://{ADP_S3_BUCKET}/adp/draftsharks/{format}/latest.json in the shape:

    {
      "scraped_at": "<utc iso8601>",
      "source": "draftsharks",
      "scoring_format": "ppr",
      "players": [
        {"name": "josh allen", "position": "QB", "team": "BUF", "adp": 25.0, "tier": 3, "positional_tier": 2}
      ]
    }

Position is included alongside each name because name alone isn't a unique key
(e.g. the real QB Josh Allen and LB Josh Allen both play in the NFL) — the
reader joins on (normalized_name, position), not name alone.

Usage:
    python scripts/upload_draftsharks_adp_snapshot.py
    python scripts/upload_draftsharks_adp_snapshot.py --format ppr
    python scripts/upload_draftsharks_adp_snapshot.py --format ppr --dry-run
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_sources.draft_sharks_client import DraftSharksClient
from src.analytics.adp_service import adp_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def build_snapshot(scoring_format: str) -> dict:
    """Fetch the local/cached DraftSharks ADP data and convert to the S3 schema."""
    client = DraftSharksClient()
    players = client.fetch_adp_data(scoring_format)
    if not players:
        raise RuntimeError(f"No DraftSharks ADP data available for format '{scoring_format}'")

    player_records = [
        {
            "name": adp_service.normalize_player_name(p.player_name),
            "position": p.position,
            "team": p.team,
            "adp": p.adp_overall,
            "tier": p.tier,
            "positional_tier": p.positional_tier,
        }
        for p in players
    ]

    return {
        "scraped_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "draftsharks",
        "scoring_format": scoring_format,
        "players": player_records,
    }


def upload_snapshot(snapshot: dict, scoring_format: str) -> None:
    import os
    import boto3

    bucket = "lineuplines-player-data-prod"
    if not bucket:
        raise RuntimeError("ADP_S3_BUCKET environment variable is not set")

    key = f"adp/draftsharks/{scoring_format}/latest.json"
    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(snapshot).encode("utf-8"),
        ContentType="application/json",
    )
    logger.info(f"Uploaded {len(snapshot['players'])} players to s3://{bucket}/{key}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=["ppr", "standard", "half_ppr"],
        default="ppr",
        help="Scoring format (default: ppr)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the snapshot and print a summary without uploading to S3",
    )
    parser.add_argument(
        "--output-file",
        type=str,
        help="Also write the snapshot JSON to this local path",
    )
    args = parser.parse_args()

    logger.info(f"Building DraftSharks ADP snapshot for format '{args.format}'...")
    snapshot = build_snapshot(args.format)
    logger.info(f"Built snapshot with {len(snapshot['players'])} players (scraped_at={snapshot['scraped_at']})")

    if args.output_file:
        Path(args.output_file).write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        logger.info(f"Wrote snapshot to {args.output_file}")

    if args.dry_run:
        sample = snapshot["players"][:5]
        logger.info(f"Dry run — sample entries: {sample}")
        return 0

    upload_snapshot(snapshot, args.format)
    return 0


if __name__ == "__main__":
    sys.exit(main())
