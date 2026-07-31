"""ADP source registry — dispatches to whichever ADP provider is requested.

The available-players table can be driven by different ADP providers (Sleeper's
native ADP, or externally scraped sources like DraftSharks). Only one source is
active at a time. Sleeper is computed in-process from data the caller already
fetched; every other source is read from a JSON snapshot in S3 dropped by the
scraping pipeline at s3://{ADP_S3_BUCKET}/adp/{source}/{scoring_format}/latest.json:

    {
      "scraped_at": "2026-07-20T08:00:00Z",
      "source": "draftsharks",
      "scoring_format": "ppr",
      "players": [
        {"name": "josh allen", "position": "QB", "team": "BUF", "adp": 25.0, "tier": 3, "positional_tier": 2},
        {"name": "josh allen", "position": "LB", "team": "JAX", "adp": 410.0, "tier": 15, "positional_tier": 8}
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
EXTERNAL_SOURCES = ("draftsharks",)
ADP_SOURCES = ("sleeper",) + EXTERNAL_SOURCES

STALE_AFTER = timedelta(hours=48)


def _load_sleeper(scoring_format: str, all_players: dict, sleeper_proj: dict) -> Tuple[Dict[str, float], Dict[str, Dict[str, int]], bool]:
    """Reshape already-fetched Sleeper projections into player_id -> adp."""
    return (
        {player_id: proj.adp for player_id, proj in sleeper_proj.items() if proj.adp is not None},
        {},
        True,
    )


def _load_external_snapshot(source: str, scoring_format: str, all_players: dict, sleeper_proj: dict) -> Tuple[Dict[str, float], Dict[str, Dict[str, int]], bool]:
    """Load an externally-scraped ADP snapshot from S3 and join it to player_id by name.

    Returns ({}, {}, False) whenever the snapshot is missing, stale (>48h old), or
    can't be read — callers are expected to fall back to Sleeper ADP in that case.
    """
    bucket = os.environ.get("ADP_S3_BUCKET")
    if not bucket:
        logger.warning("ADP_S3_BUCKET not set, cannot load external ADP source %s", source)
        return {}, {}, False

    if boto3 is None:
        logger.warning("boto3 not available, cannot load external ADP source %s", source)
        return {}, {}, False

    key = f"adp/{source}/{scoring_format}/latest.json"
    try:
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=bucket, Key=key)
        snapshot = json.loads(obj["Body"].read())
    except Exception as e:
        logger.info("No ADP snapshot available for %s/%s: %s", source, scoring_format, e)
        return {}, {}, False

    try:
        scraped_at = datetime.fromisoformat(snapshot["scraped_at"].replace("Z", "+00:00"))
        if scraped_at.tzinfo is None:
            scraped_at = scraped_at.replace(tzinfo=timezone.utc)
    except Exception as e:
        logger.warning("Malformed scraped_at in %s/%s snapshot: %s", source, scoring_format, e)
        return {}, {}, False

    age = datetime.now(timezone.utc) - scraped_at
    if age > STALE_AFTER:
        logger.warning(
            "Stale ADP snapshot for %s/%s (age=%s, threshold=%s), falling back",
            source, scoring_format, age, STALE_AFTER,
        )
        return {}, {}, False

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
    tier_map: Dict[str, Dict[str, int]] = {}
    for entry in snapshot_players:
        raw_name = entry.get("name")
        position = entry.get("position")
        tier = entry.get("tier")
        positional_tier = entry.get("positional_tier")
        adp_value = entry.get("adp")
        if raw_name is None or position is None or adp_value is None:
            continue

        player_id = normalized_to_id.get((adp_service.normalize_player_name(raw_name), position))
        if player_id is not None:
            adp_map[player_id] = float(adp_value)
            tier_map[player_id] = {"tier": tier, "positional_tier": positional_tier}

    return adp_map, tier_map, True


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
) -> Tuple[Dict[str, float], Dict[str, Dict[str, int]], bool]:
    """Get player_id -> adp_overall and player_id -> tier maps for the requested ADP source.

    Returns (adp_map, tier_map, source_available). When source_available is False
    both maps are empty and callers should fall back to Sleeper ADP.
    """
    loader = _LOADERS.get(source)
    if loader is None:
        raise ValueError(f"Unknown ADP source: {source}. Must be one of {ADP_SOURCES}")

    return loader(scoring_format, all_players, sleeper_proj)


# Only the S3 keys scraped for a live snake/linear draft's undrafted-player view
# (excludes the dynasty rookies-only keys, which are for a rookie-draft-only
# view we don't have yet, and auction_ppr, whose values are dollar amounts, not
# pick numbers — mixing that into adp_delta's "current_pick - adp" math would
# be nonsensical). See src/data_sources/draft_sharks_client.py RANKING_PATHS
# for the full scraped set.
DRAFTSHARKS_STANDARD_KEYS = {"ppr", "half_ppr", "standard"}
DRAFTSHARKS_DYNASTY_KEYS = {
    "ppr": "dynasty_ppr",
    "half_ppr": "dynasty_half_ppr",
    "superflex": "dynasty_ppr_superflex",
    "te_premium": "dynasty_te_premium",
    "te_premium_superflex": "dynasty_te_premium_superflex",
}
DRAFTSHARKS_KEEPER_KEYS = {
    "ppr": "keeper_ppr",
    "superflex": "keeper_superflex",
}


def resolve_draftsharks_ranking_key(
    scoring_format: str, league_type: str, is_superflex: bool, is_te_premium: bool
) -> str:
    """Pick the DraftSharks S3 key that best matches a Sleeper league's settings.

    Args:
        scoring_format: "ppr" | "half_ppr" | "standard" (from league scoring_settings.rec)
        league_type: Sleeper's league.settings.type as a string — "0" (redraft),
            "1" (keeper), or "2" (dynasty). Anything else is treated as redraft.
        is_superflex: True if the league starts a QB in a superflex/2QB slot.
        is_te_premium: True if the league awards bonus points for TE receptions.

    Returns:
        A key from DraftSharksClient.RANKING_PATHS. Falls back to the closest
        available combination when the league's exact combo wasn't scraped
        (e.g. a standard-scoring dynasty league falls back to dynasty_ppr,
        since no non-PPR dynasty key is scraped) rather than silently
        dropping the dynasty/keeper adjustment.
    """
    if league_type == "2":  # dynasty
        if is_te_premium:
            return DRAFTSHARKS_DYNASTY_KEYS["te_premium_superflex" if is_superflex else "te_premium"]
        if is_superflex:
            return DRAFTSHARKS_DYNASTY_KEYS["superflex"]
        return DRAFTSHARKS_DYNASTY_KEYS["half_ppr" if scoring_format == "half_ppr" else "ppr"]

    if league_type == "1":  # keeper
        return DRAFTSHARKS_KEEPER_KEYS["superflex" if is_superflex else "ppr"]

    # Redraft: no superflex/TE-premium variant scraped for this section, so
    # scoring format is the only axis we can honor.
    return scoring_format if scoring_format in DRAFTSHARKS_STANDARD_KEYS else "ppr"
