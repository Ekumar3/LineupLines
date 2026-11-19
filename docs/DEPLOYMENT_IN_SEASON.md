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
6. [Local testing workflow](#local-testing-workflow)
7. [Deployment checklist](#deployment-checklist)

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
| `ODDS_API_KEY` | `scripts/refresh_odds.py` | optional | The Odds API key for refreshing live Vegas lines (free tier at [the-odds-api.com](https://the-odds-api.com), 500 req/month). Put it in a gitignored `.env` at the repo root. Only needed if you run `refresh_odds.py`; without fresh odds the projection falls back to the nflverse schedule lines. |

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

- The API's `projections_store.load_*` helpers resolve the same prefixes, with a
  graceful empty-DataFrame fallback when a key is missing (so a not-yet-run week
  surfaces as a 503 at the endpoint, not a crash).

In dev these same tiers map to the repo-local `data/raw/`, `dbt/target/`, and
`data/projections/` directories.

> **What actually writes to S3 today.** Only `scripts/publish_to_s3.py` does (see
> "Publishing to production" below). The earlier design where `dbt build` wrote
> marts to S3 and the ingest step wrote `raw/` was never implemented: the `prod`
> dbt target runs in memory and exports nothing, and `ingest_nflverse.py` writes
> local files only. The API needs just three prefixes: `marts/mart_matchup_grade`,
> `projections/`, and `odds/`. `raw/` is unused for now.

---

## Publishing to production (the hosted API)

The hosted API container has no dbt, DuckDB file, or nflverse data. It reads S3
whenever `MART_S3_BUCKET` is set (Terraform sets it on the ECS task), so the
data has to be built somewhere else and uploaded. `scripts/publish_to_s3.py`
does that from a machine that has the full local stack:

```bash
# See what would be uploaded (nothing is sent)
.venv/Scripts/python.exe scripts/publish_to_s3.py --bucket lineuplines-player-data-prod --dry-run

# Bring the week's data fully up to date, then upload it
aws sso login            # or refresh your AWS credentials
.venv/Scripts/python.exe scripts/publish_to_s3.py --bucket lineuplines-player-data-prod --refresh
```

It uploads, in this order: `marts/mart_matchup_grade.parquet`, the week's
`odds/` file, then `projections/` for `ppr`, `half_ppr` and `standard`. The
projections go last because the frontend reloads a lineup when the projection
timestamp changes, and by then the mart it depends on is already in place.
Nothing is uploaded if a piece is missing, and each object is verified by size
afterwards. The bucket has versioning, so a bad publish can be rolled back.

The bucket comes from `--bucket` or `PUBLISH_S3_BUCKET`, deliberately not from
`MART_S3_BUCKET`: that variable puts the app's own readers into S3 mode, and the
publisher must read its inputs from local disk.

The hosted API also re-downloads Sleeper's player list every 12 hours
(`PLAYER_UNIVERSE_REFRESH_HOURS`), because the image only bakes in the copy that
existed at build time.

One-time setup, then each week (or after the data changes):

1. `terraform apply` so the API task gets `MART_S3_BUCKET` and
   `PLAYER_UNIVERSE_REFRESH_HOURS`; bring the service up
   (`aws ecs update-service --cluster lineuplines --service lineuplines-api --desired-count 1`).
2. Run the publish command above. Until it has run once, the API answers
   recommendation requests with a 503 and the page shows "Preparing this week's
   projections".

Run it before the week's first kickoff to include fresh Vegas lines: once a game
starts it leaves the Odds API feed. Automating this is the next step (a scheduled
task that runs the same script).

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

## Local testing workflow

In production the Airflow DAG keeps all of this current automatically. Locally
(no AWS, no Airflow) you run the same four layers by hand with a set of helper
scripts under `scripts/`. This section is the end-to-end recipe plus the
sequencing gotchas that will otherwise bite you.

### One-time setup

```bash
# 1. Create and activate the virtualenv (Python 3.10), install deps.
python -m venv .venv
.venv\Scripts\Activate.ps1          # PowerShell  (or: source .venv/Scripts/activate in bash)
pip install -r requirements.txt

# 2. (Optional) live Vegas lines: get a free key at the-odds-api.com,
#    then add it to a gitignored .env at the repo root.
echo ODDS_API_KEY=your_key_here >> .env
```

`dbt` is installed into the venv, so once the venv is active a bare `dbt`
command works; otherwise invoke it as `python -m dbt.cli.main ...`.

### The scripts and what each produces

| Script | Layer | Produces |
|--------|-------|----------|
| `scripts/ingest_nflverse.py <season>` | 0 — ingest | `data/raw/*.parquet` (pbp, player_stats, snap_counts, schedules). Absent-only: skips files that exist unless `--force`. |
| `dbt build --profiles-dir . --target dev` (run from `dbt/`) | 1 — transform | marts in `dbt/lineuplines.duckdb` |
| `scripts/refresh_odds.py <season> [week]` | 1.5 — live lines | `data/odds/implied_totals_<season>_wk<NN>.parquet` (overrides stale schedule lines) |
| `scripts/generate_projections.py <season> <week>` | 2 — predict | `data/projections/<season>_wk<NN>_<fmt>.parquet` |
| `scripts/run_api.py` | 3 — serve | the FastAPI app on `:8000` |
| `scripts/recommend.py --username <name>` | client | a start/sit table (calls the running API) |

### The full flow for a given week

Run these in order. Each layer feeds the next, so order matters:

```bash
# 0. Ingest raw nflverse data (once per season; re-run with --force weekly to
#    pull newly-played games).
python scripts/ingest_nflverse.py 2026

# 1. Build the dbt marts from the raw data.
cd dbt && dbt build --profiles-dir . --target dev && cd ..

# 1.5. Refresh live Vegas lines — run this BEFORE the week's first kickoff
#      (free tier has no historical odds; once games start they drop out).
python scripts/refresh_odds.py 2026 8

# 2. Generate the week's projections (bakes in the marts + fresh odds).
python scripts/generate_projections.py 2026 8

# 3. Serve the API (leave running in its own terminal).
python scripts/run_api.py

# 4. Get your start/sit table (in another terminal).
python scripts/recommend.py --username YOUR_SLEEPER_NAME
```

Or let `recommend.py` run the pipeline for you (absent-only, with cascade
invalidation) in a single command:

```bash
python scripts/recommend.py --username YOUR_SLEEPER_NAME --load-current
```

### Sequencing gotchas (read this)

- **`refresh_odds.py` must run before `generate_projections.py`.** The odds
  script updates an *input* (`data/odds/`); the projection is only recomputed
  when you run `generate_projections` (or `recommend.py --load-current`).
  Refreshing odds does **not** retroactively change a projection parquet that
  was already written — regenerate after refreshing.

- **`refresh_odds.py` only works before kickoff.** The free Odds API tier serves
  upcoming/live games only — no historical odds. Once a game starts it leaves
  the feed, so you can't backfill a week whose games have begun. It labels each
  game with its true week from the schedule, so the upcoming slate (which can
  span two weeks) is split into the correct per-week files; `week` is an
  optional filter. (A paid tier would add historical odds — see the script's
  module docstring.)

- **`--load-current` runs the whole chain, in order.** (1) Raw nflverse data is
  re-pulled when absent or when the schedule lists finished games the pbp file
  lacks (a 3-hour cooldown avoids re-pulling before nflverse publishes). (2) The
  marts are rebuilt if raw changed. (3) Vegas lines are fetched from The Odds
  API, best-effort: with no `ODDS_API_KEY`, no quota, or no upcoming games it
  logs a warning and the projection uses the nflverse schedule lines. A file
  fetched under 6 hours ago is not re-fetched, which saves quota. (4) The
  projection is regenerated if absent, if the marts changed, or if the odds file
  is newer than it. Run it before the week's first kickoff for fresh odds.
  `refresh_odds.py` keeps earlier rows for games that have already left the feed,
  so a late run never discards lines you already have. (In production the
  Airflow DAG owns freshness; it does not fetch odds.)

- **The API reads the same local files.** `run_api.py` and the generation
  scripts all resolve `data/` and `dbt/lineuplines.duckdb` relative to the repo
  root, so run everything from the repo root (the scripts `os.chdir` there
  anyway). If you regenerate projections while the API is running, the API picks
  up the new parquet on the next request — no restart needed.

- **Bye weeks and missing projections.** Players on a bye (their team has no
  scheduled game that week) are labeled `SIT (BYE)` and excluded from the
  optimal lineup. If a week's projection parquet is missing, the
  `/recommendations`, `/waiver`, and `/drop-add` endpoints return **503** — run
  `generate_projections.py` (or `--load-current`) first.

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

## Lineup page (frontend) with automatic local updates

The React app has an in-season page at `/lineup/:leagueId/:userId`. The Home page
lists every league whose draft is complete under **Your Leagues**; clicking one
opens that league's start/sit lineup for the current week.

Run it locally in two terminals (from the repo root):

```bash
# 1. API + background data refresh. Use the project venv (it has uvicorn/dbt).
.venv/Scripts/python.exe scripts/dev_server.py        # add --no-refresh for API only

# 2. Frontend (http://localhost:3000, proxies /api to :8000)
cd frontend && npm ci && npm run dev
```

`dev_server.py` runs the API and, every 30 minutes (`--interval-min`), a refresh
cycle for the current week across `ppr`, `half_ppr` and `standard`
(`--formats` to change): it refreshes the stored Sleeper player list when it is
over 24 hours old, re-pulls nflverse data when finished games are missing,
rebuilds the marts, fetches Vegas lines (best-effort) and regenerates stale
projections. Stages that are already current skip themselves, so most cycles do
nothing.

The page polls `GET /api/v1/in-season/{league_id}/status` every minute and
whenever the tab regains focus. When the projection or odds timestamp changes it
reloads the lineup in the background. If projections aren't ready yet it shows a
"preparing" state and keeps retrying.

Notes:

- **Stop the server with Ctrl+C in its own terminal.** Killing only the parent
  process can leave the reloaded API worker holding port 8000.
- **K and DEF have no projection** (the model covers QB/RB/WR/TE), so the
  "Projected" total excludes them and the matchup chip is hidden for them.
- **Not used in production yet.** The deployed container ships only `src/` and
  `data/`, so it cannot run this refresh. In production the Airflow DAG must own
  it. Still to do before deploying: add an odds step and all three scoring formats
  to `airflow/dags/in_season_pipeline.py`, schedule it more than once a day, and
  refresh `data/players/nfl_players.json` (it is baked into the image, so rookies
  and trades go stale until the image is rebuilt).

### Hover breakdown on the lineup page

Hovering (or tapping, on a phone) a player's matchup chip or projected points
opens a card explaining both. It reads the same projection parquet, which now
also stores how each number was built:

| Column | Meaning |
|---|---|
| `baseline_points` | recent form alone (last-3-game average, scored) |
| `defense_adjusted_points` | after the opponent's pass/run defense factors |
| `env_multiplier` | Vegas game-environment multiplier (x0.75 to x1.25) |
| `implied_team_total`, `trailing_implied_total` | Vegas points for the team this week, and its usual figure |
| `points_<stat>` | fantasy points each projected stat contributes |

`projected_points = defense_adjusted_points * env_multiplier`, and the
`points_<stat>` columns sum to `projected_points`. The recommendations endpoint
returns this as `projection_detail` on each player (none for K/DEF or bye weeks).
Projection files written before these columns existed still load; the card then
shows only what the file has, so regenerate a week
(`scripts/generate_projections.py <season> <week> --scoring <fmt>`) to fill it in.

The **matchup label** (Favorable/Neutral/Tough) comes from the OL-vs-DL grades in
`mart_matchup_grade` and is informational. It is not an input to the projection,
which uses the defense factors and the Vegas multiplier above.
