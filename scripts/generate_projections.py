"""Generate projections for one (season, week) via ProjectionService.

This is the manual, local-testing equivalent of the Airflow DAG's
``generate_projections`` task (see ``airflow/dags/in_season_pipeline.py``). It
wraps ``ProjectionService`` so you don't have to paste a long ``python -c``
one-liner: read the dbt feature mart, project every modeled player for the
target week, and write the projection parquet via ``projections_store``.

No AWS is needed in dev mode. By default output lands in the repo-local
``data/projections/`` directory. Set ``MART_S3_BUCKET`` to run against S3
instead (prod path) — ``projections_store`` decides where to read/write based
solely on whether that variable is set.

This step reads the dbt feature mart (``mart_player_week_features``) and the
defense factor input mart (``int_defense_factor_inputs``). Build them first
from the ``dbt/`` directory with:

    dbt build --profiles-dir . --target dev

Usage:
    python scripts/generate_projections.py 2025 8
    python scripts/generate_projections.py 2025 8 --scoring half_ppr
    python scripts/generate_projections.py --list-formats
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path so 'src' and 'research' are importable,
# and set CWD to it so relative data/ paths resolve — exactly like run_api.py.
# This MUST happen before importing any src.* or research.* modules.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

SCORING_CHOICES = ["ppr", "half_ppr", "standard"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the projection parquet for one (season, week) — the manual "
            "equivalent of the in-season DAG's generate_projections task."
        )
    )
    parser.add_argument("season", nargs="?", type=int, help="Season year (e.g. 2025).")
    parser.add_argument("week", nargs="?", type=int, help="Week number (e.g. 8).")
    parser.add_argument(
        "--scoring",
        choices=SCORING_CHOICES,
        default="ppr",
        help="Scoring format preset to score projections with (default: ppr).",
    )
    parser.add_argument(
        "--list-formats",
        action="store_true",
        help="Print the available scoring format labels and exit.",
    )
    args = parser.parse_args()

    if args.list_formats:
        print("Available scoring formats:")
        for label in SCORING_CHOICES:
            print(f"  {label}")
        return 0

    if args.season is None or args.week is None:
        parser.error("season and week are required (e.g. 2025 8). Use --list-formats to list scoring formats.")

    # Resolve scoring multipliers from the shared preset table — never hardcode.
    from research.scoring import get_scoring_settings

    scoring_settings = get_scoring_settings(args.scoring)

    from src.services.projection_service import ProjectionService

    service = ProjectionService()

    # load_marts raises a clear RuntimeError when projections_store/polars is
    # unavailable; translate it into an actionable message rather than a stack.
    try:
        service.load_marts(args.season)
    except RuntimeError as exc:
        logger.error("Could not load marts: %s", exc)
        logger.error(
            "Install the projection stack (polars, duckdb, dbt-duckdb) and ensure "
            "src/data_sources/projections_store.py is present, then retry."
        )
        return 1

    projections = service.project_week(args.season, args.week, scoring_settings)

    if not projections:
        logger.error(
            "No projections produced for season=%d week=%d (scoring=%s).",
            args.season,
            args.week,
            args.scoring,
        )
        logger.error(
            "The feature mart is likely not built or has no players for this week. "
            "Build the marts first from the dbt/ directory:"
        )
        logger.error("    dbt build --profiles-dir . --target dev")
        return 1

    service.write_output(projections, args.season, args.week, args.scoring)

    destination = (
        f"s3://{os.environ['MART_S3_BUCKET']}/projections/"
        if os.environ.get("MART_S3_BUCKET", "").strip()
        else "data/projections/"
    )
    logger.info(
        "Wrote %d projections for season=%d week=%d (scoring=%s) to %s",
        len(projections),
        args.season,
        args.week,
        args.scoring,
        destination,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
