"""Run the API locally AND keep the in-season data fresh in the background.

This is the local-dev stand-in for the production setup, where the Airflow DAG
(airflow/dags/in_season_pipeline.py) owns data freshness. It is NOT used in the
deployed container, which only ships src/ and data/.

What it does:
  * starts the FastAPI app (same as scripts/run_api.py), and
  * every ``--interval-min`` minutes, refreshes the stored Sleeper player list
    once it is over a day old (so rookies and signings get names and teams
    instead of "UNKNOWN"), then brings the current week's data up to date
    for each scoring format: re-pulls nflverse data when finished games are
    missing, rebuilds the dbt marts if that changed anything, fetches fresh
    Vegas lines (best-effort), and regenerates projections. Anything already
    current is skipped, so most cycles are a no-op. See
    scripts/recommend.py::ensure_data_current for the exact rules.

The frontend polls ``GET /api/v1/in-season/{league_id}/status`` and reloads the
lineup when the projection/odds timestamps change, so a refresh here shows up in
an open browser tab without a manual reload.

Usage:
    python scripts/dev_server.py
    python scripts/dev_server.py --interval-min 15 --formats ppr,half_ppr
    python scripts/dev_server.py --no-refresh        # same as run_api.py
Then, in another terminal:  cd frontend && npm run dev   (http://localhost:3000)
"""

import argparse
import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

# Project root on sys.path and as CWD, exactly like run_api.py, before src imports.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

import uvicorn  # noqa: E402

logger = logging.getLogger("dev_server")

DEFAULT_FORMATS = ("ppr", "half_ppr", "standard")
DEFAULT_INTERVAL_MIN = 30.0


PLAYER_UNIVERSE_MAX_AGE_HOURS = 24.0


def refresh_players_if_stale(max_age_hours: float = PLAYER_UNIVERSE_MAX_AGE_HOURS) -> bool:
    """Re-download Sleeper's player list when the stored copy is old. True if refreshed.

    The in-season endpoints read the stored copy (data/players/nfl_players.json)
    to name players and look up their team. Without refreshing it, anyone added
    since the file was written (rookies, signings, trades) shows up as
    "UNKNOWN" with no projection. The running API notices the new file by its
    modification time, so no restart is needed.
    """
    from src.api.storage import player_universe_age_hours, save_player_universe
    from src.data_sources.sleeper_client import SleeperClient

    age = player_universe_age_hours()
    if age is not None and age < max_age_hours:
        return False

    players = SleeperClient().get_players(force_refresh=True)
    if not players:
        logger.warning("Could not download the Sleeper player list; keeping the stored copy.")
        return False
    save_player_universe(players)
    logger.info("Refreshed the stored player list (%d players).", len(players))
    return True


def refresh_once(formats) -> bool:
    """One refresh cycle for the current (season, week). True if every format is ready."""
    # Imported lazily: scripts.recommend configures logging and pulls in the
    # projection stack, which the plain API process shouldn't pay for.
    from scripts.recommend import _resolve_current_week, ensure_data_current
    from src.data_sources.sleeper_client import SleeperClient

    try:
        refresh_players_if_stale()
    except Exception:  # an old player list is better than no refresh at all
        logger.exception("Player list refresh failed; continuing.")

    season, week = _resolve_current_week(SleeperClient(), str(datetime.now().year))
    logger.info("Refresh cycle: season=%d week=%d formats=%s", season, week, ",".join(formats))

    all_ok = True
    for scoring_format in formats:
        # Stages that are already current (raw data, marts, odds) skip themselves
        # after the first format; only a missing/stale projection is rebuilt.
        if not ensure_data_current(season, week, scoring_format):
            logger.warning("Refresh for %s did not complete; will retry next cycle.", scoring_format)
            all_ok = False
    return all_ok


def refresh_loop(formats, interval_s: float, stop: threading.Event) -> None:
    """Refresh immediately, then every ``interval_s`` seconds, until ``stop`` is set."""
    while not stop.is_set():
        try:
            refresh_once(formats)
        except Exception:  # a bad cycle (network, dbt) must never kill the loop
            logger.exception("Refresh cycle failed; will retry next cycle.")
        stop.wait(interval_s)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the API with automatic local data refresh.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument(
        "--interval-min", type=float, default=DEFAULT_INTERVAL_MIN,
        help=f"Minutes between refresh cycles (default {DEFAULT_INTERVAL_MIN:g}).",
    )
    parser.add_argument(
        "--formats", default=",".join(DEFAULT_FORMATS),
        help="Comma-separated scoring formats to keep projected (default: ppr,half_ppr,standard).",
    )
    parser.add_argument("--no-refresh", action="store_true", help="Serve the API only.")
    args = parser.parse_args()

    formats = tuple(f.strip() for f in args.formats.split(",") if f.strip())
    if not formats:
        parser.error("--formats must list at least one scoring format.")

    if not args.no_refresh:
        threading.Thread(
            target=refresh_loop,
            args=(formats, args.interval_min * 60.0, threading.Event()),
            name="data-refresh",
            daemon=True,
        ).start()
        logger.info("Background data refresh every %g min.", args.interval_min)

    # Watch only src/ for reloads: the refresher writes parquet/duckdb/dbt files
    # under data/ and dbt/ that must not restart the server.
    uvicorn.run(
        "src.api.main:app", host="0.0.0.0", port=args.port,
        reload=True, reload_dirs=[str(project_root / "src")],
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.exit(main())
