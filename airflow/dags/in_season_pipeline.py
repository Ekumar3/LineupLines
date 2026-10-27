"""Daily in-season NFL data pipeline: ingest -> dbt transform -> projections.

Runs once a day during the NFL regular season (approx weeks 1-18) and drives
the three-layer architecture described in the design doc:

    Ingestion (this DAG)        scripts/ingest_nflverse.py  -> data/raw/*.parquet
    dbt-duckdb transform layer  dbt run                     -> marts (parquet/duckdb)
    Python prediction layer     ProjectionService           -> projection parquet

Task chain (see design.md "Ingestion (Airflow daily)" + the dbt/Python layers):

    bye_week_gate (ShortCircuit) -> ingest_nflverse -> dbt_build -> generate_projections

bye_week_gate is a ShortCircuitOperator: it consults stg_schedules (the raw
schedules parquet via DuckDB) for the target (season, week). If no regular
season games are scheduled — the league-wide bye at season's end, or the DAG
firing off-season before it's paused — the downstream tasks are skipped so we
don't run a pipeline over an empty slate.

Scheduling: a plain daily schedule. Off-season parking is handled two ways —
(1) an end_date Airflow Variable (IN_SEASON_PIPELINE_END_DATE) parks the DAG
after the season the same way adp_scrape_dag does, and (2) the bye_week_gate
short-circuits any individual run that lands on a week with no scheduled games.

Environment:
    MART_S3_BUCKET  — when set, prod mode: dbt reads/writes S3, projections_store
                      persists to S3. When unset, dev mode: everything falls back
                      to the repo-local data/ and dbt/ directories (projections_store
                      already implements that fallback). The DAG only passes the
                      env through; it does not branch on it beyond choosing the
                      dbt target.

This module uses standard Airflow imports at the top. In an environment without
Airflow installed it will not import, but it is a well-formed DAG module and
parses cleanly; the companion test (task 13.2) validates import via DagBag when
Airflow is present.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow import DAG
from airflow.models import Variable
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator, ShortCircuitOperator

logger = logging.getLogger(__name__)

# --- Repo layout ------------------------------------------------------------
# Resolve repo paths from this file so the DAG works both in the Astro image
# (dags/ copied in) and from a local checkout. The repo root is two levels up
# from airflow/dags/.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INGEST_SCRIPT = REPO_ROOT / "scripts" / "ingest_nflverse.py"
DBT_PROJECT_DIR = REPO_ROOT / "dbt"
RAW_DATA_DIR = REPO_ROOT / "data" / "raw"

# Default scoring format projections are generated for on the daily run. The
# projection service is scoring-agnostic; PPR is the canonical daily output and
# other formats can be re-derived on demand by the API layer.
DEFAULT_SCORING_FORMAT = "ppr"


# --- Environment helpers ----------------------------------------------------
def _is_prod() -> bool:
    """Prod when MART_S3_BUCKET is set; dev (local data/) otherwise."""
    return bool(os.environ.get("MART_S3_BUCKET", "").strip())


def _dbt_target() -> str:
    """dbt target: 'prod' reads/writes S3, 'dev' uses the local duckdb file."""
    return "prod" if _is_prod() else "dev"


def _end_date() -> pendulum.DateTime:
    """Park the DAG after the season via an Airflow Variable (no code deploy)."""
    raw = Variable.get("IN_SEASON_PIPELINE_END_DATE", default_var="2027-02-15")
    return pendulum.parse(raw)


# --- Monitoring / alert hooks ----------------------------------------------
def notify_on_failure(context: dict) -> None:
    """on_failure_callback placeholder for critical pipeline failures.

    Wired via default_args so every task in the DAG routes failures here. Logs
    a structured message today; swap the body for a Slack/PagerDuty hook (see
    plugins/adp_sources/slack_alerts.py for the pattern) without touching the
    task graph.
    """
    ti = context.get("task_instance")
    dag_run = context.get("dag_run")
    task_id = getattr(ti, "task_id", "unknown")
    dag_id = getattr(ti, "dag_id", "in_season_pipeline")
    logical_date = getattr(dag_run, "logical_date", None)
    logger.error(
        "IN-SEASON PIPELINE FAILURE | dag=%s task=%s logical_date=%s",
        dag_id,
        task_id,
        logical_date,
    )


def notify_on_success(context: dict) -> None:
    """on_success_callback placeholder for the terminal projections task."""
    ti = context.get("task_instance")
    logger.info(
        "IN-SEASON PIPELINE SUCCESS | task=%s",
        getattr(ti, "task_id", "generate_projections"),
    )


# --- Target (season, week) resolution ---------------------------------------
def _target_season_week(logical_dt: pendulum.DateTime) -> tuple[int, int]:
    """Resolve the (season, week) this run should process.

    Prefers the Sleeper NFL state (authoritative for the live week); falls back
    to a date-derived estimate when SleeperClient is unavailable in the worker
    image. The fallback keeps the gate functional without the src/ vendor.
    """
    try:
        from src.data_sources.sleeper_client import SleeperClient  # type: ignore

        state = SleeperClient().get_nfl_state()
        if state:
            season = int(state.get("season") or logical_dt.year)
            week = int(state.get("week") or state.get("display_week") or 0)
            if week > 0:
                return season, week
    except Exception as exc:  # defensive: never fail the gate on lookup error
        logger.warning("NFL state lookup failed, using date fallback: %s", exc)

    # Date fallback: NFL season is labeled by the year it starts in. Treat
    # Jan/Feb as belonging to the prior season's playoffs.
    season = logical_dt.year if logical_dt.month >= 3 else logical_dt.year - 1
    # Approximate regular-season week from early-September kickoff.
    season_start = pendulum.datetime(season, 9, 4, tz=logical_dt.timezone_name)
    delta_days = (logical_dt - season_start).in_days()
    week = max(1, min(18, delta_days // 7 + 1))
    return season, int(week)


# --- Task callables ---------------------------------------------------------
def bye_week_gate(**context) -> bool:
    """Short-circuit when the target week has no scheduled regular-season games.

    Queries the raw schedules parquet directly via DuckDB (the same files
    stg_schedules reads) so the gate works before dbt has materialized views.
    Returns True to proceed, False to skip the ingest -> dbt -> projections
    chain. Defaults to proceeding if schedules can't be read — a missing
    schedule file is itself a reason to run ingest.
    """
    logical_dt = context["logical_date"]
    season, week = _target_season_week(logical_dt)
    logger.info("Resolved target season=%d week=%d", season, week)
    context["ti"].xcom_push(key="season", value=season)
    context["ti"].xcom_push(key="week", value=week)

    schedules_glob = str(RAW_DATA_DIR / "schedules_*.parquet")
    try:
        import duckdb

        con = duckdb.connect(database=":memory:")
        try:
            row = con.execute(
                """
                select count(*)
                from read_parquet(?)
                where game_type = 'REG' and season = ? and week = ?
                """,
                [schedules_glob, season, week],
            ).fetchone()
        finally:
            con.close()
        games = int(row[0]) if row else 0
    except Exception as exc:
        # No schedules yet (fresh env) or duckdb missing -> let ingest run.
        logger.warning(
            "Could not read schedules for bye-week check (%s); proceeding.", exc
        )
        return True

    if games == 0:
        logger.info(
            "No regular-season games scheduled for season=%d week=%d; skipping run.",
            season,
            week,
        )
        return False

    logger.info("%d games scheduled for season=%d week=%d; proceeding.", games, season, week)
    return True


def generate_projections(**context) -> dict:
    """Generate projections via ProjectionService and persist the parquet.

    Reads the dbt feature mart, projects every modeled player for the target
    (season, week), and writes the projection parquet through projections_store
    (S3 in prod via MART_S3_BUCKET, local data/ in dev). Logs run duration for
    monitoring.
    """
    from src.services.projection_service import ProjectionService  # type: ignore

    try:
        from research.scoring import get_scoring_settings  # type: ignore

        scoring_settings = get_scoring_settings(DEFAULT_SCORING_FORMAT)
    except Exception as exc:
        logger.warning("Falling back to inline PPR scoring (%s)", exc)
        scoring_settings = {
            "passing_yards": 0.04,
            "passing_tds": 4,
            "interceptions": -2,
            "rushing_yards": 0.1,
            "rushing_tds": 6,
            "receptions": 1.0,
            "receiving_yards": 0.1,
            "receiving_tds": 6,
            "fumbles_lost": -2,
        }

    ti = context["ti"]
    season = ti.xcom_pull(key="season", task_ids="bye_week_gate")
    week = ti.xcom_pull(key="week", task_ids="bye_week_gate")
    if season is None or week is None:
        season, week = _target_season_week(context["logical_date"])

    start = time.monotonic()
    service = ProjectionService()
    service.load_marts(int(season))
    projections = service.project_week(int(season), int(week), scoring_settings)
    service.write_output(projections, int(season), int(week), DEFAULT_SCORING_FORMAT)
    duration = time.monotonic() - start

    logger.info(
        "Generated %d projections for season=%s week=%s format=%s in %.1fs",
        len(projections),
        season,
        week,
        DEFAULT_SCORING_FORMAT,
        duration,
    )
    return {
        "season": int(season),
        "week": int(week),
        "scoring_format": DEFAULT_SCORING_FORMAT,
        "projection_count": len(projections),
        "duration_seconds": round(duration, 2),
    }


# --- DAG definition ---------------------------------------------------------
default_args = {
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=60),
    "on_failure_callback": notify_on_failure,
}

# dbt invocation mirrors dbt_project.yml's documented pattern: run from the
# dbt/ dir with --profiles-dir . and the chosen target. In prod the raw parquet
# lives in S3, so override raw_data_path via --vars; in dev the default
# ../data/raw (from dbt_project.yml) is correct.
_DBT_VARS_PROD = (
    ' --vars "{raw_data_path: \'s3://${MART_S3_BUCKET}/raw\'}"'
)
DBT_BUILD_COMMAND = (
    f"cd {DBT_PROJECT_DIR} && "
    f"dbt build --profiles-dir . --target {_dbt_target()}"
    + (_DBT_VARS_PROD if _is_prod() else "")
)

with DAG(
    dag_id="in_season_pipeline",
    description="Daily in-season NFL pipeline: ingest nflverse -> dbt -> projections.",
    schedule="0 9 * * *",  # 09:00 UTC daily during the season
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    end_date=_end_date(),
    catchup=False,
    default_args=default_args,
    tags=["in-season", "nflverse", "dbt", "projections"],
) as dag:

    gate = ShortCircuitOperator(
        task_id="bye_week_gate",
        python_callable=bye_week_gate,
        doc_md="Skip the run when the target week has no scheduled regular-season games.",
    )

    ingest = BashOperator(
        task_id="ingest_nflverse",
        bash_command=(
            f"python {INGEST_SCRIPT} "
            "{{ ti.xcom_pull(key='season', task_ids='bye_week_gate') }} --force"
        ),
        doc_md="Ingest nflverse pbp/player_stats/snap_counts/schedules to data/raw/.",
    )

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=DBT_BUILD_COMMAND,
        env={"MART_S3_BUCKET": os.environ.get("MART_S3_BUCKET", "")},
        append_env=True,
        doc_md="Run dbt staging -> intermediate -> marts transformations.",
    )

    projections = PythonOperator(
        task_id="generate_projections",
        python_callable=generate_projections,
        on_success_callback=notify_on_success,
        doc_md="Project every modeled player for the target week and write parquet.",
    )

    gate >> ingest >> dbt_build >> projections
