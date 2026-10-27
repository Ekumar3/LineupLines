"""Tests for src/data_sources/projections_store.py.

Covers graceful degradation (missing marts/parquet return empty DataFrames
and never raise), the write/load round-trip in a temp directory, and season
filtering of marts.

These tests exercise the dev (local) code path. The S3 bucket env var
(``MART_S3_BUCKET``) is cleared so ``load_mart``/``load_projections`` use the
local DuckDB/parquet readers rather than boto3.
"""

import polars as pl
import pytest

from src.data_sources import projections_store


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch):
    """Force the local (non-S3) code path for every test."""
    monkeypatch.delenv("MART_S3_BUCKET", raising=False)


@pytest.fixture
def temp_projections_dir(tmp_path, monkeypatch):
    """Point the projections store at an isolated temp directory."""
    target = tmp_path / "projections"
    monkeypatch.setattr(projections_store, "LOCAL_PROJECTIONS_DIR", target)
    return target


@pytest.fixture
def temp_duckdb(tmp_path, monkeypatch):
    """Point the mart loader at a DuckDB file inside the temp directory.

    The file is not created here — tests decide whether to materialize it,
    which lets us cover both the missing-file and present-file paths.
    """
    db_path = tmp_path / "lineuplines.duckdb"
    monkeypatch.setattr(projections_store, "LOCAL_DUCKDB_PATH", db_path)
    return db_path


# ---------------------------------------------------------------------------
# Graceful degradation: missing files/tables return empty, never raise.
# ---------------------------------------------------------------------------

def test_load_mart_missing_database_returns_empty(temp_duckdb):
    # The DuckDB file was never created.
    assert not temp_duckdb.exists()

    result = projections_store.load_mart("mart_matchup_grade")

    assert isinstance(result, pl.DataFrame)
    assert result.is_empty()


def test_load_mart_missing_table_returns_empty(temp_duckdb):
    import duckdb

    # Create the database but not the requested table.
    con = duckdb.connect(str(temp_duckdb))
    con.execute("create schema main_marts")
    con.execute("create table main_marts.some_other_table (x integer)")
    con.close()

    result = projections_store.load_mart("mart_matchup_grade")

    assert isinstance(result, pl.DataFrame)
    assert result.is_empty()


def test_load_projections_missing_parquet_returns_empty(temp_projections_dir):
    # Directory/file does not exist.
    assert not temp_projections_dir.exists()

    result = projections_store.load_projections(2025, 8, "ppr")

    assert isinstance(result, pl.DataFrame)
    assert result.is_empty()


# ---------------------------------------------------------------------------
# write_projections -> load_projections round-trip.
# ---------------------------------------------------------------------------

def test_write_then_load_projections_round_trip(temp_projections_dir):
    df = pl.DataFrame(
        {
            "player_id": ["2307", "4046"],
            "projected_points": [18.4, 6.1],
        }
    )

    projections_store.write_projections(df, 2025, 8, "ppr")

    # File should land in the temp dir with the conventional name.
    expected_path = temp_projections_dir / "2025_wk08_ppr.parquet"
    assert expected_path.exists()

    loaded = projections_store.load_projections(2025, 8, "ppr")

    assert not loaded.is_empty()
    assert loaded.sort("player_id").to_dicts() == df.sort("player_id").to_dicts()


def test_load_projections_distinguishes_by_params(temp_projections_dir):
    df = pl.DataFrame({"player_id": ["2307"], "projected_points": [18.4]})
    projections_store.write_projections(df, 2025, 8, "ppr")

    # Same season/week but different scoring format -> no file -> empty.
    other = projections_store.load_projections(2025, 8, "standard")
    assert other.is_empty()

    # Different week -> empty.
    other_week = projections_store.load_projections(2025, 9, "ppr")
    assert other_week.is_empty()


# ---------------------------------------------------------------------------
# Season filtering (when a season column exists).
# ---------------------------------------------------------------------------

def test_load_mart_filters_by_season(temp_duckdb):
    import duckdb

    con = duckdb.connect(str(temp_duckdb))
    con.execute("create schema main_marts")
    con.execute(
        "create table main_marts.mart_matchup_grade "
        "(season integer, team varchar, pass_matchup double)"
    )
    con.execute(
        "insert into main_marts.mart_matchup_grade values "
        "(2024, 'SF', 1.0), (2025, 'SF', 2.0), (2025, 'SEA', 3.0)"
    )
    con.close()

    all_rows = projections_store.load_mart("mart_matchup_grade")
    assert all_rows.height == 3

    only_2025 = projections_store.load_mart("mart_matchup_grade", season=2025)
    assert only_2025.height == 2
    assert set(only_2025["season"].to_list()) == {2025}


def test_load_mart_without_season_column_ignores_filter(temp_duckdb):
    import duckdb

    con = duckdb.connect(str(temp_duckdb))
    con.execute("create schema main_intermediate")
    con.execute(
        "create table main_intermediate.int_no_season (team varchar, grade double)"
    )
    con.execute("insert into main_intermediate.int_no_season values ('SF', 10.0)")
    con.close()

    # Passing a season is a no-op when the table has no season column.
    result = projections_store.load_mart("int_no_season", season=2025)
    assert result.height == 1
