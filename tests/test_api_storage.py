"""Tests for API storage layer functions."""

import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile

import src.api.storage as storage_module
from src.api.storage import (
    save_player_universe,
    load_player_universe,
    get_player_universe_age,
)


class TestPlayerUniverseStorage:
    """Tests for player universe storage and loading."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear the in-memory player universe cache before each test."""
        storage_module._player_universe_cache = None
        yield
        storage_module._player_universe_cache = None

    @pytest.fixture
    def sample_players(self):
        """Sample player data."""
        return {
            "2307": {
                "first_name": "Christian",
                "last_name": "McCaffrey",
                "position": "RB",
                "team": "SF",
                "age": 27,
                "years_exp": 7,
            },
            "4866": {
                "first_name": "CeeDee",
                "last_name": "Lamb",
                "position": "WR",
                "team": "DAL",
                "age": 24,
                "years_exp": 3,
            },
            "5000": {
                "first_name": "Joe",
                "last_name": "Burrow",
                "position": "QB",
                "team": "CIN",
                "age": 27,
                "years_exp": 4,
            },
        }

    def test_save_and_load_player_universe(self, sample_players, tmp_path):
        """Test saving and loading player data."""
        test_file = tmp_path / "test_players.json"

        with patch("src.api.storage.PLAYER_DATA_FILE", test_file):
            # Save
            save_player_universe(sample_players)
            assert test_file.exists()

            # Verify file structure
            with open(test_file, 'r') as f:
                data = json.load(f)
            assert "updated_at" in data
            assert "player_count" in data
            assert "players" in data
            assert data["player_count"] == 3

            # Load
            loaded = load_player_universe()
            assert loaded == sample_players

    def test_load_nonexistent_file(self):
        """Test loading when file doesn't exist."""
        with patch(
            "src.api.storage.PLAYER_DATA_FILE",
            Path("/nonexistent/path/players.json"),
        ):
            result = load_player_universe()
            assert result is None

    def test_load_corrupted_file(self, tmp_path):
        """Test loading corrupted JSON file."""
        test_file = tmp_path / "corrupted.json"
        test_file.write_text("{ invalid json }")

        with patch("src.api.storage.PLAYER_DATA_FILE", test_file):
            result = load_player_universe()
            assert result is None

    def test_get_player_universe_age(self, sample_players, tmp_path):
        """Test getting player data age."""
        test_file = tmp_path / "test_players.json"

        with patch("src.api.storage.PLAYER_DATA_FILE", test_file):
            # Should be None before saving
            age = get_player_universe_age()
            assert age is None

            # Save data
            save_player_universe(sample_players)

            # Should have a timestamp now
            age = get_player_universe_age()
            assert age is not None
            assert isinstance(age, str)
            # Should be ISO format
            assert "T" in age  # ISO format has T between date and time

    def test_save_empty_player_universe(self, tmp_path):
        """Test saving empty player dictionary."""
        test_file = tmp_path / "empty_players.json"

        with patch("src.api.storage.PLAYER_DATA_FILE", test_file):
            save_player_universe({})
            assert test_file.exists()

            loaded = load_player_universe()
            assert loaded == {}

    def test_save_large_player_universe(self, tmp_path):
        """Test saving large player universe."""
        # Create 1000 players
        large_players = {
            f"{i}": {
                "first_name": f"Player{i}",
                "last_name": f"Last{i}",
                "position": "RB" if i % 4 == 0 else "WR",
                "team": "NFL",
            }
            for i in range(1000)
        }

        test_file = tmp_path / "large_players.json"

        with patch("src.api.storage.PLAYER_DATA_FILE", test_file):
            save_player_universe(large_players)
            loaded = load_player_universe()
            assert len(loaded) == 1000
            assert loaded["500"]["first_name"] == "Player500"

    def test_player_data_structure_preservation(self, sample_players, tmp_path):
        """Test that player data structure is preserved through save/load."""
        test_file = tmp_path / "test_players.json"

        with patch("src.api.storage.PLAYER_DATA_FILE", test_file):
            save_player_universe(sample_players)
            loaded = load_player_universe()

            # Check specific player data
            original_player = sample_players["2307"]
            loaded_player = loaded["2307"]

            assert original_player == loaded_player
            assert loaded_player["first_name"] == "Christian"
            assert loaded_player["position"] == "RB"
            assert loaded_player["age"] == 27

    def test_create_player_data_directory(self, tmp_path):
        """Test that player data directory is created if it doesn't exist."""
        nested_path = tmp_path / "new" / "nested" / "dir" / "players.json"

        sample_players = {
            "1": {
                "first_name": "Test",
                "last_name": "Player",
                "position": "RB",
            }
        }

        with patch("src.api.storage.PLAYER_DATA_FILE", nested_path):
            save_player_universe(sample_players)
            assert nested_path.exists()
            assert nested_path.parent.exists()

    def test_load_preserves_optional_fields(self, tmp_path):
        """Test that optional fields in player data are preserved."""
        players_with_optional = {
            "2307": {
                "first_name": "Christian",
                "last_name": "McCaffrey",
                "position": "RB",
                "team": "SF",
                "age": 27,
                "years_exp": 7,
                "nfl_id": "12345",  # Extra optional field
            },
            "4866": {
                "first_name": "CeeDee",
                "last_name": "Lamb",
                "position": "WR",
                # Missing some optional fields
            },
        }

        test_file = tmp_path / "optional_fields.json"

        with patch("src.api.storage.PLAYER_DATA_FILE", test_file):
            save_player_universe(players_with_optional)
            loaded = load_player_universe()

            # Check that optional fields are preserved
            assert loaded["2307"]["nfl_id"] == "12345"
            assert "years_exp" not in loaded["4866"]  # Preserved as not present
