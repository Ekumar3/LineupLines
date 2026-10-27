# In-Season Deployment Guide

Deployment and operation guide for the in-season half of LineupLines: the daily
nflverse → dbt → projections pipeline and the `/api/v1/in-season/` endpoints.

This complements the base [`DEPLOYMENT.md`](DEPLOYMENT.md) (API + frontend) and
[`AWS_DEPLOYMENT.md`](AWS_DEPLOYMENT.md). For the architecture behind the three
layers, see the "In-Season Matchup Recommendations" section of
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## Table of Contents

1. [How the layers fit together](#how-the-layers-fit-together)
2. [Environment variables](#environment-variables)
3. [S3 bucket layout](#s3-bucket-layout)
4. [Airflow deployment](#airflow-deployment)
5. [Daily pipeline operation](#daily-pipeline-operation)
6. [Deployment checklist](#deployment-checklist)

---

## How the layers fit together

```
Layer 0  Ingestion    scripts/ingest_nflverse.py   -> data/raw/*.parquet
Layer 1  dbt transform dbt build                    -> marts (parquet / duckdb)
Layer 2  Prediction    ProjectionService            -> projection parquet
Layer 3  Serving       FastAPI /api/v1/in-season/   -> JSON responses
```

Layers 0–2 run once a day as the `in_season_pipeline` Airflow DAG. Layer 3 is
the same FastAPI app documented in `DEPLOYMENT.md`; the in-season endpoints read
the projection parquet that the pipeline writes.

The handoff between dbt and Python is the mart parquet, abstracted by
`src/data_sources/projections_store.py`:

- **prod** (env `MART_S3_BUCKET` set): dbt reads/writes S3, projections persist to S3
- **dev** (env unset): everything falls back to the repo-local `data/` and `dbt/` dirs

---

## Environment variables

| Variable | Scope | Required | Description |
|----------|-------|----------|-------------|
| `MART_S3_BUCKET` | API + Airflow | prod only | S3 bucket holding dbt marts, projection output, and raw parquet. **When set, the app runs in prod mode** (S3 I/O). When unset, it runs in dev mode against the local `data/` directory. |
| `DUCKDB_PATH` | dbt + Airflow | optional | Path to the DuckDB database file dbt materializes into (dev target). Defaults to the dbt project's configured path when unset. |
| `IN_SEASON_PIPELINE_END_DATE` | Airflow Variable | optional | Date after which the DAG is parked for the off-season (default `2027-02-15`). This is an **Airflow Variable**, not an OS env var — set it in the Airflow UI/CLI so you can re-arm the DAG for next season without a code deploy. |

Dev vs prod is decided solely by whether `MART_S3_BUCKET` is set — there is no
separate `ENV` flag. This keeps local runs zero-config: clone, run the pipeline,
and everything lands in `data/`.

The in-season endpoints inherit the base API environment (CORS, rate limiting,
etc.) from `DEPLOYMENT.md` — no additional API env vars are required beyond
`MART_S3_BUCKET` in prod.

---

## S3 bucket layout

In prod, a single bucket (`$MART_S3_BUCKET`) holds all three in-season data
tiers under stable prefixes:

```
s3://$MART_S3_BUCKET/
├── raw/                         # Layer 0 output (ingested nflverse parquet)
│   ├── pbp_<season>.parquet
│   ├── player_stats_<season>.parquet
│   ├── snap_counts_<season>.parquet
│   └── schedules_<season>.parquet
├── marts/                       # Layer 1 output (dbt marts)
│   ├── mart_ol_grade.parquet
│   ├── mart_dl_grade.parquet
│   ├── mart_matchup_grade.parquet
│   └── mart_player_week_features.parquet
└── projections/                 # Layer 2 output (projection service)
    └── projections_<season>_wk<week>_<scoring_format>.parquet
```

- `dbt build` in prod overrides `raw_data_path` to `s3://$MART_S3_BUCKET/raw`
  (see the DAG's `--vars`), and writes marts under `marts/`.
- `projections_store.write_projections()` persists the projection parquet under
  `projections/`.
- The API's `projections_store.load_*` helpers resolve the same prefixes, with a
  graceful empty-DataFrame fallback when a key is missing (so a not-yet-run week
  surfaces as a 503 at the endpoint, not a crash).

In dev these same tiers map to the repo-local `data/raw/`, `dbt/target/`, and
`data/projections/` directories.

---

## Airflow deployment

The DAG is `airflow/dags/in_season_pipeline.py`. Its task chain:

```
bye_week_gate (ShortCircuit) → ingest_nflverse → dbt_build → generate_projections
```

Deploy it the same way as the existing `adp_scrape_dag` (see `airflow/README.md`):

1. **Ship the DAG + vendored `src/`.** The worker image needs `src/` importable
   (`projection_service`, `projections_store`, `sleeper_client`) and the `dbt/`
   project. `airflow/scripts/vendor_src.py` is the existing pattern for vendoring
   repo code into the image.
2. **Install dependencies.** `airflow/requirements.txt` must cover
   `dbt-duckdb`, `duckdb`, `polars`, `scipy`, and `nflreadpy` (the ingest + dbt +
   projection stack).
3. **Set `MART_S3_BUCKET`** on the Airflow workers for prod mode. Leave it unset
   for a local/dev Airflow that reads and writes the repo's `data/` directory.
4. **Set the `IN_SEASON_PIPELINE_END_DATE` Variable** in Airflow to park the DAG
   after the season:
   ```bash
   airflow variables set IN_SEASON_PIPELINE_END_DATE 2027-02-15
   ```
   Re-arm it for the next season by updating the Variable — no code deploy needed.
5. **Confirm the schedule.** The DAG runs daily at `09:00 UTC` with
   `catchup=False`. Failures route to `notify_on_failure` (wire this to
   Slack/PagerDuty via the `plugins/adp_sources/slack_alerts.py` pattern); the
   terminal projections task routes to `notify_on_success`.

---

## Daily pipeline operation

Each run walks the three layers in order:

1. **`bye_week_gate`** — resolves the target `(season, week)` from Sleeper's NFL
   state (date-derived fallback if Sleeper is unavailable), then checks the raw
   schedules parquet for scheduled `REG` games that week. If none are scheduled
   (the league-wide bye at season's end, or an off-season run before the DAG is
   parked), it **short-circuits** and skips the rest of the run. A missing
   schedule file is treated as "proceed" so a fresh environment still ingests.
2. **`ingest_nflverse`** — `scripts/ingest_nflverse.py <season> --force` pulls
   pbp / player_stats / snap_counts / schedules into `data/raw/` (or S3 `raw/`).
3. **`dbt_build`** — runs staging → intermediate → marts. In prod it targets
   `prod` and overrides `raw_data_path` to the S3 `raw/` prefix; in dev it targets
   `dev` against the local DuckDB file.
4. **`generate_projections`** — `ProjectionService` reads the feature mart,
   projects every modeled player for the target week (default scoring: PPR), and
   writes the projection parquet via `projections_store`. Run duration is logged
   for monitoring. The same step can be run manually for local testing via
   `python scripts/generate_projections.py <season> <week> [--scoring ppr|half_ppr|standard]`,
   which writes the projection parquet to `data/projections/` (dev) exactly like the DAG.

**Bye-week gating** means you can leave the DAG on a plain daily schedule without
worrying about empty-slate runs: individual weeks with no games self-skip, and
the `IN_SEASON_PIPELINE_END_DATE` Variable parks the DAG for the off-season.

Projections are generated for PPR on the daily run; the projection service is
scoring-agnostic, and the API re-derives other formats on demand from the
league's settings. Until a week's projection parquet exists, the
`/recommendations`, `/waiver`, and `/drop-add` endpoints return **503**; the
`/rosters` and `/roster` endpoints still respond, with `projected_points` and
`matchup_grade` as `null`.

---

## Deployment checklist

Run these final validation steps in the deployment environment — they require a
live Airflow worker, S3 access, and a real Sleeper league, so they are **not**
part of the local test suite.

- [ ] `MART_S3_BUCKET` set on API + Airflow workers (prod); unset for dev.
- [ ] `IN_SEASON_PIPELINE_END_DATE` Airflow Variable set to park the DAG after the season.
- [ ] Worker image has `src/` + `dbt/` vendored and `airflow/requirements.txt` installed.
- [ ] DAG parses cleanly in the target Airflow (`airflow dags list` shows `in_season_pipeline`).
- [ ] S3 bucket has `raw/`, `marts/`, and `projections/` prefixes writable by the pipeline role.
- [ ] Trigger one manual DAG run on an in-season date; confirm `bye_week_gate` proceeds and all four tasks succeed.
- [ ] Confirm the projection parquet lands under `projections/` for the target week.
- [ ] Smoke-test each in-season endpoint against a real Sleeper `league_id`:
  - [ ] `GET /api/v1/in-season/{league_id}/rosters` → 200 with enriched players
  - [ ] `GET /api/v1/in-season/{league_id}/{user_id}/roster` → 200
  - [ ] `GET /api/v1/in-season/{league_id}/{user_id}/recommendations` → 200 (503 before projections exist)
  - [ ] `GET /api/v1/in-season/{league_id}/waiver` → 200
  - [ ] `GET /api/v1/in-season/{league_id}/{user_id}/drop-add` → 200
- [ ] Verify 404 semantics with a bogus `league_id` and a `user_id` not in the league.
- [ ] Review the daily run's failure/success alert routing (Slack/PagerDuty hook wired).
- [ ] Run a security review of S3/IAM scoping (pipeline role limited to the bucket + required prefixes).
