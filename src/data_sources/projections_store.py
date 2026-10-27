"""Parquet/table store for dbt marts and projection output.

The boundary between the dbt-duckdb transform layer and the Python prediction
layer is this module. dbt writes the marts; Python reads them here. It mirrors
the S3-fallback pattern already used by ``src/services/adp_sources.py`` and
``src/services/environment_score.py``:

    prod: read from S3 (env ``MART_S3_BUCKET``) via boto3
    dev:  read from the local dbt-duckdb database / ``data/`` directory

In dev, ``dbt run`` materializes marts as tables inside a single DuckDB file
(``dbt/lineuplines.duckdb``), *not* as standalone parquet files — dbt-duckdb
places each model in a ``main_<schema>`` schema (e.g. ``main_marts``,
``main_intermediate``). So "reading a mart" in dev means querying that DuckDB
database for the named table. ``load_mart`` resolves the schema for a table
name generically via ``information_schema``, so it works for any mart or
intermediate model without hardcoding which schema a given name lives in.

Every loader degrades gracefully: a missing database, missing table, or
missing parquet file returns an empty ``pl.DataFrame`` and never raises. This
matters because marts are built incrementally — a consumer (e.g. the matchup
grade service) may run before its mart exists and must still behave sanely.
"""

import io
import logging
import os
from pathlib import Path
from typing import List, Optional

import polars as pl

logger = logging.getLogger(__name__)

try:
    import boto3
except Exception:  # pragma: no cover - boto3 is optional in dev
    boto3 = None

try:
    import duckdb
except Exception:  # pragma: no cover - duckdb only needed for local marts
    duckdb = None

# Repo-root relative paths (this file lives at src/data_sources/).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# dev: dbt materializes marts into this DuckDB database.
LOCAL_DUCKDB_PATH = Path(
    os.environ.get("DUCKDB_PATH", str(REPO_ROOT / "dbt" / "lineuplines.duckdb"))
)
# dev: projection service output lives here.
LOCAL_PROJECTIONS_DIR = REPO_ROOT / "data" / "projections"

# S3 key prefixes (prod).
_MART_S3_PREFIX = "marts"
_PROJECTIONS_S3_PREFIX = "projections"


def _mart_bucket() -> Optional[str]:
    """Return the configured mart S3 bucket, or None in dev."""
    return os.environ.get("MART_S3_BUCKET") or None


def _empty() -> pl.DataFrame:
    return pl.DataFrame()


def _filter_season(df: pl.DataFrame, season: Optional[int]) -> pl.DataFrame:
    """Filter to a season when requested and the column exists; else passthrough."""
    if season is None or df.is_empty() or "season" not in df.columns:
        return df
    return df.filter(pl.col("season") == season)


def _duckdb_to_polars(relation) -> pl.DataFrame:
    """Convert a DuckDB result relation to a polars DataFrame without pyarrow.

    DuckDB's native ``.pl()`` requires pyarrow, which is optional here, so we
    go through plain Python rows instead.
    """
    columns = [d[0] for d in relation.description]
    rows = relation.fetchall()
    if not rows:
        return pl.DataFrame(schema=columns)
    return pl.DataFrame(rows, schema=columns, orient="row")


def _load_mart_local(name: str, season: Optional[int]) -> pl.DataFrame:
    """Load a mart/intermediate table from the local dbt DuckDB database.

    Resolves the table's schema generically so the caller only needs the model
    name (e.g. ``mart_matchup_grade``). Returns an empty DataFrame if duckdb is
    unavailable, the database file is missing, or the table does not exist yet.
    """
    if duckdb is None:
        logger.warning("duckdb not available, cannot read local mart %s", name)
        return _empty()

    if not LOCAL_DUCKDB_PATH.exists():
        logger.info("Local dbt DuckDB file not found at %s", LOCAL_DUCKDB_PATH)
        return _empty()

    con = None
    try:
        con = duckdb.connect(str(LOCAL_DUCKDB_PATH), read_only=True)
        schema = con.execute(
            "select table_schema from information_schema.tables "
            "where table_name = ? order by table_schema limit 1",
            [name],
        ).fetchone()
        if schema is None:
            logger.info("Mart table %r not found in %s", name, LOCAL_DUCKDB_PATH)
            return _empty()

        qualified = f'"{schema[0]}"."{name}"'
        df = _duckdb_to_polars(con.execute(f"select * from {qualified}"))
        return _filter_season(df, season)
    except Exception as e:  # pragma: no cover - defensive
        logger.info("Could not read local mart %s: %s", name, e)
        return _empty()
    finally:
        if con is not None:
            con.close()


def _load_mart_s3(bucket: str, name: str, season: Optional[int]) -> pl.DataFrame:
    """Load a mart parquet export from S3. Empty DataFrame when missing."""
    if boto3 is None:
        logger.warning("boto3 not available, cannot read mart %s from S3", name)
        return _empty()

    key = f"{_MART_S3_PREFIX}/{name}.parquet"
    try:
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=bucket, Key=key)
        df = pl.read_parquet(io.BytesIO(obj["Body"].read()))
        return _filter_season(df, season)
    except Exception as e:
        logger.info("No mart parquet available for %s (s3://%s/%s): %s", name, bucket, key, e)
        return _empty()


def load_mart(name: str, season: Optional[int] = None) -> pl.DataFrame:
    """Load a dbt mart by table name. Returns an empty DataFrame if missing.

    Args:
        name: mart/intermediate table name, e.g. ``"mart_matchup_grade"`` or
            ``"mart_player_week_features"``.
        season: if set, filter to that season before returning (no-op when the
            table has no ``season`` column).

    Returns:
        The mart as a polars DataFrame, or an empty DataFrame when the mart is
        unavailable. Never raises — missing marts degrade gracefully so that
        consumers built before their upstream mart exists still function.
    """
    bucket = _mart_bucket()
    if bucket:
        return _load_mart_s3(bucket, name, season)
    return _load_mart_local(name, season)


def _projection_filename(season: int, week: int, scoring_format: str) -> str:
    return f"{season}_wk{week:02d}_{scoring_format}.parquet"


def load_projections(season: int, week: int, scoring_format: str) -> pl.DataFrame:
    """Load the projection service's output parquet for (season, week, scoring).

    Returns an empty DataFrame when no projection output exists for that
    (season, week, scoring_format). Never raises.
    """
    filename = _projection_filename(season, week, scoring_format)
    bucket = _mart_bucket()

    if bucket:
        if boto3 is None:
            logger.warning("boto3 not available, cannot read projections from S3")
            return _empty()
        key = f"{_PROJECTIONS_S3_PREFIX}/{filename}"
        try:
            s3 = boto3.client("s3")
            obj = s3.get_object(Bucket=bucket, Key=key)
            return pl.read_parquet(io.BytesIO(obj["Body"].read()))
        except Exception as e:
            logger.info("No projection output at s3://%s/%s: %s", bucket, key, e)
            return _empty()

    path = LOCAL_PROJECTIONS_DIR / filename
    if not path.exists():
        logger.info("No local projection output at %s", path)
        return _empty()
    try:
        return pl.read_parquet(path)
    except Exception as e:  # pragma: no cover - defensive
        logger.info("Could not read projection output %s: %s", path, e)
        return _empty()


def write_projections(
    df: pl.DataFrame, season: int, week: int, scoring_format: str
) -> None:
    """Persist projection output to S3 (prod) or ``data/projections/`` (dev).

    In prod the parquet is written to ``s3://{MART_S3_BUCKET}/projections/``;
    in dev it lands in the local ``data/projections/`` directory (created if
    needed).
    """
    filename = _projection_filename(season, week, scoring_format)
    bucket = _mart_bucket()

    if bucket:
        if boto3 is None:
            raise RuntimeError("boto3 is required to write projections to S3")
        buffer = io.BytesIO()
        df.write_parquet(buffer)
        buffer.seek(0)
        key = f"{_PROJECTIONS_S3_PREFIX}/{filename}"
        s3 = boto3.client("s3")
        s3.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())
        logger.info("Wrote projections to s3://%s/%s", bucket, key)
        return

    LOCAL_PROJECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = LOCAL_PROJECTIONS_DIR / filename
    df.write_parquet(path)
    logger.info("Wrote projections to %s", path)


__all__: List[str] = ["load_mart", "load_projections", "write_projections"]
