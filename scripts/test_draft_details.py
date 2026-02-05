"""Manual testing script for draft details API endpoint.

Usage:
    python scripts/test_draft_details.py <draft_id>
    python scripts/test_draft_details.py <draft_id> --base-url http://localhost:8000
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


def test_draft_details(base_url: str, draft_id: str):
    """Test fetching draft details including roster mapping."""
    print(f"\n{'='*70}")
    print(f"Testing: GET /api/v1/drafts/{draft_id}")
    print(f"{'='*70}")

    try:
        import requests

        url = f"{base_url}/api/v1/drafts/{draft_id}"
        response = requests.get(url, timeout=10)

        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()

            print(f"\nDraft Details:")
            print(f"  Draft ID: {data['draft_id']}")
            print(f"  League ID: {data['league_id']}")
            print(f"  Status: {data['status']}")
            print(f"\n  Settings:")
            print(f"    Teams: {data['settings']['teams']}")
            print(f"    Rounds: {data['settings']['rounds']}")
            print(f"    Type: {data['settings']['type']}")

            print(f"\n  Metadata:")
            print(f"    Name: {data['metadata'].get('name') or 'N/A'}")
            print(f"    Scoring: {data['metadata'].get('scoring_type') or 'N/A'}")

            print(f"\n  Draft Order (first 12 slots):")
            for i, user_id in enumerate(data['draft_order'][:12]):
                slot_num = i + 1
                user_display = user_id if user_id else "[UNPICKED]"
                print(f"    Slot {slot_num:2d}: {user_display}")

            print(f"\n  Roster-to-User Mapping:")
            for roster_id, user_id in sorted(data['roster_to_user'].items(), key=lambda x: int(x[0])):
                print(f"    Roster {roster_id}: {user_id}")

            print(f"\n✅ Draft details retrieved successfully!")
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
    """Test draft details endpoint."""
    parser = argparse.ArgumentParser(
        description="Test draft details API endpoint manually"
    )
    parser.add_argument("draft_id", help="Sleeper draft ID")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)",
    )

    args = parser.parse_args()

    print(f"Testing Draft Details API at {args.base_url}")
    print(f"Draft ID: {args.draft_id}")

    return test_draft_details(args.base_url, args.draft_id)


if __name__ == "__main__":
    sys.exit(main())
