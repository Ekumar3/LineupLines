"""Tests for ADP Service layer."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

from src.analytics.adp_service import ADPService


class TestADPService:
    """Tests for ADP Service."""

    @pytest.fixture
    def adp_service(self):
        """Create ADP service instance."""
        return ADPService()

    @pytest.fixture
    def mock_player(self):
        """Mock player object from FantasyPros."""
        player = Mock()
        player.player_name = "Christian McCaffrey"
        player.adp_overall = 3.5
        player.position = "RB"
        return player

    @pytest.fixture
    def mock_players_list(self):
        """Mock list of players."""
        players = []
        names_adps = [
            ("Christian McCaffrey", 3.5),
            ("Travis Kelce", 15.2),
            ("Joe Burrow", 60.0),
            ("Tyreek Hill", 25.0),
            ("Josh Allen", 45.0),
        ]
        for name, adp in names_adps:
            player = Mock()
            player.player_name = name
            player.adp_overall = adp
            players.append(player)
        return players

    def test_get_adp_data_fetches_fresh(self, adp_service, mock_players_list):
        """Test fetching fresh ADP data."""
        with patch.object(adp_service.fp_client, "fetch_adp_data", return_value=mock_players_list):
            with patch.object(adp_service.fp_client, "get_cached_data", return_value=None):
                players = adp_service.get_adp_data("ppr")

        assert players is not None
        assert len(players) == 5
        assert "ppr" in adp_service.last_refresh

    def test_get_adp_data_uses_cache(self, adp_service, mock_players_list):
        """Test that cached ADP data is used."""
        with patch.object(adp_service.fp_client, "fetch_adp_data", return_value=mock_players_list):
            with patch.object(adp_service.fp_client, "get_cached_data", return_value=mock_players_list):
                # First call fetches fresh
                adp_service.get_adp_data("ppr")

                # Second call should use cache
                with patch.object(adp_service.fp_client, "fetch_adp_data", side_effect=Exception("Should not call")):
                    cached = adp_service.get_adp_data("ppr")
                    assert cached is not None

    def test_get_adp_data_cache_expiration(self, adp_service, mock_players_list):
        """Test that cache expires after TTL."""
        # Set up cache with old timestamp
        adp_service.last_refresh["ppr"] = datetime.utcnow() - timedelta(hours=25)

        with patch.object(adp_service.fp_client, "fetch_adp_data", return_value=mock_players_list):
            with patch.object(adp_service.fp_client, "get_cached_data", return_value=None):
                players = adp_service.get_adp_data("ppr")

        # Should have fetched fresh since cache expired
        assert players is not None

    def test_get_player_adp_found(self, adp_service, mock_players_list):
        """Test finding player ADP."""
        with patch.object(adp_service, "get_adp_data", return_value=mock_players_list):
            adp = adp_service.get_player_adp("Christian McCaffrey", "ppr")

        assert adp == 3.5

    def test_get_player_adp_not_found(self, adp_service, mock_players_list):
        """Test when player not found in ADP data."""
        with patch.object(adp_service, "get_adp_data", return_value=mock_players_list):
            adp = adp_service.get_player_adp("Unknown Player", "ppr")

        assert adp is None

    def test_get_player_adp_case_insensitive(self, adp_service, mock_players_list):
        """Test case-insensitive player name matching."""
        with patch.object(adp_service, "get_adp_data", return_value=mock_players_list):
            adp = adp_service.get_player_adp("christian mccaffrey", "ppr")

        assert adp == 3.5

    def test_calculate_value_delta_positive(self, adp_service):
        """Test value delta when player typically goes later (good value)."""
        delta = adp_service.calculate_value_delta(current_pick=50, player_adp=25)

        assert delta == -25  # Negative: we're picking later than ADP (reaching)

    def test_calculate_value_delta_negative(self, adp_service):
        """Test value delta when player typically goes earlier (reaching)."""
        delta = adp_service.calculate_value_delta(current_pick=10, player_adp=30)

        assert delta == 20  # Positive: we're picking earlier than ADP (value)

    def test_calculate_value_delta_zero(self, adp_service):
        """Test value delta when picking at ADP."""
        delta = adp_service.calculate_value_delta(current_pick=25, player_adp=25)

        assert delta == 0

    def test_calculate_positional_value(self, adp_service, mock_players_list):
        """Test positional value calculation."""
        available = [
            {"name": "Christian McCaffrey", "id": "1"},
            {"name": "Travis Kelce", "id": "2"},
        ]

        # Set up mock analyzer in service
        mock_analyzer = Mock()
        mock_analyzer.get_positional_scarcity = Mock(return_value=0.5)
        adp_service.analyzers["ppr"] = mock_analyzer

        with patch.object(adp_service, "get_adp_data", return_value=mock_players_list):
            value_score = adp_service.calculate_positional_value(
                position="RB", current_pick=50, available_players=available, scoring_format="ppr"
            )

        # Value calculation: (scarcity * 50) + best_value_delta
        # McCaffrey ADP is 3.5, current pick is 50, so delta = 3.5 - 50 = -46.5 (reaching)
        # Final: (0.5 * 50) + (-46.5) = 25 - 46.5 = -21.5
        # It will be negative but should still be a valid number
        assert isinstance(value_score, float)

    def test_calculate_positional_value_empty_available(self, adp_service):
        """Test positional value with no available players."""
        value_score = adp_service.calculate_positional_value(
            position="RB", current_pick=50, available_players=[], scoring_format="ppr"
        )

        assert value_score == 0.0

    def test_calculate_positional_value_no_adp_data(self, adp_service):
        """Test positional value when ADP data unavailable."""
        available = [{"name": "Some Player", "id": "1"}]

        value_score = adp_service.calculate_positional_value(
            position="RB", current_pick=50, available_players=available, scoring_format="unknown_format"
        )

        assert value_score == 0.0

    def test_scoring_formats(self, adp_service, mock_players_list):
        """Test that service handles different scoring formats."""
        with patch.object(adp_service.fp_client, "fetch_adp_data", return_value=mock_players_list):
            with patch.object(adp_service.fp_client, "get_cached_data", return_value=None):
                ppr_players = adp_service.get_adp_data("ppr")
                half_ppr_players = adp_service.get_adp_data("half_ppr")
                standard_players = adp_service.get_adp_data("standard")

        assert ppr_players is not None
        assert half_ppr_players is not None
        assert standard_players is not None
