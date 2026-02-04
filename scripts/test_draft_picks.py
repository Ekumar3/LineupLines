"""Manual testing script for draft picks API endpoint.

Usage:
    python scripts/test_draft_picks.py <draft_id>
    python scripts/test_draft_picks.py <draft_id> --base-url http://localhost:8000
"""

import sys
import logging
import argparse
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def test_get_picks(base_url: str, draft_id: str):
    """Test fetching draft picks."""
    print(f"\n{'='*70}")
    print(f"Testing: GET /api/v1/drafts/{draft_id}/picks")
    print(f"{'='*70}")

    try:
        import requests

        response = requests.get(f"{base_url}/api/v1/drafts/{draft_id}/picks", timeout=10)

        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"\nDraft ID: {data['draft_id']}")
            print(f"Total Picks: {data['total_picks']}")

            print(f"\nPicks ({len(data['picks'])} total):")
            print(f"{'Pick':>6} {'Rnd':>4} {'Player':25s} {'Pos':>3} {'Team':>4}")
            print(f"{'-'*6} {'-'*4} {'-'*25} {'-'*3} {'-'*4}")

            for pick in data["picks"]:
                print(
                    f"{pick['pick_no']:6d} {pick['round']:4d} "
                    f"{pick['player_name'][:25]:25s} {pick['position']:>3} {pick['team']:>4}"
                )

            return 0
        else:
            print(f"Error: {response.json()}")
            return 1

    except requests.exceptions.ConnectionError:
        print(f"[ERROR] Failed to connect to {base_url}")
        print("Is the API server running? Try:")
        print(f"  uvicorn src.api.main:app --reload")
        return 1
    except Exception as e:
        print(f"[ERROR] {e}")
        return 1


def main():
    """Test draft picks endpoint."""
    parser = argparse.ArgumentParser(
        description="Test draft picks API endpoint manually"
    )
    parser.add_argument("draft_id", help="Sleeper draft ID")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)",
    )

    args = parser.parse_args()

    print(f"Testing Draft Picks API at {args.base_url}")
    print(f"Draft ID: {args.draft_id}")

    return test_get_picks(args.base_url, args.draft_id)


if __name__ == "__main__":
    sys.exit(main())
