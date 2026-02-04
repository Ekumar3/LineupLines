"""Manual testing script for draft API endpoints.

Usage:
    python scripts/test_draft_api.py <user_id>
    python scripts/test_draft_api.py 123456789 --active-only
    python scripts/test_draft_api.py 123456789 --base-url http://localhost:8000
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


def test_get_all_drafts(base_url: str, user_id: str):
    """Test fetching all drafts."""
    print(f"\n{'='*70}")
    print(f"Testing: GET /api/v1/users/{user_id}/drafts")
    print(f"{'='*70}")

    try:
        import requests

        response = requests.get(f"{base_url}/api/v1/users/{user_id}/drafts", timeout=10)

        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"\nUser ID: {data['user_id']}")
            print(f"Total Drafts: {data['total_drafts']}")
            print(f"Active Drafts: {data['active_drafts']}")
            print(f"Sport: {data['sport']}")
            print(f"Season: {data['season']}")

            print(f"\nDrafts ({len(data['drafts'])} total):")

            for i, draft in enumerate(data["drafts"], 1):
                metadata = draft.get("metadata", {})
                settings = draft.get("settings", {})
                print(f"\n  [{i}] {metadata.get('name', 'Unnamed Draft')}")
                print(
                    f"      Draft ID: {draft['draft_id']}"
                )
                print(f"      Status: {draft['status']}")
                print(
                    f"      League ID: {draft['league_id']}"
                )
                print(
                    f"      Format: {settings.get('type', 'unknown')} - {settings.get('teams', '?')} teams, {settings.get('rounds', '?')} rounds"
                )
                print(
                    f"      Scoring: {metadata.get('scoring_type', 'unknown')}"
                )
                if draft.get("start_time"):
                    from datetime import datetime

                    start = datetime.fromtimestamp(
                        draft["start_time"] / 1000
                    )
                    print(f"      Start Time: {start}")

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


def test_get_active_drafts(base_url: str, user_id: str):
    """Test fetching active drafts only."""
    print(f"\n{'='*70}")
    print(f"Testing: GET /api/v1/users/{user_id}/drafts/active")
    print(f"{'='*70}")

    try:
        import requests

        response = requests.get(
            f"{base_url}/api/v1/users/{user_id}/drafts/active", timeout=10
        )

        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"\nActive Drafts: {len(data['drafts'])}")

            if data["drafts"]:
                for i, draft in enumerate(data["drafts"], 1):
                    metadata = draft.get("metadata", {})
                    print(
                        f"\n  [{i}] {metadata.get('name', 'Unnamed Draft')} (ID: {draft['draft_id']})"
                    )
                    print(f"      Status: {draft['status']}")
                    print(
                        f"      Scoring: {metadata.get('scoring_type', 'unknown')}"
                    )
            else:
                print("\nNo active drafts found.")

            return 0
        else:
            print(f"Error: {response.json()}")
            return 1

    except requests.exceptions.ConnectionError:
        print(f"[ERROR] Failed to connect to {base_url}")
        return 1
    except Exception as e:
        print(f"[ERROR] {e}")
        return 1


def test_health(base_url: str):
    """Test health check endpoint."""
    try:
        import requests

        response = requests.get(f"{base_url}/health", timeout=5)

        if response.status_code == 200:
            data = response.json()
            print(f"[OK] API is healthy: {data}")
            return True
        else:
            print(f"[ERROR] API unhealthy: {response.status_code}")
            return False

    except Exception as e:
        print(f"[ERROR] Health check failed: {e}")
        return False


def main():
    """Test draft API endpoints."""
    parser = argparse.ArgumentParser(
        description="Test draft API endpoints manually"
    )
    parser.add_argument("username", help="Sleeper user ID")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--active-only",
        action="store_true",
        help="Only test active drafts endpoint",
    )
    parser.add_argument(
        "--skip-health",
        action="store_true",
        help="Skip health check",
    )

    args = parser.parse_args()

    print(f"Testing Draft API at {args.base_url}")
    print(f"User Name: {args.username}")

    # Test health check first (unless skipped)
    if not args.skip_health:
        print("\nChecking API health...")
        if not test_health(args.base_url):
            print("\nAPI server is not accessible. Start it with:")
            print("  uvicorn src.api.main:app --reload")
            return 1

    # Test endpoints
    if args.active_only:
        return test_get_active_drafts(args.base_url, args.user_id)
    else:
        result1 = test_get_all_drafts(args.base_url, args.user_id)
        print()
        result2 = test_get_active_drafts(args.base_url, args.user_id)
        return max(result1, result2)


if __name__ == "__main__":
    sys.exit(main())
