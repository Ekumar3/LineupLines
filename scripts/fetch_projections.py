"""
Download NFL player season projection stats from SportsData.io.

Usage:
    python scripts/fetch_projections.py

Saves:
    data/projections/projections_2025.json
    data/projections/projections_2026.json

API docs: https://sportsdata.io/developers/api-documentation/nfl
"""

import io
import json
import sys
from pathlib import Path

import requests

# Force UTF-8 output on Windows so player names with accents don't crash
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

API_KEY = "b50fd627a6df43fdbfc98da0a9da72ea"
BASE_URL = "https://api.sportsdata.io/v3/nfl/projections/json/PlayerSeasonProjectionStats/{season}"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "projections"

RELEVANT_POSITIONS = {"QB", "RB", "WR", "TE", "K"}


def fetch_season(season: int) -> list:
    url = BASE_URL.format(season=season)
    print(f"Fetching {season} projections from {url} ...")
    resp = requests.get(url, params={"key": API_KEY}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def save(data: list, season: int) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"projections_{season}.json"
    with open(out, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved {len(data)} records -> {out}")
    return out


def summarize(data: list, season: int):
    skill_players = [p for p in data if p.get("Position") in RELEVANT_POSITIONS]
    by_pos: dict[str, list] = {}
    for p in skill_players:
        by_pos.setdefault(p["Position"], []).append(p)

    print(f"\n── {season} Projections Summary ──────────────────────────────")
    print(f"  Total records     : {len(data)}")
    print(f"  Skill positions   : {len(skill_players)}")
    for pos, players in sorted(by_pos.items()):
        print(f"    {pos}: {len(players)} players")

    # Show available fields from the first record
    if data:
        sample = data[0]
        print(f"\n  Sample fields ({len(sample)} total):")
        for key in list(sample.keys())[:30]:
            print(f"    {key}: {sample[key]!r}")
        if len(sample) > 30:
            print(f"    ... (+{len(sample) - 30} more)")

    # Top fantasy scorers — SportsData field is FantasyPointsPPR
    ppr_field = "FantasyPointsPPR"
    scored = [p for p in skill_players if p.get(ppr_field) is not None]
    if scored:
        top = sorted(scored, key=lambda p: p[ppr_field], reverse=True)[:10]
        print(f"\n  Top 10 projected PPR scorers:")
        for i, p in enumerate(top, 1):
            name = p.get("Name") or f"{p.get('FirstName','')} {p.get('LastName','')}".strip()
            pos = p.get("Position", "?")
            team = p.get("Team", "?")
            pts = p[ppr_field]
            print(f"    {i:2}. {name:<22} {pos:<4} {team:<4} {pts:.1f} pts")


def main():
    errors = []
    for season in (2025, 2026):
        try:
            data = fetch_season(season)
            save(data, season)
            summarize(data, season)
        except requests.HTTPError as e:
            print(f"  HTTP error for {season}: {e}", file=sys.stderr)
            errors.append(season)
        except Exception as e:
            print(f"  Unexpected error for {season}: {e}", file=sys.stderr)
            errors.append(season)

    if errors:
        print(f"\nWarning: failed to fetch seasons: {errors}", file=sys.stderr)
        sys.exit(1)
    print("\nDone.")


if __name__ == "__main__":
    main()
