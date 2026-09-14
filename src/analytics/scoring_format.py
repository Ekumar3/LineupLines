"""Pure scoring-format classification — no network calls, no I/O.

Maps a league's scoring_settings dict to one of the app's three scoring
format labels ("ppr", "half_ppr", "standard") based on reception points.
Extracted from SleeperClient.get_scoring_format so the classification logic
has exactly one home and can be reused by offline/research code that has a
scoring_settings dict but no Sleeper client to fetch one from.
"""

from typing import Dict


def format_from_scoring_settings(scoring_settings: Dict[str, float]) -> str:
    """Classify a league's scoring settings into "ppr", "half_ppr", or "standard".

    Maps Sleeper's reception points to standard scoring formats:
    - 1.0 points per reception = PPR
    - 0.5 points per reception = Half-PPR
    - 0.0 points per reception = Standard
    - Anything else (custom scoring) snaps to the closest of the three.

    Args:
        scoring_settings: A league's scoring_settings dict (or any dict with
            a "rec" key giving points per reception).

    Returns:
        One of "ppr", "half_ppr", "standard".
    """
    rec_points = scoring_settings.get("rec", 0)

    if rec_points == 1.0:
        return "ppr"
    elif rec_points == 0.5:
        return "half_ppr"
    elif rec_points == 0.0:
        return "standard"

    # Custom scoring - default to closest match
    if rec_points > 0.75:
        return "ppr"
    elif rec_points > 0.25:
        return "half_ppr"
    else:
        return "standard"
