"""DAG structure tests for the in-season Airflow pipeline.

Validates airflow/dags/in_season_pipeline.py:
  - imports cleanly via DagBag with zero import errors
  - exposes dag_id "in_season_pipeline"
  - contains the four expected tasks
  - wires the dependency chain
        bye_week_gate >> ingest_nflverse >> dbt_build >> generate_projections
  - sets retries == 3 with exponential backoff in default_args
  - runs on a daily schedule

Environment note
----------------
Apache Airflow is NOT guaranteed to be installed here. The repository ships a
top-level ``airflow/`` directory, so a bare ``import airflow`` resolves to that
local *namespace* package (``airflow.__file__ is None``) rather than the real
distribution. A plain ``pytest.importorskip("airflow")`` would therefore NOT
skip — it would succeed against the stub and then blow up on
``from airflow.models import DagBag``.

To skip cleanly when real Airflow is absent we probe for a concrete symbol
(``airflow.models.DagBag``) and ``pytest.skip`` the whole module if the import
fails. When real Airflow is installed, every test below runs.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pytest

# --- Skip the whole module unless *real* Apache Airflow is importable --------
# Probe a concrete symbol rather than the namespace package, since the repo's
# own airflow/ directory satisfies a bare `import airflow`.
try:
    from airflow.models import DagBag  # noqa: F401  (import is the probe)
except Exception as exc:  # ModuleNotFoundError, ImportError, etc.
    pytest.skip(
        f"Apache Airflow not installed ({exc!r}); skipping DAG structure tests.",
        allow_module_level=True,
    )

# Absolute path to airflow/dags so DagBag can find in_season_pipeline.py
# regardless of the pytest invocation directory.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DAG_FOLDER = os.path.join(_REPO_ROOT, "airflow", "dags")

DAG_ID = "in_season_pipeline"
EXPECTED_TASK_IDS = [
    "bye_week_gate",
    "ingest_nflverse",
    "dbt_build",
    "generate_projections",
]


@pytest.fixture(scope="module")
def dagbag():
    from airflow.models import DagBag

    return DagBag(dag_folder=_DAG_FOLDER, include_examples=False)


@pytest.fixture(scope="module")
def dag(dagbag):
    loaded = dagbag.get_dag(DAG_ID)
    assert loaded is not None, f"DAG '{DAG_ID}' not found in {_DAG_FOLDER}"
    return loaded


class TestInSeasonPipelineDagStructure:
    def test_no_import_errors(self, dagbag):
        assert not dagbag.import_errors, (
            f"DAG import errors: {dagbag.import_errors}"
        )

    def test_dag_id_present(self, dag):
        assert dag.dag_id == DAG_ID

    def test_expected_tasks_exist(self, dag):
        task_ids = set(dag.task_ids)
        for expected in EXPECTED_TASK_IDS:
            assert expected in task_ids, (
                f"missing task '{expected}'; found {sorted(task_ids)}"
            )

    def test_exactly_four_tasks(self, dag):
        assert len(dag.task_ids) == len(EXPECTED_TASK_IDS), (
            f"expected {len(EXPECTED_TASK_IDS)} tasks, got {sorted(dag.task_ids)}"
        )

    def test_dependency_chain(self, dag):
        """bye_week_gate >> ingest_nflverse >> dbt_build >> generate_projections."""
        gate = dag.get_task("bye_week_gate")
        ingest = dag.get_task("ingest_nflverse")
        dbt_build = dag.get_task("dbt_build")
        projections = dag.get_task("generate_projections")

        # gate is the root: no upstream, ingest downstream
        assert gate.upstream_task_ids == set()
        assert gate.downstream_task_ids == {"ingest_nflverse"}

        # ingest between gate and dbt_build
        assert ingest.upstream_task_ids == {"bye_week_gate"}
        assert ingest.downstream_task_ids == {"dbt_build"}

        # dbt_build between ingest and projections
        assert dbt_build.upstream_task_ids == {"ingest_nflverse"}
        assert dbt_build.downstream_task_ids == {"generate_projections"}

        # projections is the leaf
        assert projections.upstream_task_ids == {"dbt_build"}
        assert projections.downstream_task_ids == set()

    def test_no_cycles(self, dag):
        from airflow.utils.dag_cycle_tester import check_cycle

        check_cycle(dag)  # raises if a cycle exists

    def test_retries_and_exponential_backoff(self, dag):
        default_args = dag.default_args
        assert default_args.get("retries") == 3, (
            f"expected retries == 3, got {default_args.get('retries')}"
        )
        assert default_args.get("retry_exponential_backoff") is True, (
            "expected retry_exponential_backoff to be set/True in default_args"
        )
        # Every task should inherit retries == 3 from default_args.
        for task in dag.tasks:
            assert task.retries == 3, (
                f"task '{task.task_id}' retries == {task.retries}, expected 3"
            )

    def test_retry_delay_is_a_timedelta(self, dag):
        # Exponential backoff is seeded from retry_delay; sanity-check its type.
        retry_delay = dag.default_args.get("retry_delay")
        assert isinstance(retry_delay, timedelta)

    def test_schedule_is_daily(self, dag):
        """Schedule fires once per day. The DAG uses a daily cron ('0 9 * * *')."""
        schedule = getattr(dag, "schedule_interval", None)
        # Newer Airflow exposes `.schedule_interval`; it should be a daily cron
        # or the '@daily' preset. Accept either representation.
        daily_crons = {"0 9 * * *", "@daily"}
        if schedule in daily_crons:
            return
        # Fallback: resolve the timetable's summary / next-run cadence.
        summary = getattr(getattr(dag, "timetable", None), "summary", None)
        assert summary in daily_crons or schedule in daily_crons, (
            f"expected a daily schedule, got schedule={schedule!r} summary={summary!r}"
        )
