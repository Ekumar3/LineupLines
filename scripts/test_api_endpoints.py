#!/usr/bin/env python
"""
Test season props API endpoints after running the server.
Run this after: python scripts/run_api.py
"""

import requests
import json
import sys

BASE_URL = "http://localhost:8000"
TIMEOUT = 5


def test_endpoint(method: str, path: str, expected_status: int = 200):
    """Test an API endpoint."""
    url = f"{BASE_URL}{path}"
    print(f"\n{method} {path}")
    print(f"  URL: {url}")

    try:
        if method == "GET":
            resp = requests.get(url, timeout=TIMEOUT)
        else:
            raise ValueError(f"Unsupported method: {method}")

        print(f"  Status: {resp.status_code}")

        if resp.status_code == expected_status:
            print(f"  [OK] Got expected status {expected_status}")
        else:
            print(f"  [ERROR] Expected {expected_status}, got {resp.status_code}")
            return False

        # Try to parse JSON
        try:
            data = resp.json()
            if isinstance(data, dict) and "props" in data:
                print(f"  Props returned: {len(data.get('props', []))}")
            elif isinstance(data, dict) and "props" in data:
                print(f"  Items returned: {len(data.get('props', []))}")
            elif isinstance(data, dict) and "count" in data:
                print(f"  Count: {data.get('count')}")
            print(f"  [OK] Valid JSON response")
            return True
        except json.JSONDecodeError:
            print(f"  [ERROR] Invalid JSON response")
            return False

    except requests.exceptions.ConnectionError:
        print(f"  [ERROR] Could not connect to {BASE_URL}")
        print(f"  Make sure the API server is running: python scripts/run_api.py")
        return False
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False


def main():
    print("=" * 60)
    print("LineupLines API Endpoint Tests")
    print("=" * 60)

    # Test health check
    print("\nPart 1: Health & Game Odds Endpoints")
    test_endpoint("GET", "/health")

    # Test game odds endpoint (should work from existing data)
    test_endpoint("GET", "/lines/latest", expected_status=200)

    # Test season props endpoints
    print("\nPart 2: Season Props Endpoints")
    test_endpoint("GET", "/props/season/latest")
    test_endpoint("GET", "/props/season/player/Patrick%20Mahomes")
    test_endpoint("GET", "/props/season/category/passing_yards")

    # Test with custom season
    print("\nPart 3: Custom Season/Sport Parameters")
    test_endpoint("GET", "/props/season/latest?sport=nfl&season=2026")
    test_endpoint("GET", "/props/season/category/rushing_yards?sport=nfl&season=2026")

    # Test invalid player (should 404)
    print("\nPart 4: Error Handling")
    test_endpoint("GET", "/props/season/player/NonExistentPlayer", expected_status=404)
    test_endpoint("GET", "/props/season/category/invalid_category", expected_status=404)

    print("\n" + "=" * 60)
    print("Endpoint tests complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
