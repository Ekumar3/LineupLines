"""Slack alert on task failure, wired via default_args["on_failure_callback"]."""

from airflow.providers.slack.hooks.slack_webhook import SlackWebhookHook

SLACK_CONN_ID = "slack_adp_alerts"


def notify_slack_on_failure(context: dict) -> None:
    ti = context["task_instance"]
    dag_run = context["dag_run"]

    message = (
        f":red_circle: ADP pipeline task failed\n"
        f"*DAG*: {ti.dag_id}\n"
        f"*Task*: {ti.task_id}\n"
        f"*Scoring format*: {context['params'].get('scoring_format', 'unknown')}\n"
        f"*Execution date*: {dag_run.logical_date}\n"
        f"*Logs*: {ti.log_url}"
    )

    SlackWebhookHook(slack_webhook_conn_id=SLACK_CONN_ID).send(text=message)
