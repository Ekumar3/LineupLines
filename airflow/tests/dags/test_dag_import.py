"""Astro's standard DAG-integrity test: every DAG must import cleanly, have
no import errors, and contain no cycles."""

import os

import pytest
from airflow.models import DagBag


@pytest.fixture(scope="module")
def dagbag():
    return DagBag(dag_folder=os.path.join(os.path.dirname(__file__), "..", "..", "dags"), include_examples=False)


def test_no_import_errors(dagbag):
    assert not dagbag.import_errors, f"DAG import errors: {dagbag.import_errors}"


def test_adp_scrape_dag_loaded(dagbag):
    dag = dagbag.get_dag("adp_scrape_dag")
    assert dag is not None
    assert not dag.test_cycle()


def test_adp_scrape_dag_has_one_group_per_format_and_source():
    from adp_sources import REGISTERED_SOURCES

    from dags.adp_scrape_dag import adp_scrape_dag, RANKING_KEYS

    dag = adp_scrape_dag()
    task_ids = set(dag.task_ids)

    for ranking_key in RANKING_KEYS:
        for source in REGISTERED_SOURCES:
            prefix = f"format_group_{ranking_key}.{source.source_name}"
            for step in ("scrape", "validate", "cross_reference", "write_s3"):
                expected = f"{prefix}.{step}_{source.source_name}_{ranking_key}"
                assert expected in task_ids, f"missing task {expected}"
