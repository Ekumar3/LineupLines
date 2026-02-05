"""Manual testing script for user roster API endpoint.

Usage:
    python scripts/test_user_roster.py <draft_id> <user_id>
    python scripts/test_user_roster.py <draft_id> <user_id> --base-url http://localhost:8000
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


def test_user_roster(base_url: str, draft_id: str, user_id: str):
    """Test fetching user's roster grouped by position."""
    print(f"\n{'='*70}")
    print(f"Testing: GET /api/v1/drafts/{draft_id}/users/{user_id}/roster")
    print(f"{'='*70}")

    try:
        import requests

        url = f"{base_url}/api/v1/drafts/{draft_id}/users/{user_id}/roster"
        response = requests.get(url, timeout=10)

        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()

            print(f"\nRoster Information:")
            print(f"  Draft ID: {data['draft_id']}")
            print(f"  User ID: {data['user_id']}")
            print(f"  Draft Slot: {data['draft_slot']}")
            print(f"  Total Picks: {data['total_picks']}")

            print(f"\nRoster by Position:")
            for position in ["QB", "RB", "WR", "TE", "K", "DEF"]:
                picks = data['roster_by_position'].get(position, [])
                needs = data['position_summary'][position]

                print(f"\n  {position}:")
                print(f"    Count: {needs['count']}")
                print(f"    Needs More: {needs['needs_more']}")
                print(f"    Priority: {needs['priority']}")

                if picks:
                    for pick in picks:
                        print(
                            f"      - Pick #{pick['pick_no']} (R{pick['round']}): "
                            f"{pick['player_name']} ({pick['position']}, {pick['team']})"
                        )
                else:
                    print(f"      - No {position} drafted yet")

            print(f"\n✅ User roster retrieved successfully!")
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
    """Test user roster endpoint."""
    parser = argparse.ArgumentParser(
        description="Test user roster API endpoint manually"
    )
    parser.add_argument("draft_id", help="Sleeper draft ID")
    parser.add_argument("user_id", help="Sleeper user ID")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)",
    )

    args = parser.parse_args()

    print(f"Testing User Roster API at {args.base_url}")
    print(f"Draft ID: {args.draft_id}")
    print(f"User ID: {args.user_id}")

    return test_user_roster(args.base_url, args.draft_id, args.user_id)


if __name__ == "__main__":
    sys.exit(main())
