"""Manual testing script for available players API endpoint.

Usage:
    python scripts/test_available_players.py <draft_id>
    python scripts/test_available_players.py <draft_id> --position RB
    python scripts/test_available_players.py <draft_id> --base-url http://localhost:8000
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


def test_available_players(base_url: str, draft_id: str, position: str = None):
    """Test fetching available players."""
    print(f"\n{'='*70}")
    print(f"Testing: GET /api/v1/drafts/{draft_id}/available-players")
    print(f"{'='*70}")

    try:
        import requests

        url = f"{base_url}/api/v1/drafts/{draft_id}/available-players"
        params = {}
        if position:
            params["position"] = position
            print(f"Position filter: {position}")

        response = requests.get(url, params=params, timeout=10)

        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"\nDraft ID: {data['draft_id']}")
            print(f"Total available: {data['total_available']}")
            print(f"Position filter: {data.get('position_filter') or 'None'}")
            print(f"Returned: {len(data['players'])} players")

            print(f"\nTop 10 available players:")
            print(f"{'#':>3} {'Player Name':25s} {'Pos':>3} {'Team':>4} {'Age':>4} {'Exp':>3}")
            print(f"{'-'*3} {'-'*25} {'-'*3} {'-'*4} {'-'*4} {'-'*3}")

            for i, player in enumerate(data["players"][:10], 1):
                age = player.get('age') or '-'
                exp = player.get('years_exp') or '-'
                print(
                    f"{i:3d} {player['name'][:25]:25s} {player['position']:>3} "
                    f"{player['team']:>4} {str(age):>4} {str(exp):>3}"
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
    """Test available players endpoint."""
    parser = argparse.ArgumentParser(
        description="Test available players API endpoint manually"
    )
    parser.add_argument("draft_id", help="Sleeper draft ID")
    parser.add_argument(
        "--position",
        help="Position filter (e.g., RB, WR, QB, TE)",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)",
    )

    args = parser.parse_args()

    print(f"Testing Available Players API at {args.base_url}")
    print(f"Draft ID: {args.draft_id}")

    return test_available_players(args.base_url, args.draft_id, args.position)


if __name__ == "__main__":
    sys.exit(main())
