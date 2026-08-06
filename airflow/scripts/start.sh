#!/usr/bin/env bash
set -euo pipefail

# Deliberately NOT set as a container-level env var (i.e. not in the ECS task
# definition): astro-runtime's own /entrypoint script (which already ran and
# exec'd this script) parses AIRFLOW__DATABASE__SQL_ALCHEMY_CONN as a
# host:port URI and blocks in a `nc` wait-loop until it can connect — a
# check built for Postgres/MySQL. A SQLite URI has no host/port, so that
# loop spins forever ("nc: port number invalid") and the container never
# starts. Exporting it here, after the entrypoint has already handed off,
# avoids the loop entirely while Airflow itself still picks it up normally.
export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=sqlite:////usr/local/airflow/db/airflow.db

# SQLite on EFS may not exist yet on first boot, and Fargate tasks are
# replaced on every deploy — `airflow db migrate` is safe to re-run.
airflow db migrate

# Idempotently register the Slack alert connection from SLACK_WEBHOOK_URL
# (a plain Terraform-injected container env var — see infra/terraform/modules/
# airflow/main.tf). Skipped if already present so repeated task restarts
# don't error, and skipped entirely if no webhook URL was configured.
if [ -n "${SLACK_WEBHOOK_URL:-}" ] && ! airflow connections get slack_adp_alerts >/dev/null 2>&1; then
  airflow connections add slack_adp_alerts \
    --conn-type slackwebhook \
    --conn-host "https://hooks.slack.com/services" \
    --conn-password "${SLACK_WEBHOOK_URL#https://hooks.slack.com/services}"
fi

exec airflow scheduler
