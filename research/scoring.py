"""Stat line -> fantasy points, for arbitrary scoring settings.

Points are always computed as a dot product of a projected/actual STAT LINE
with a scoring-multiplier dict — never derived from a scoring-format label.
A label (ppr/half_ppr/standard) is only ever used for display, and even then
it's derived from the scoring settings via the shared, pure classifier in
src/analytics/scoring_format.py rather than hand-rolled here.
"""

from typing import Dict

from src.analytics.scoring_format import format_from_scoring_settings

# The 9-component projected/actual stat line every player-week is expressed as.
STAT_COMPONENTS = (
    "passing_yards",
    "passing_tds",
    "interceptions",
    "rushing_yards",
    "rushing_tds",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "fumbles_lost",
)

# Scoring-multiplier presets for the app's three standard formats. Any league
# with custom scoring (TE premium, 6pt pass TDs, ...) just passes its own
# dict with the same keys — score_stat_line doesn't care where it came from.
SCORING_PRESETS: Dict[str, Dict[str, float]] = {
    "ppr": {
        "passing_yards": 0.04,
        "passing_tds": 4,
        "interceptions": -2,
        "rushing_yards": 0.1,
        "rushing_tds": 6,
        "receptions": 1.0,
        "receiving_yards": 0.1,
        "receiving_tds": 6,
        "fumbles_lost": -2,
    },
    "half_ppr": {
        "passing_yards": 0.04,
        "passing_tds": 4,
        "interceptions": -2,
        "rushing_yards": 0.1,
        "rushing_tds": 6,
        "receptions": 0.5,
        "receiving_yards": 0.1,
        "receiving_tds": 6,
        "fumbles_lost": -2,
    },
    "standard": {
        "passing_yards": 0.04,
        "passing_tds": 4,
        "interceptions": -2,
        "rushing_yards": 0.1,
        "rushing_tds": 6,
        "receptions": 0.0,
        "receiving_yards": 0.1,
        "receiving_tds": 6,
        "fumbles_lost": -2,
    },
}


def score_stat_line(stat_line: Dict[str, float], scoring_settings: Dict[str, float]) -> float:
    """Dot product of a stat line with a scoring-multiplier dict.

    Args:
        stat_line: Dict covering some/all of STAT_COMPONENTS. Missing
            components are treated as 0.
        scoring_settings: Dict of component -> points-per-unit multiplier.
            Missing multipliers are treated as 0, so a partial/custom
            settings dict (e.g. only overriding "rec") works fine as long as
            it's merged onto a full preset first.

    Returns:
        Total fantasy points for the stat line under these scoring settings.
    """
    return sum(
        stat_line.get(component, 0.0) * scoring_settings.get(component, 0.0)
        for component in STAT_COMPONENTS
    )


def get_scoring_settings(label: str) -> Dict[str, float]:
    """Look up a scoring-multiplier preset by label ("ppr"/"half_ppr"/"standard")."""
    try:
        return dict(SCORING_PRESETS[label])
    except KeyError:
        raise ValueError(f"Unknown scoring format label: {label!r}. Expected one of {list(SCORING_PRESETS)}.")


def label_for_settings(raw_scoring_settings: Dict[str, float]) -> str:
    """Best-effort label for a RAW (Sleeper-shaped) scoring_settings dict, for display only.

    Takes a league's raw scoring_settings dict (keyed "rec", not our
    "receptions" STAT_COMPONENTS name — see src/data_sources/sleeper_client.py)
    and reuses the app's existing pure classifier rather than re-deriving the
    ppr/half/standard split here. Not meant to be called with one of this
    module's SCORING_PRESETS dicts, which use different keys entirely.
    """
    return format_from_scoring_settings(raw_scoring_settings)
