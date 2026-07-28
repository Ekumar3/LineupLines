"""Sleeper player universe lookup for cross-referencing scraped ADP.

Builds the same (normalized_name, position) -> player_id join key that
src/services/adp_sources.py._load_external_snapshot uses at read time, so
the DAG's match-rate check and the app's own join logic never disagree.
"""

from src.data_sources.sleeper_client import SleeperClient
from src.analytics.adp_service import adp_service


def build_name_position_index() -> dict[tuple[str, str], str]:
    """Return {(normalized_name, position): player_id} for the Sleeper universe."""
    all_players = SleeperClient().get_players()

    index: dict[tuple[str, str], str] = {}
    for player_id, player_data in all_players.items():
        first = player_data.get("first_name", "")
        last = player_data.get("last_name", "")
        name = f"{first} {last}".strip()
        position = player_data.get("position")
        if not name or not position:
            continue
        index[(adp_service.normalize_player_name(name), position)] = player_id

    return index
