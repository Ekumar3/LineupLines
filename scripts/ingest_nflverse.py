"""Ingest nflverse data into parquet for the dbt transformation pipeline.

Pulls play-by-play, player stats, snap counts, and schedules via nflreadpy and
writes one parquet file per (source, season) to data/raw/. The dbt staging
models read these files via DuckDB's read_parquet().

This is the ingestion step of the in-season pipeline. The Airflow DAG
(Task 13) calls this script, then runs `dbt run` to transform the raw data
into staging → intermediate → marts.

Usage:
    python scripts/ingest_nflverse.py 2024 2025          # specific seasons
    python scripts/ingest_nflverse.py --all               # all available seasons
    python scripts/ingest_nflverse.py 2025 --force         # overwrite existing

Raw parquet layout (mirrors the research/ caching pattern but generalized):
    data/raw/pbp_2024.parquet
    data/raw/player_stats_2024.parquet
    data/raw/snap_counts_2024.parquet
    data/raw/schedules_2024.parquet

The pbp parquet selects only the ~35 columns needed for OL/DL metrics (the
full 372-column schema is ~100MB+/season; columnar parquet means unused
columns are cheap at query time, but we skip them at ingest to keep the
local dev footprint reasonable). The other three sources keep all columns
since they're far smaller.
"""

import argparse
import logging
import sys
from pathlib import Path

import nflreadpy as nfl

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

# Columns selected from the 372-column pbp schema — everything the OL/DL
# metric models (Task 3) and the feature table (Task 9) need.
PBP_COLUMNS = [
    "play_id", "game_id", "old_game_id",
    "season", "week", "season_type", "game_date",
    "home_team", "away_team", "posteam", "defteam", "posteam_type",
    "play_type", "yards_gained", "down", "ydstogo", "yardline_100",
    "qtr", "quarter_seconds_remaining", "game_seconds_remaining",
    "sack", "qb_hit", "qb_scramble", "pass_attempt", "rush_attempt",
    "complete_pass", "incomplete_pass", "interception",
    "air_yards", "yards_after_catch",
    "passing_yards", "rushing_yards", "receiving_yards",
    "epa", "success",
    "run_location", "run_gap",
    "passer_player_id", "receiver_player_id", "rusher_player_id",
    "penalty", "penalty_team",
]

# (nflreadpy function, output filename prefix) for the non-pbp sources.
SOURCES = [
    (nfl.load_player_stats, "player_stats"),
    (nfl.load_snap_counts, "snap_counts"),
    (nfl.load_schedules, "schedules"),
]


def ingest_season(season: int, force: bool = False) -> list[Path]:
    """Ingest all nflverse sources for one season into parquet files.

    Returns the list of files written (or skipped if already present and
    force=False).
    """
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # --- pbp (column-selected) ---
    pbp_path = RAW_DATA_DIR / f"pbp_{season}.parquet"
    if pbp_path.exists() and not force:
        logger.info("pbp_%d.parquet exists, skipping (use --force to overwrite)", season)
    else:
        logger.info("Loading play-by-play for season %d ...", season)
        df = nfl.load_pbp([season])
        available = [c for c in PBP_COLUMNS if c in df.columns]
        missing = set(PBP_COLUMNS) - set(available)
        if missing:
            logger.warning("pbp columns not found in season %d: %s", season, missing)
        df.select(available).write_parquet(pbp_path)
        logger.info("  Wrote %s (%d rows, %d cols)", pbp_path.name, df.height, len(available))
        written.append(pbp_path)

    # --- other sources (all columns) ---
    for loader, prefix in SOURCES:
        path = RAW_DATA_DIR / f"{prefix}_{season}.parquet"
        if path.exists() and not force:
            logger.info("%s_%d.parquet exists, skipping", prefix, season)
            continue
        logger.info("Loading %s for season %d ...", prefix, season)
        df = loader([season])
        df.write_parquet(path)
        logger.info("  Wrote %s (%d rows, %d cols)", path.name, df.height, len(df.columns))
        written.append(path)

    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest nflverse data into parquet for the dbt pipeline.")
    parser.add_argument("seasons", nargs="*", type=int, help="Season years to ingest (e.g. 2024 2025).")
    parser.add_argument("--all", action="store_true", help="Ingest all available seasons (since 1999).")
    parser.add_argument("--force", action="store_true", help="Overwrite existing parquet files.")
    args = parser.parse_args()

    if args.all:
        seasons = list(range(1999, 2026))
    elif args.seasons:
        seasons = args.seasons
    else:
        parser.error("Provide season years or use --all.")

    total_written = 0
    for season in seasons:
        written = ingest_season(season, force=args.force)
        total_written += len(written)
    logger.info("Done. %d files written across %d seasons.", total_written, len(seasons))


if __name__ == "__main__":
    sys.exit(main())
