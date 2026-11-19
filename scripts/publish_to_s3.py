"""Publish the current week's in-season data to S3 so the hosted API can serve it.

The hosted API container ships only ``src/`` and ``data/`` (no dbt, no DuckDB
file), so in production it reads everything from S3 when ``MART_S3_BUCKET`` is
set (see src/data_sources/projections_store.py). This script builds the
week's data locally, exactly like ``scripts/recommend.py --load-current`` does,
and uploads the pieces the API reads:

    marts/mart_matchup_grade.parquet                  OL/DL grades, opponents, byes
    odds/implied_totals_<season>_wk<NN>.parquet       live Vegas lines (freshness label)
    projections/<season>_wk<NN>_<format>.parquet      one per scoring format

Projections are uploaded LAST. The frontend watches the projection timestamp to
decide when to reload a lineup, so by then the mart and odds it depends on are
already in place.

The target bucket comes from ``--bucket`` or ``PUBLISH_S3_BUCKET``, never from
``MART_S3_BUCKET``: that variable switches the app's own readers to S3, and this
script has to read its inputs from local disk (it is cleared on startup).

Usage:
    python scripts/publish_to_s3.py --bucket lineuplines-player-data-prod --dry-run
    python scripts/publish_to_s3.py --bucket lineuplines-player-data-prod --refresh
    python scripts/publish_to_s3.py --bucket ... --season 2026 --week 11 --formats ppr

``--refresh`` first brings the week's raw data, marts, odds and projections up to
date for every format (the same stages --load-current runs). Without it the
script publishes whatever is already on disk, and stops if that is incomplete.

Needs AWS credentials with write access to the bucket (``aws sso login`` or
environment keys). Uploading overwrites the same keys each run; the bucket has
versioning enabled, so earlier versions are kept.
"""

import argparse
import io
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Project root on sys.path and as CWD, like the other scripts, before src imports.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

# This process must read marts/projections from LOCAL disk. MART_S3_BUCKET would
# flip every store reader to S3, so make sure it is off here.
os.environ.pop("MART_S3_BUCKET", None)

from src.data_sources import projections_store as store  # noqa: E402

logger = logging.getLogger("publish_to_s3")

DEFAULT_FORMATS = ("ppr", "half_ppr", "standard")
# The only mart the hosted API reads (MatchupGradeService). Add names here if
# the API starts reading more.
MARTS = ("mart_matchup_grade",)
# A projection written before the hover-card breakdown existed lacks this column.
BREAKDOWN_COLUMN = "env_multiplier"


@dataclass
class Upload:
    key: str
    body: bytes
    label: str


class PublishError(Exception):
    """Something is missing or inconsistent; nothing has been uploaded."""


def _parquet_bytes(df) -> bytes:
    buffer = io.BytesIO()
    df.write_parquet(buffer)
    return buffer.getvalue()


def build_uploads(season: int, week: int, formats) -> list[Upload]:
    """Read everything to publish from local disk. Raises PublishError if incomplete.

    Ordered marts, odds, projections (see module docstring).
    """
    import polars as pl

    uploads: list[Upload] = []

    for name in MARTS:
        df = store._load_mart_local(name, None)
        if df is None or df.is_empty():
            raise PublishError(
                f"Mart {name} is empty or missing in {store.LOCAL_DUCKDB_PATH}. "
                "Build it with --refresh (or `dbt build` from dbt/)."
            )
        has_week = df.filter((pl.col("season") == season) & (pl.col("week") == week)).height
        if not has_week:
            raise PublishError(
                f"Mart {name} has no rows for season={season} week={week}. "
                "Rebuild it with --refresh."
            )
        uploads.append(Upload(store.mart_s3_key(name), _parquet_bytes(df), f"mart {name} ({df.height} rows)"))

    odds_path = store.LOCAL_ODDS_DIR / f"implied_totals_{season}_wk{week:02d}.parquet"
    if odds_path.exists():
        uploads.append(Upload(store.odds_s3_key(season, week), odds_path.read_bytes(), f"odds week {week}"))
    else:
        logger.warning(
            "No live odds file for week %d; the API will report schedule lines. "
            "(refresh_odds.py or --refresh fetches them before kickoff.)", week,
        )

    for scoring_format in formats:
        path = store.LOCAL_PROJECTIONS_DIR / store._projection_filename(season, week, scoring_format)
        if not path.exists():
            raise PublishError(
                f"Projection {path.name} is missing. Generate it with --refresh or "
                f"`python scripts/generate_projections.py {season} {week} --scoring {scoring_format}`."
            )
        df = pl.read_parquet(path)
        if BREAKDOWN_COLUMN not in df.columns:
            logger.warning(
                "%s predates the hover-card breakdown columns; regenerate it to include them.",
                path.name,
            )
        uploads.append(
            Upload(
                store.projection_s3_key(season, week, scoring_format),
                path.read_bytes(),
                f"projection {scoring_format} ({df.height} players)",
            )
        )

    return uploads


def upload_all(bucket: str, uploads: list[Upload]) -> None:
    """PUT every object, then confirm each landed with the expected size."""
    import boto3

    s3 = boto3.client("s3")
    for u in uploads:
        s3.put_object(Bucket=bucket, Key=u.key, Body=u.body)
        logger.info("uploaded s3://%s/%s  (%s, %.1f KB)", bucket, u.key, u.label, len(u.body) / 1024)

    for u in uploads:
        size = s3.head_object(Bucket=bucket, Key=u.key)["ContentLength"]
        if size != len(u.body):
            raise PublishError(f"Verification failed for {u.key}: expected {len(u.body)} bytes, S3 has {size}.")
    logger.info("verified %d object(s) in s3://%s", len(uploads), bucket)


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish the current week's data to S3 for the hosted API.")
    parser.add_argument("--bucket", default=os.environ.get("PUBLISH_S3_BUCKET"),
                        help="Target S3 bucket (default: $PUBLISH_S3_BUCKET).")
    parser.add_argument("--season", type=int, help="Season (default: current, from Sleeper).")
    parser.add_argument("--week", type=int, help="Week (default: current, from Sleeper).")
    parser.add_argument("--formats", default=",".join(DEFAULT_FORMATS),
                        help="Comma-separated scoring formats (default: ppr,half_ppr,standard).")
    parser.add_argument("--refresh", action="store_true",
                        help="Bring raw data, marts, odds and projections up to date first.")
    parser.add_argument("--dry-run", action="store_true", help="Build and list what would be uploaded; upload nothing.")
    args = parser.parse_args()

    if not args.bucket:
        parser.error("Provide --bucket or set PUBLISH_S3_BUCKET.")
    formats = tuple(f.strip() for f in args.formats.split(",") if f.strip())
    if not formats:
        parser.error("--formats must list at least one scoring format.")

    # Lazy: these pull in the projection stack and configure logging.
    from scripts.recommend import _resolve_current_week, ensure_data_current
    from src.data_sources.sleeper_client import SleeperClient

    season, week = args.season, args.week
    if not (season and week):
        current_season, current_week = _resolve_current_week(SleeperClient(), str(datetime.now().year))
        season, week = season or current_season, week or current_week
    logger.info("Publishing season=%d week=%d formats=%s to s3://%s%s",
                season, week, ",".join(formats), args.bucket, " (dry run)" if args.dry_run else "")

    if args.refresh:
        for scoring_format in formats:
            if not ensure_data_current(season, week, scoring_format):
                logger.error("Refresh failed for %s; nothing was published.", scoring_format)
                return 1

    try:
        uploads = build_uploads(season, week, formats)
    except PublishError as e:
        logger.error("%s", e)
        return 1

    if args.dry_run:
        for u in uploads:
            print(f"would upload s3://{args.bucket}/{u.key}  ({u.label}, {len(u.body) / 1024:.1f} KB)")
        return 0

    try:
        upload_all(args.bucket, uploads)
    except PublishError as e:
        logger.error("%s", e)
        return 1
    except Exception as e:  # botocore errors: credentials, permissions, bucket name
        if "ExpiredToken" in str(e):
            logger.error("Your AWS credentials have expired. Refresh them (e.g. `aws sso login`) and rerun.")
        elif e.__class__.__name__ == "NoCredentialsError":
            logger.error("No AWS credentials found. Run `aws configure` or `aws sso login`.")
        else:
            logger.error("Upload failed: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.exit(main())
