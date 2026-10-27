"""Fetch in-season start/sit recommendations from the LOCAL running API.

This is a convenience client so you don't have to hand-run several curls. It
resolves a Sleeper username (or raw user_id) to a roster, picks a league, then
calls the local LineupLines API's in-season recommendations endpoint and prints
a clean start/sit table.

Username -> user_id resolution and league listing go straight through
``SleeperClient`` (Sleeper's public API), so they work without the local API
running. Only the recommendations call needs the local API up.

Prerequisites:
  * The API must already be running locally:  python scripts/run_api.py
  * Projections for the resolved week must already be generated:
        python scripts/generate_projections.py <season> <week>

Usage:
    python scripts/recommend.py --username YOUR_SLEEPER_NAME
    python scripts/recommend.py --username YOUR_SLEEPER_NAME --league-id 123456789
    python scripts/recommend.py --user-id 987654321 --league-id 123456789
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path so 'src' is importable, and set CWD to
# it so relative data/ paths resolve — exactly like run_api.py. This MUST happen
# before importing any src.* modules.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

import requests  # noqa: E402  (import after sys.path/CWD setup)

from src.data_sources.sleeper_client import SleeperClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# recommendation values that count as "starting"; everything else is a SIT variant.
_START_REC = "START"


def _resolve_user_id(args: argparse.Namespace, client: SleeperClient) -> str | None:
    """Resolve the user_id from --username or --user-id (exactly one required)."""
    if args.user_id:
        return str(args.user_id)

    user = client.get_user(args.username)
    if not user or not user.get("user_id"):
        logger.error("Could not resolve Sleeper username %r to a user_id.", args.username)
        return None
    return str(user["user_id"])


def _resolve_league_id(args: argparse.Namespace, client: SleeperClient, user_id: str) -> str | None:
    """Resolve the league_id, listing/prompting when --league-id is omitted."""
    if args.league_id:
        return str(args.league_id)

    leagues = client.get_user_leagues(user_id, "nfl", args.season)
    if not leagues:
        logger.error(
            "No NFL leagues found for user_id=%s in season %s. "
            "Pass --league-id explicitly or check the --season.",
            user_id,
            args.season,
        )
        return None

    if len(leagues) == 1:
        league = leagues[0]
        league_id = str(league.get("league_id"))
        logger.info("Using your only %s league: %s (%s)", args.season, league.get("name"), league_id)
        return league_id

    print(f"\nFound {len(leagues)} NFL leagues for season {args.season}:")
    for i, league in enumerate(leagues):
        print(f"  [{i}] {league.get('name')} ({league.get('league_id')})")

    while True:
        raw = input("\nPick a league by index: ").strip()
        try:
            idx = int(raw)
        except ValueError:
            print("Please enter a number.")
            continue
        if 0 <= idx < len(leagues):
            return str(leagues[idx].get("league_id"))
        print(f"Index out of range (0-{len(leagues) - 1}).")


def _fetch_recommendations(base_url: str, league_id: str, user_id: str) -> dict | None:
    """Call the local API's recommendations endpoint; return parsed JSON or None on error."""
    url = f"{base_url.rstrip('/')}/api/v1/in-season/{league_id}/{user_id}/recommendations"
    logger.info("Fetching recommendations from %s", url)

    try:
        response = requests.get(url, timeout=30)
    except requests.exceptions.ConnectionError:
        logger.error(
            "Could not connect to the API at %s. Is it running? "
            "Start it with:  python scripts/run_api.py",
            base_url,
        )
        return None

    if response.status_code == 200:
        return response.json()

    detail = _response_detail(response)

    if response.status_code == 503:
        logger.error(
            "Projections aren't generated yet for the resolved week. "
            "Generate them first with:  python scripts/generate_projections.py <season> <week>"
        )
        if detail:
            logger.error("API said: %s", detail)
        return None

    if response.status_code == 404:
        logger.error(
            "League or user not found (bad league_id/user_id, or the user isn't in that league)."
        )
        if detail:
            logger.error("API said: %s", detail)
        return None

    logger.error("Request failed with HTTP %d: %s", response.status_code, detail or response.text)
    return None


def _response_detail(response: requests.Response) -> str | None:
    """Best-effort extraction of a FastAPI 'detail' message from a response body."""
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return str(detail)
    return None


def _sort_key_start(rec: dict) -> tuple:
    """Sort STARTers by slot label, then projected points descending."""
    slot = rec.get("slot") or ""
    proj = rec.get("projected_points")
    proj = proj if isinstance(proj, (int, float)) else float("-inf")
    return (slot, -proj)


def _sort_key_sit(rec: dict) -> tuple:
    """Sort SIT variants by projected points descending."""
    proj = rec.get("projected_points")
    proj = proj if isinstance(proj, (int, float)) else float("-inf")
    return (-proj,)


def _format_proj(value) -> str:
    return f"{value:.1f}" if isinstance(value, (int, float)) else "-"


def _print_table(data: dict) -> None:
    """Print the header block and the sorted start/sit table."""
    print()
    print("=" * 60)
    print(f"League:          {data.get('league_id')}")
    print(f"User:            {data.get('user_id')}")
    print(f"Season / Week:   {data.get('season')} / week {data.get('week')}")
    print(f"Scoring format:  {data.get('scoring_format')}")
    print(f"Optimal lineup:  {data.get('optimal_lineup_set')}")
    print("=" * 60)

    recommendations = data.get("recommendations") or []
    if not recommendations:
        print("\nNo recommendations — this roster is empty or has no projectable players.\n")
        return

    starters = sorted(
        (r for r in recommendations if r.get("recommendation") == _START_REC),
        key=_sort_key_start,
    )
    sitters = sorted(
        (r for r in recommendations if r.get("recommendation") != _START_REC),
        key=_sort_key_sit,
    )
    ordered = starters + sitters

    headers = ["SLOT", "REC", "POS", "PLAYER", "TEAM", "OPP", "PROJ", "MATCHUP"]
    rows = []
    for rec in ordered:
        grade = rec.get("matchup_grade") or {}
        rows.append(
            [
                str(rec.get("slot") or "-"),
                str(rec.get("recommendation") or "-"),
                str(rec.get("position") or "-"),
                str(rec.get("player_name") or "-"),
                str(rec.get("team") or "-"),
                str(grade.get("opponent") or "-"),
                _format_proj(rec.get("projected_points")),
                str(grade.get("overall_signal") or "-"),
            ]
        )

    # Column widths: max of header and all cell lengths.
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    # PROJ is numeric -> right-justify; everything else left-justify.
    right_justify = {headers.index("PROJ")}

    def render(cells: list) -> str:
        parts = []
        for i, cell in enumerate(cells):
            parts.append(cell.rjust(widths[i]) if i in right_justify else cell.ljust(widths[i]))
        return "  ".join(parts).rstrip()

    print()
    print(render(headers))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(render(row))
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch in-season start/sit recommendations from the LOCAL running API "
            "and print a clean table."
        )
    )
    parser.add_argument("--username", help="Sleeper username to resolve into a user_id.")
    parser.add_argument("--user-id", dest="user_id", help="Sleeper user_id to use directly.")
    parser.add_argument(
        "--league-id",
        dest="league_id",
        help="League to query. If omitted, your NFL leagues for --season are listed.",
    )
    parser.add_argument(
        "--season",
        default="2026",
        help="Season used only for listing leagues when --league-id is omitted (default: 2026).",
    )
    parser.add_argument(
        "--base-url",
        dest="base_url",
        default="http://localhost:8000",
        help="Base URL of the local API (default: http://localhost:8000).",
    )
    args = parser.parse_args()

    if bool(args.username) == bool(args.user_id):
        parser.error("Provide exactly one of --username or --user-id.")

    client = SleeperClient()

    user_id = _resolve_user_id(args, client)
    if user_id is None:
        return 1

    league_id = _resolve_league_id(args, client, user_id)
    if league_id is None:
        return 1

    data = _fetch_recommendations(args.base_url, league_id, user_id)
    if data is None:
        return 1

    _print_table(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
