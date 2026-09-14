"""DuckDB helpers over the partitioned prediction log.

The prediction log only denormalizes PPR points (expected_points_ppr,
actual_points_ppr) for convenience — everything else is meant to be derived
from the stored 9-component stat line via research.scoring.score_stat_line.
`predictions_half` proves that out: it rebuilds half-PPR points in SQL
straight from the same projected_*/actual_* columns, using the same
half_ppr preset scoring.py exposes, rather than from any stored point total.
"""

from pathlib import Path
from typing import Optional

import duckdb

from research.scoring import STAT_COMPONENTS, get_scoring_settings

PREDICTIONS_DIR = Path(__file__).resolve().parent / "data" / "predictions"
_PREDICTIONS_GLOB = str(PREDICTIONS_DIR / "season=*" / "week=*" / "*.parquet")


def _score_sql(prefix: str, scoring_settings: dict) -> str:
    """SQL expression for score_stat_line() over columns named f"{prefix}_{component}"."""
    terms = [
        f"COALESCE({prefix}_{component}, 0) * {scoring_settings.get(component, 0.0)}"
        for component in STAT_COMPONENTS
    ]
    return " + ".join(terms)


def connect(predictions_glob: Optional[str] = None) -> duckdb.DuckDBPyConnection:
    """Open an in-memory DuckDB connection with `predictions` and `predictions_half` views.

    `predictions` reads every partitioned parquet file under
    research/data/predictions/season=*/week=*/*.parquet. `predictions_half`
    layers half-PPR points (expected_points_half, actual_points_half) on top,
    computed in SQL from the raw stat-line columns.
    """
    con = duckdb.connect()
    glob = predictions_glob or _PREDICTIONS_GLOB
    con.execute(
        f"CREATE OR REPLACE VIEW predictions AS "
        f"SELECT * FROM read_parquet('{glob}', union_by_name=True)"
    )

    half_ppr = get_scoring_settings("half_ppr")
    con.execute(
        f"""
        CREATE OR REPLACE VIEW predictions_half AS
        SELECT *,
               {_score_sql("projected", half_ppr)} AS expected_points_half,
               {_score_sql("actual", half_ppr)} AS actual_points_half
        FROM predictions
        """
    )
    return con
