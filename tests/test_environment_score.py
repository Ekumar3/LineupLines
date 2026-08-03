"""Tests for src/services/environment_score.py — the team environment score loader."""

import io
from unittest.mock import MagicMock, patch

from src.services import environment_score


def _s3_csv_body(csv_text: str):
    """Build a mock S3 get_object response body streaming the given CSV text.

    io.TextIOWrapper needs a readable stream, so this hands back a real
    BytesIO rather than a MagicMock.
    """
    return {"Body": io.BytesIO(csv_text.encode("utf-8"))}


CSV_TEXT = (
    "rank,team,implied_ppg,avg_game_total,shootout_rate,low_total_rate,score\n"
    "1,Dallas Cowboys,25.74,50.32,88.2%,0.0%,3.12\n"
    "2,Cincinnati Bengals,25.97,49.09,64.7%,0.0%,2.67\n"
)


def test_happy_path_parses_csv_keyed_by_abbreviation():
    mock_s3 = MagicMock()
    mock_s3.get_object.return_value = _s3_csv_body(CSV_TEXT)

    with patch.dict("os.environ", {"ADP_S3_BUCKET": "test-bucket"}), \
         patch.object(environment_score, "boto3", MagicMock(client=MagicMock(return_value=mock_s3))):
        result = environment_score.get_environment_map()

    assert result == {
        "DAL": {"rank": 1, "score": 3.12},
        "CIN": {"rank": 2, "score": 2.67},
    }


def test_missing_bucket_env_var_returns_empty_without_raising():
    with patch.dict("os.environ", {}, clear=True):
        result = environment_score.get_environment_map()

    assert result == {}


def test_missing_s3_object_returns_empty_without_raising():
    mock_s3 = MagicMock()
    mock_s3.get_object.side_effect = Exception("NoSuchKey")

    with patch.dict("os.environ", {"ADP_S3_BUCKET": "test-bucket"}), \
         patch.object(environment_score, "boto3", MagicMock(client=MagicMock(return_value=mock_s3))):
        result = environment_score.get_environment_map()

    assert result == {}


def test_malformed_row_is_skipped_but_others_still_parsed():
    csv_text = (
        "rank,team,implied_ppg,avg_game_total,shootout_rate,low_total_rate,score\n"
        "1,Dallas Cowboys,25.74,50.32,88.2%,0.0%,3.12\n"
        "not_a_number,Cincinnati Bengals,25.97,49.09,64.7%,0.0%,not_a_score\n"
    )
    mock_s3 = MagicMock()
    mock_s3.get_object.return_value = _s3_csv_body(csv_text)

    with patch.dict("os.environ", {"ADP_S3_BUCKET": "test-bucket"}), \
         patch.object(environment_score, "boto3", MagicMock(client=MagicMock(return_value=mock_s3))):
        result = environment_score.get_environment_map()

    assert result == {"DAL": {"rank": 1, "score": 3.12}}


def test_unmapped_team_name_is_skipped():
    csv_text = (
        "rank,team,implied_ppg,avg_game_total,shootout_rate,low_total_rate,score\n"
        "1,Some Fictional Team,25.74,50.32,88.2%,0.0%,3.12\n"
    )
    mock_s3 = MagicMock()
    mock_s3.get_object.return_value = _s3_csv_body(csv_text)

    with patch.dict("os.environ", {"ADP_S3_BUCKET": "test-bucket"}), \
         patch.object(environment_score, "boto3", MagicMock(client=MagicMock(return_value=mock_s3))):
        result = environment_score.get_environment_map()

    assert result == {}


def test_stale_alias_oakland_raiders_maps_to_lv():
    csv_text = (
        "rank,team,implied_ppg,avg_game_total,shootout_rate,low_total_rate,score\n"
        "30,Oakland Raiders,19.13,42.97,0.0%,35.3%,-2.86\n"
    )
    mock_s3 = MagicMock()
    mock_s3.get_object.return_value = _s3_csv_body(csv_text)

    with patch.dict("os.environ", {"ADP_S3_BUCKET": "test-bucket"}), \
         patch.object(environment_score, "boto3", MagicMock(client=MagicMock(return_value=mock_s3))):
        result = environment_score.get_environment_map()

    assert result == {"LV": {"rank": 30, "score": -2.86}}
