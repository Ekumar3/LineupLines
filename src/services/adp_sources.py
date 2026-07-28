"""ADP source registry — dispatches to whichever ADP provider is requested.

The available-players table can be driven by different ADP providers (Sleeper's
native ADP, or externally scraped sources like FantasyPros). Only one source is
active at a time. Sleeper is computed in-process from data the caller already
fetched; every other source is read from a JSON snapshot in S3 dropped by the
scraping pipeline at s3://{ADP_S3_BUCKET}/adp/{source}/{scoring_format}/latest.json:

    {
      "scraped_at": "2026-07-20T08:00:00Z",
      "source": "fantasypros",
      "scoring_format": "ppr",
      "players": [
        {"name": "josh allen", "position": "QB", "team": "BUF", "adp": 25.0},
        {"name": "josh allen", "position": "LB", "team": "JAX", "adp": 410.0}
      ]
    }

External sources have no shared player_id with Sleeper, so players are joined
by (normalized_name, position) — position is required because name alone isn't
unique (e.g. the real QB Josh Allen and LB Josh Allen both play in the NFL).

Adding a new externally-scraped source (DraftSharks, FantasyPoints, ...) means
adding its name to EXTERNAL_SOURCES below — no endpoint changes required.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple

from src.analytics.adp_service import adp_service

logger = logging.getLogger(__name__)

try:
    import boto3
except Exception:
    boto3 = None

# All externally-scraped sources share the same S3 snapshot format/loader.
EXTERNAL_SOURCES = ("fantasypros",)
ADP_SOURCES = ("sleeper",) + EXTERNAL_SOURCES

STALE_AFTER = timedelta(hours=48)


def _load_sleeper(scoring_format: str, all_players: dict, sleeper_proj: dict) -> Tuple[Dict[str, float], bool]:
    """Reshape already-fetched Sleeper projections into player_id -> adp."""
    return (
        {player_id: proj.adp for player_id, proj in sleeper_proj.items() if proj.adp is not None},
        True,
    )


def _load_external_snapshot(source: str, scoring_format: str, all_players: dict, sleeper_proj: dict) -> Tuple[Dict[str, float], bool]:
    """Load an externally-scraped ADP snapshot from S3 and join it to player_id by name.

    Returns ({}, False) whenever the snapshot is missing, stale (>48h old), or
    can't be read — callers are expected to fall back to Sleeper ADP in that case.
    """
    bucket = os.environ.get("ADP_S3_BUCKET")
    if not bucket:
        logger.warning("ADP_S3_BUCKET not set, cannot load external ADP source %s", source)
        return {}, False

    if boto3 is None:
        logger.warning("boto3 not available, cannot load external ADP source %s", source)
        return {}, False

    key = f"adp/{source}/{scoring_format}/latest.json"
    try:
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=bucket, Key=key)
        snapshot = json.loads(obj["Body"].read())
    except Exception as e:
        logger.info("No ADP snapshot available for %s/%s: %s", source, scoring_format, e)
        return {}, False

    try:
        scraped_at = datetime.fromisoformat(snapshot["scraped_at"].replace("Z", "+00:00"))
        if scraped_at.tzinfo is None:
            scraped_at = scraped_at.replace(tzinfo=timezone.utc)
    except Exception as e:
        logger.warning("Malformed scraped_at in %s/%s snapshot: %s", source, scoring_format, e)
        return {}, False

    age = datetime.now(timezone.utc) - scraped_at
    if age > STALE_AFTER:
        logger.warning(
            "Stale ADP snapshot for %s/%s (age=%s, threshold=%s), falling back",
            source, scoring_format, age, STALE_AFTER,
        )
        return {}, False

    snapshot_players = snapshot.get("players") or []

    # Build (normalized_name, position) -> player_id from the universe so we can
    # join without a shared player_id. Position is required to disambiguate
    # same-named players at different positions (e.g. Josh Allen QB vs. LB).
    normalized_to_id: Dict[Tuple[str, str], str] = {}
    for player_id, player_data in all_players.items():
        first = player_data.get("first_name", "")
        last = player_data.get("last_name", "")
        name = f"{first} {last}".strip()
        position = player_data.get("position")
        if not name or not position:
            continue
        normalized_to_id[(adp_service.normalize_player_name(name), position)] = player_id

    adp_map: Dict[str, float] = {}
    for entry in snapshot_players:
        raw_name = entry.get("name")
        position = entry.get("position")
        adp_value = entry.get("adp")
        if raw_name is None or position is None or adp_value is None:
            continue

        player_id = normalized_to_id.get((adp_service.normalize_player_name(raw_name), position))
        if player_id is not None:
            adp_map[player_id] = float(adp_value)

    return adp_map, True


_LOADERS = {
    "sleeper": _load_sleeper,
}
for _source in EXTERNAL_SOURCES:
    _LOADERS[_source] = (lambda src: (
        lambda scoring_format, all_players, sleeper_proj: _load_external_snapshot(
            src, scoring_format, all_players, sleeper_proj
        )
    ))(_source)


def get_adp_map(
    source: str, scoring_format: str, all_players: dict, sleeper_proj: dict
) -> Tuple[Dict[str, float], bool]:
    """Get a player_id -> adp_overall map for the requested ADP source.

    Returns (adp_map, source_available). When source_available is False the
    map is empty and callers should fall back to Sleeper ADP.
    """
    loader = _LOADERS.get(source)
    if loader is None:
        raise ValueError(f"Unknown ADP source: {source}. Must be one of {ADP_SOURCES}")

    return loader(scoring_format, all_players, sleeper_proj)
