"""Tests for research/scoring.py — stat line -> points for arbitrary scoring settings."""

from research.scoring import get_scoring_settings, label_for_settings, score_stat_line

STAT_LINE = {
    "passing_yards": 250,
    "passing_tds": 2,
    "interceptions": 1,
    "rushing_yards": 30,
    "rushing_tds": 0,
    "receptions": 5,
    "receiving_yards": 60,
    "receiving_tds": 1,
    "fumbles_lost": 0,
}


def test_ppr_derives_correctly_from_stat_line():
    points = score_stat_line(STAT_LINE, get_scoring_settings("ppr"))
    # 250*0.04 + 2*4 - 1*2 + 30*0.1 + 0 + 5*1 + 60*0.1 + 1*6 + 0
    # = 10 + 8 - 2 + 3 + 0 + 5 + 6 + 6 + 0 = 36
    assert points == 36.0


def test_half_ppr_derives_correctly_from_stat_line():
    points = score_stat_line(STAT_LINE, get_scoring_settings("half_ppr"))
    # Same as PPR but receptions worth 0.5 instead of 1.0 -> 36 - 5 + 2.5
    assert points == 33.5


def test_standard_derives_correctly_from_stat_line():
    points = score_stat_line(STAT_LINE, get_scoring_settings("standard"))
    # Same as PPR but receptions worth 0 -> 36 - 5
    assert points == 31.0


def test_missing_components_default_to_zero():
    partial_line = {"receiving_yards": 100}
    points = score_stat_line(partial_line, get_scoring_settings("ppr"))
    assert points == 10.0  # 100 * 0.1, everything else absent -> 0


def test_custom_multiplier_dict_works_without_a_preset():
    # e.g. a 6pt-passing-TD, TE-premium-style league bolted onto a partial dict.
    custom = {"passing_tds": 6, "receptions": 1.5}
    points = score_stat_line({"passing_tds": 2, "receptions": 4}, custom)
    assert points == 2 * 6 + 4 * 1.5


def test_unknown_preset_label_raises():
    import pytest

    with pytest.raises(ValueError):
        get_scoring_settings("not_a_real_format")


def test_label_for_settings_reuses_shared_classifier():
    # label_for_settings takes a RAW (Sleeper-shaped, "rec"-keyed) scoring_settings
    # dict, not one of our internal SCORING_PRESETS — see its docstring.
    assert label_for_settings({"rec": 1.0}) == "ppr"
    assert label_for_settings({"rec": 0.5}) == "half_ppr"
    assert label_for_settings({"rec": 0.0}) == "standard"
