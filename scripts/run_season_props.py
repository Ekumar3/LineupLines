#!/usr/bin/env python
"""
Run the season props fetcher locally (for development/testing).
Returns sample data by default (no API key required).
"""

import os
import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.vegas_pipeline.fetchers.opticodds_fetcher import fetch_season_props
from src.vegas_pipeline.handler import _handle_season_props


def main():
    print("=" * 60)
    print("LineupLines — Season Props Fetcher (Local Test)")
    print("=" * 60)

    # Test 1: Fetch season props directly
    print("\n1. Fetching season props from OpticOdds...")
    try:
        props = fetch_season_props(sport="nfl", season="2026")
        print(f"   [OK] Fetched {len(props['props'])} player props")
        print(f"   Data source: {props['data_source']}")
        print(f"   Fetched at: {props['fetched_at']}")
    except Exception as e:
        print(f"   [ERROR] {e}")
        return 1

    # Test 2: Use handler to store locally
    print("\n2. Testing handler with local storage...")
    try:
        # Ensure we don't use S3
        os.environ.pop("S3_BUCKET", None)
        os.environ.pop("OPTICODDS_API_KEY", None)

        result = _handle_season_props(sport="nfl", season="2026")
        print(f"   [OK] Handler result: {result['status']}")
        if "path" in result:
            print(f"   Stored at: {result['path']}")
            # Verify file was created and has data
            with open(result['path'], 'r') as f:
                data = json.load(f)
                print(f"   File contains {len(data.get('props', []))} props")
    except Exception as e:
        print(f"   [ERROR] {e}")
        return 1

    # Test 3: Display sample props
    print("\n3. Sample player props (first 3):")
    for i, prop in enumerate(props['props'][:3]):
        print(f"\n   [{i+1}] {prop['player_name']} ({prop['team']}) - {prop['position']}")
        print(f"       {prop['stat_category'].upper()}")
        print(f"       Line: {prop['line']}")
        print(f"       Over: {prop['over_odds']} | Under: {prop['under_odds']}")
        print(f"       Book: {prop['sportsbook']}")

    print("\n" + "=" * 60)
    print("[OK] All local tests passed!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
