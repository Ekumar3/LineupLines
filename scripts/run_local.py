"""Run fetcher locally and save to ./data/latest.json"""
import argparse
import json
from src.vegas_pipeline.fetchers.the_odds_api import fetch_odds


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", default="americanfootball_nfl")
    args = parser.parse_args()

    results = fetch_odds(sport=args.sport)
    payload = {"sport": args.sport, "results": results}

    with open("data/latest.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, default=str, indent=2)

    print("Saved data/latest.json")


if __name__ == "__main__":
    main()
