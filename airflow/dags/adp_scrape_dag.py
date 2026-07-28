"""Daily ADP scrape -> validate -> cross-reference -> write-to-S3 pipeline.

Structure per (source, scoring_format) pair, three formats in parallel:

    scrape_{source}_{format} -> validate_{source}_{format}
        -> cross_reference_{source}_{format} -> write_s3_{source}_{format}

The DAG iterates adp_sources.REGISTERED_SOURCES rather than hardcoding a
source name, so adding a new scraper (one file + one registry entry, see
plugins/adp_sources/__init__.py) requires no changes here.

Paused automatically after ADP_PIPELINE_END_DATE (an Airflow Variable, so it
can be moved without a code deploy) since there are no live drafts during the
NFL season.
"""

import json
from datetime import datetime, timedelta, timezone

import pendulum
from airflow.decorators import dag, task, task_group
from airflow.exceptions import AirflowException
from airflow.models import Variable

from adp_sources import REGISTERED_SOURCES
from adp_sources.sleeper_universe import build_name_position_index
from adp_sources.slack_alerts import notify_slack_on_failure
from src.analytics.adp_service import adp_service

SCORING_FORMATS = ["ppr", "half_ppr", "standard"]

MIN_PLAYERS = 100
MIN_ADP = 1.0
MAX_ADP = 300.0
MAX_MISSING_ADP_FRACTION = 0.2
MIN_MATCH_RATE_WARNING_THRESHOLD = 0.9

default_args = {
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "on_failure_callback": notify_slack_on_failure,
}


def _end_date() -> pendulum.DateTime:
    raw = Variable.get("ADP_PIPELINE_END_DATE", default_var="2026-09-01")
    return pendulum.parse(raw)


@dag(
    dag_id="adp_scrape_dag",
    schedule="0 6 * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    end_date=_end_date(),
    catchup=False,
    default_args=default_args,
    tags=["adp", "scraping"],
)
def adp_scrape_dag():
    for scoring_format in SCORING_FORMATS:

        @task_group(group_id=f"format_group_{scoring_format}")
        def format_group(scoring_format=scoring_format):
            for source in REGISTERED_SOURCES:

                @task_group(group_id=source.source_name)
                def source_group(source=source, scoring_format=scoring_format):
                    task_params = {
                        "scoring_format": scoring_format,
                        "source_name": source.source_name,
                    }

                    @task(task_id=f"scrape_{source.source_name}_{scoring_format}", params=task_params)
                    def scrape():
                        return source.scrape(scoring_format)

                    @task(task_id=f"validate_{source.source_name}_{scoring_format}", params=task_params)
                    def validate(players):
                        if len(players) < MIN_PLAYERS:
                            raise AirflowException(
                                f"Only {len(players)} players scraped for "
                                f"{source.source_name}/{scoring_format}, expected at least {MIN_PLAYERS}"
                            )

                        missing_adp = sum(1 for p in players if p.get("adp") is None)
                        if missing_adp / len(players) > MAX_MISSING_ADP_FRACTION:
                            raise AirflowException(
                                f"{missing_adp}/{len(players)} players missing ADP for "
                                f"{source.source_name}/{scoring_format}, exceeds "
                                f"{MAX_MISSING_ADP_FRACTION:.0%} threshold"
                            )

                        out_of_range = [
                            p for p in players
                            if p.get("adp") is not None and not (MIN_ADP <= p["adp"] <= MAX_ADP)
                        ]
                        if out_of_range:
                            raise AirflowException(
                                f"{len(out_of_range)} players have ADP outside "
                                f"[{MIN_ADP}, {MAX_ADP}] for {source.source_name}/{scoring_format}: "
                                f"{out_of_range[:5]}"
                            )

                        return players

                    @task(task_id=f"cross_reference_{source.source_name}_{scoring_format}", params=task_params)
                    def cross_reference(players):
                        name_position_index = build_name_position_index()

                        matched = []
                        for p in players:
                            key = (adp_service.normalize_player_name(p["name"]), p["position"])
                            if key in name_position_index:
                                matched.append(p)

                        total = len(players)
                        match_rate = len(matched) / total if total else 0.0
                        print(
                            f"Matched {len(matched)}/{total} players "
                            f"({match_rate:.1%}) against Sleeper universe."
                        )

                        if match_rate < MIN_MATCH_RATE_WARNING_THRESHOLD:
                            print(
                                f"WARNING: match rate {match_rate:.1%} for "
                                f"{source.source_name}/{scoring_format} is below "
                                f"{MIN_MATCH_RATE_WARNING_THRESHOLD:.0%} threshold"
                            )

                        return matched

                    @task(task_id=f"write_s3_{source.source_name}_{scoring_format}", params=task_params)
                    def write_s3(players):
                        import boto3

                        bucket = Variable.get("ADP_S3_BUCKET")
                        key = f"adp/{source.source_name}/{scoring_format}/latest.json"
                        body = {
                            "scraped_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "source": source.source_name,
                            "scoring_format": scoring_format,
                            "players": players,
                        }

                        boto3.client("s3").put_object(
                            Bucket=bucket,
                            Key=key,
                            Body=json.dumps(body),
                            ContentType="application/json",
                        )
                        print(f"Wrote {len(players)} players to s3://{bucket}/{key}")

                    write_s3(cross_reference(validate(scrape())))

                source_group()

        format_group()


adp_scrape_dag()
