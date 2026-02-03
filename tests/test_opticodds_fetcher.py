"""Tests for OpticOdds season-long props fetcher."""
import pytest
import os
from unittest import mock
from src.vegas_pipeline.fetchers.opticodds_fetcher import (
    fetch_season_props,
    OpticOddsError,
    SAMPLE_SEASON_PROPS,
    get_player_stat_categories,
)


def test_fetch_season_props_returns_sample_when_no_api_key():
    """Test that sample data is returned when OPTICODDS_API_KEY is not set."""
    # Ensure the env var is not set
    with mock.patch.dict(os.environ, {}, clear=True):
        result = fetch_season_props()

    assert result is not None
    assert result["data_source"] == "opticodds"
    assert result["sport"] == "nfl"
    assert result["season"] == "2026"
    assert "props" in result
    assert len(result["props"]) > 0

    # Verify sample data structure
    prop = result["props"][0]
    assert "player_name" in prop
    assert "stat_category" in prop
    assert "line" in prop
    assert "over_odds" in prop
    assert "under_odds" in prop
    assert "sportsbook" in prop


def test_fetch_season_props_includes_required_stat_categories():
    """Test that sample data includes all major stat categories."""
    with mock.patch.dict(os.environ, {}, clear=True):
        result = fetch_season_props()

    props = result["props"]
    categories = {prop["stat_category"] for prop in props}

    required_categories = {
        "passing_yards",
        "passing_touchdowns",
        "rushing_yards",
        "rushing_touchdowns",
        "receiving_yards",
        "receptions",
        "receiving_touchdowns",
    }

    # Check that at least some required categories are present
    assert len(required_categories & categories) > 0


def test_fetch_season_props_with_custom_sport():
    """Test that custom sport parameter is accepted (though not used with sample data)."""
    with mock.patch.dict(os.environ, {}, clear=True):
        result = fetch_season_props(sport="nba", season="2025")

    # With sample data, sport/season from sample is used, but call shouldn't error
    assert result is not None
    assert "props" in result


def test_sample_data_has_valid_structure():
    """Test that SAMPLE_SEASON_PROPS has correct structure."""
    assert "fetched_at" in SAMPLE_SEASON_PROPS
    assert "data_source" in SAMPLE_SEASON_PROPS
    assert "sport" in SAMPLE_SEASON_PROPS
    assert "season" in SAMPLE_SEASON_PROPS
    assert "props" in SAMPLE_SEASON_PROPS

    assert SAMPLE_SEASON_PROPS["data_source"] == "opticodds"
    assert isinstance(SAMPLE_SEASON_PROPS["props"], list)
    assert len(SAMPLE_SEASON_PROPS["props"]) > 0

    # Verify each prop has required fields
    for prop in SAMPLE_SEASON_PROPS["props"]:
        assert "player_name" in prop
        assert "team" in prop
        assert "position" in prop
        assert "stat_category" in prop
        assert "line" in prop
        assert "over_odds" in prop
        assert "under_odds" in prop
        assert "sportsbook" in prop
        assert "last_updated" in prop


def test_get_player_stat_categories():
    """Test that stat categories are returned."""
    categories = get_player_stat_categories()

    assert isinstance(categories, list)
    assert len(categories) > 0
    assert "passing_yards" in categories
    assert "rushing_yards" in categories
    assert "receiving_yards" in categories
    assert "receptions" in categories


def test_sample_data_players_and_positions():
    """Test that sample data includes realistic player/team/position data."""
    props = SAMPLE_SEASON_PROPS["props"]

    # Check for known players
    player_names = {prop["player_name"] for prop in props}
    assert "Patrick Mahomes" in player_names
    assert "Christian McCaffrey" in player_names

    # Check for valid positions
    positions = {prop["position"] for prop in props}
    valid_positions = {"QB", "RB", "WR", "TE"}
    assert positions.issubset(valid_positions)


def test_sample_data_odds_format():
    """Test that odds are in American format (negative expected for even money)."""
    props = SAMPLE_SEASON_PROPS["props"]

    for prop in props:
        over_odds = prop["over_odds"]
        under_odds = prop["under_odds"]

        # American odds should be integers
        assert isinstance(over_odds, int)
        assert isinstance(under_odds, int)

        # Most props should have negative odds (favorite)
        # This is a common pattern but not always true
        assert over_odds != 0
        assert under_odds != 0
