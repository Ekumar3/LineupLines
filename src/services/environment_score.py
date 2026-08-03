"""Environment score loader — team-level scoring-environment data used to break
ties within a player's tier.

Unlike the ADP snapshots in adp_sources.py, this is a manually-uploaded CSV
(pulled from DraftSharks/Vegas lines, not scraped in-house) at a fixed S3 key
with no scraped_at timestamp, so there is deliberately no staleness check.
Lives in the same bucket as the ADP snapshots (ADP_S3_BUCKET), just a
different key:

    s3://{ADP_S3_BUCKET}/environment_score.csv

    rank,team,implied_ppg,avg_game_total,shootout_rate,low_total_rate,score
    1,Dallas Cowboys,25.74,50.32,88.2%,0.0%,3.12
    ...

The CSV keys teams by full name; every other player/team field in this
codebase (Sleeper, DraftSharks) uses 2-3 letter abbreviations, so this module
also owns the full-name -> abbreviation mapping needed to join the two.
"""

import csv
import io
import logging
import os
from typing import Dict

logger = logging.getLogger(__name__)

try:
    import boto3
except Exception:
    boto3 = None

TEAM_FULL_NAME_TO_ABBR = {
    "Arizona Cardinals": "ARI",
    "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR",
    "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN",
    "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN",
    "Detroit Lions": "DET",
    "Green Bay Packers": "GB",
    "Houston Texans": "HOU",
    "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV",
    "Oakland Raiders": "LV",
    "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR",
    "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN",
    "New England Patriots": "NE",
    "New Orleans Saints": "NO",
    "New York Giants": "NYG",
    "New York Jets": "NYJ",
    "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA",
    "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN",
    "Washington Commanders": "WAS",
}


def get_environment_map() -> Dict[str, Dict[str, float]]:
    """Load the environment score CSV from S3, keyed by team abbreviation.

    Returns {team_abbr: {"rank": int, "score": float}}. Returns {} whenever
    the bucket isn't configured or the object can't be read/parsed — callers
    should treat environment data as optional and degrade gracefully.
    """
    bucket = os.environ.get("ADP_S3_BUCKET")
    if not bucket:
        logger.info("ADP_S3_BUCKET not set, skipping environment score")
        return {}

    if boto3 is None:
        logger.warning("boto3 not available, cannot load environment score CSV")
        return {}

    try:
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=bucket, Key="environment_score.csv")
        reader = csv.DictReader(io.TextIOWrapper(obj["Body"], encoding="utf-8"))

        result: Dict[str, Dict[str, float]] = {}
        for row in reader:
            abbr = TEAM_FULL_NAME_TO_ABBR.get((row.get("team") or "").strip())
            if abbr is None:
                logger.warning("Unmapped team name in environment score CSV: %r", row.get("team"))
                continue
            try:
                result[abbr] = {"rank": int(row["rank"]), "score": float(row["score"])}
            except (KeyError, ValueError) as e:
                logger.warning("Malformed environment score row %r: %s", row, e)
                continue

        return result
    except Exception as e:
        logger.info("Could not load environment score CSV: %s", e)
        return {}
