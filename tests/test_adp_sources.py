"""Tests for src/services/adp_sources.py — the ADP source registry."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.services import adp_sources
from src.data_sources.sleeper_projections_client import PlayerProjection


def _make_proj(player_id: str, adp: float) -> PlayerProjection:
    return PlayerProjection(
        player_id=player_id,
        player_name="Test Player",
        position="RB",
        team="KC",
        projected_pts=200.0,
        avg_ppg=12.5,
        adp=adp,
        gp=16.0,
    )


PLAYER_UNIVERSE = {
    "2307": {"first_name": "Christian", "last_name": "McCaffrey", "position": "RB", "team": "SF"},
    "4866": {"first_name": "CeeDee", "last_name": "Lamb", "position": "WR", "team": "DAL"},
    "6001": {"first_name": "Josh", "last_name": "Allen", "position": "QB", "team": "BUF"},
    "6002": {"first_name": "Josh", "last_name": "Allen", "position": "LB", "team": "JAX"},
}


def _s3_body(payload: dict):
    """Build a mock S3 get_object response body."""
    body = MagicMock()
    body.read.return_value = json.dumps(payload).encode("utf-8")
    return {"Body": body}


class TestSleeperSource:
    def test_reshapes_sleeper_projections_into_adp_map(self):
        sleeper_proj = {
            "2307": _make_proj("2307", 3.5),
            "4866": _make_proj("4866", 10.0),
        }
        adp_map, tier_map, available = adp_sources.get_adp_map("sleeper", "ppr", PLAYER_UNIVERSE, sleeper_proj)

        assert available is True
        assert adp_map == {"2307": 3.5, "4866": 10.0}

    def test_skips_projections_with_no_adp(self):
        sleeper_proj = {"2307": _make_proj("2307", None)}
        adp_map, tier_map, available = adp_sources.get_adp_map("sleeper", "ppr", PLAYER_UNIVERSE, sleeper_proj)

        assert available is True
        assert adp_map == {}


class TestDraftSharksSource:
    def test_fresh_snapshot_joins_by_normalized_name_and_position(self):
        snapshot = {
            "scraped_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "source": "draftsharks",
            "scoring_format": "ppr",
            "players": [
                {"name": "Christian McCaffrey (SF)", "position": "RB", "team": "SF", "adp": 2.1},
                {"name": "CeeDee Lamb (DAL)", "position": "WR", "team": "DAL", "adp": 8.4},
            ],
        }
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = _s3_body(snapshot)

        with patch.dict("os.environ", {"ADP_S3_BUCKET": "test-bucket"}), \
             patch.object(adp_sources, "boto3", MagicMock(client=MagicMock(return_value=mock_s3))):
            adp_map, tier_map, available = adp_sources.get_adp_map("draftsharks", "ppr", PLAYER_UNIVERSE, {})

        assert available is True
        assert adp_map == {"2307": 2.1, "4866": 8.4}

    def test_same_name_different_position_disambiguated(self):
        """Two real players can share a name — position must disambiguate them."""
        snapshot = {
            "scraped_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "draftsharks",
            "scoring_format": "ppr",
            "players": [
                {"name": "Josh Allen", "position": "QB", "team": "BUF", "adp": 25.0},
                {"name": "Josh Allen", "position": "LB", "team": "JAX", "adp": 410.0},
            ],
        }
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = _s3_body(snapshot)

        with patch.dict("os.environ", {"ADP_S3_BUCKET": "test-bucket"}), \
             patch.object(adp_sources, "boto3", MagicMock(client=MagicMock(return_value=mock_s3))):
            adp_map, tier_map, available = adp_sources.get_adp_map("draftsharks", "ppr", PLAYER_UNIVERSE, {})

        assert available is True
        assert adp_map == {"6001": 25.0, "6002": 410.0}

    def test_stale_snapshot_falls_back(self):
        snapshot = {
            "scraped_at": (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat().replace("+00:00", "Z"),
            "source": "draftsharks",
            "scoring_format": "ppr",
            "players": [{"name": "Christian McCaffrey (SF)", "position": "RB", "team": "SF", "adp": 2.1}],
        }
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = _s3_body(snapshot)

        with patch.dict("os.environ", {"ADP_S3_BUCKET": "test-bucket"}), \
             patch.object(adp_sources, "boto3", MagicMock(client=MagicMock(return_value=mock_s3))):
            adp_map, tier_map, available = adp_sources.get_adp_map("draftsharks", "ppr", PLAYER_UNIVERSE, {})

        assert available is False
        assert adp_map == {}

    def test_snapshot_just_under_staleness_threshold_is_used(self):
        snapshot = {
            "scraped_at": (datetime.now(timezone.utc) - timedelta(hours=47)).isoformat().replace("+00:00", "Z"),
            "source": "draftsharks",
            "scoring_format": "ppr",
            "players": [{"name": "Christian McCaffrey (SF)", "position": "RB", "team": "SF", "adp": 2.1}],
        }
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = _s3_body(snapshot)

        with patch.dict("os.environ", {"ADP_S3_BUCKET": "test-bucket"}), \
             patch.object(adp_sources, "boto3", MagicMock(client=MagicMock(return_value=mock_s3))):
            adp_map, tier_map, available = adp_sources.get_adp_map("draftsharks", "ppr", PLAYER_UNIVERSE, {})

        assert available is True
        assert adp_map == {"2307": 2.1}

    def test_missing_s3_object_falls_back_without_raising(self):
        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = Exception("NoSuchKey")

        with patch.dict("os.environ", {"ADP_S3_BUCKET": "test-bucket"}), \
             patch.object(adp_sources, "boto3", MagicMock(client=MagicMock(return_value=mock_s3))):
            adp_map, tier_map, available = adp_sources.get_adp_map("draftsharks", "ppr", PLAYER_UNIVERSE, {})

        assert available is False
        assert adp_map == {}

    def test_missing_bucket_env_var_falls_back_without_raising(self):
        with patch.dict("os.environ", {}, clear=True):
            adp_map, tier_map, available = adp_sources.get_adp_map("draftsharks", "ppr", PLAYER_UNIVERSE, {})

        assert available is False
        assert adp_map == {}

    def test_unmatched_names_are_dropped(self):
        snapshot = {
            "scraped_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "draftsharks",
            "scoring_format": "ppr",
            "players": [{"name": "Nobody Real (XX)", "position": "RB", "team": "XX", "adp": 99.0}],
        }
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = _s3_body(snapshot)

        with patch.dict("os.environ", {"ADP_S3_BUCKET": "test-bucket"}), \
             patch.object(adp_sources, "boto3", MagicMock(client=MagicMock(return_value=mock_s3))):
            adp_map, tier_map, available = adp_sources.get_adp_map("draftsharks", "ppr", PLAYER_UNIVERSE, {})

        assert available is True
        assert adp_map == {}

    def test_matching_name_wrong_position_is_dropped(self):
        """A name match with a mismatched position must not be joined."""
        snapshot = {
            "scraped_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "draftsharks",
            "scoring_format": "ppr",
            "players": [{"name": "Christian McCaffrey (SF)", "position": "WR", "team": "SF", "adp": 2.1}],
        }
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = _s3_body(snapshot)

        with patch.dict("os.environ", {"ADP_S3_BUCKET": "test-bucket"}), \
             patch.object(adp_sources, "boto3", MagicMock(client=MagicMock(return_value=mock_s3))):
            adp_map, tier_map, available = adp_sources.get_adp_map("draftsharks", "ppr", PLAYER_UNIVERSE, {})

        assert available is True
        assert adp_map == {}


def test_unknown_source_raises_value_error():
    with pytest.raises(ValueError):
        adp_sources.get_adp_map("not_a_real_source", "ppr", PLAYER_UNIVERSE, {})
