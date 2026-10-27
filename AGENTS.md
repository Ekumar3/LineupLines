# AGENTS.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

LineupLines is a Fantasy Football API that integrates with Sleeper's fantasy football platform. It has two halves:

- **Draft helper** (original): endpoints for tracking live drafts, fetching player data, and analyzing ADP (Average Draft Position) data from FantasyPros.
- **In-season matchup recommendations**: start/sit calls, OL/DL matchup grades, and waiver-wire recommendations for a real Sleeper roster. This feature is kept **separate** from the draft helper — every route lives under `/api/v1/in-season/`, services live in `src/services/`, and it is fed by new dbt models. It follows a three-layer architecture: a dbt-duckdb SQL transform layer (nflverse play-by-play → marts), a Python prediction layer (projections + matchup grades + lineup optimization), and the FastAPI serving layer. See `docs/ARCHITECTURE.md` ("In-Season Matchup Recommendations") and `docs/DEPLOYMENT_IN_SEASON.md`.

## Development Commands

### Run the API server
```bash
python scripts/run_api.py
```
This starts the FastAPI server with hot-reload on port 8000.

### Run all tests
```bash
pytest tests/ -v
```

### Run property-based tests
```bash
pytest tests/property_tests/ -v
```
Property-based tests (Hypothesis) live in `tests/property_tests/`. They are
included in a plain `pytest tests/` run and can also be targeted directly.

### Run a specific test file
```bash
pytest tests/test_draft_endpoints.py -v
```

### Run a specific test
```bash
pytest tests/test_draft_endpoints.py::TestGetUserDrafts::test_get_user_drafts_success -v
```

### Sync player data from Sleeper
```bash
python scripts/sync_player_data.py
```

### View API documentation
After starting the server, visit `http://localhost:8000/docs` for Swagger UI.

## Architecture

### Key Modules

**`src/api/`** - FastAPI application
- `main.py`: API endpoints and route handlers. Uses `SleeperClient` singleton for all Sleeper API calls.
- `models.py`: Pydantic models for request/response validation. All IDs are normalized to strings.
- `storage.py`: Abstraction layer for player data persistence (currently local JSON, designed for future S3/DynamoDB migration).

**`src/data_sources/`** - External API integrations
- `sleeper_client.py`: Sleeper Fantasy API client with rate limiting (0.1s between requests), player caching (24hr TTL), and defensive programming (returns "UNKNOWN"/"FA" instead of None for missing data). Extended for in-season with `get_league_rosters`, `get_nfl_state`, `get_league_transactions`, and `get_trending_players`.
- `fantasypros_client.py`: FantasyPros ADP scraper with scoring format support (PPR, standard, half-PPR).
- `projections_store.py`: parquet I/O abstraction for dbt marts and projection output (S3 in prod via `MART_S3_BUCKET`, local `data/` in dev). Degrades gracefully — a missing mart returns an empty DataFrame, never raises.

**`src/services/`** - In-season prediction/modeling layer
- `matchup_grade.py`: serves the OL/DL matchup grade for a `(team, opponent, season, week)` query from `mart_matchup_grade`; returns a neutral default when no row matches.
- `projection_service.py`: production projection pipeline (baseline → deltas → ridge defense factors → expected stat line → scored projection), writing projection parquet.
- `lineup_optimizer.py`: optimal lineup assignment via max-weight bipartite matching (`scipy.optimize.linear_sum_assignment`), excluding bye/OUT/IR players.
- `waiver_service.py`: waiver recommendations — Phase 1 ranks free agents by projected points (augmented with Sleeper trending adds); Phase 2 ranks drop/add pairs by net points gained.

**`src/analytics/`** - Data analysis
- `adp_analyzer.py`: Analyzes ADP data to identify round patterns, positional tiers, and value picks.

**`src/sleeper_pipeline/`** - AWS Lambda pipeline for fetching odds data
- `handler.py`: Lambda entrypoint supporting both game-level odds and season props.

**`dbt/`** - In-season dbt-duckdb transform layer (SQL)
- Intermediate models: `int_team_pass_metrics`, `int_team_run_metrics`, `int_defense_factor_inputs`.
- Marts: `mart_ol_grade`, `mart_dl_grade`, `mart_matchup_grade`, `mart_player_week_features`.
- Transforms raw nflverse parquet (`data/raw/`) into the marts the Python prediction layer reads. dbt never predicts; Python never transforms raw data.

**`airflow/dags/in_season_pipeline.py`** - Daily in-season pipeline DAG
- Chain: `bye_week_gate (ShortCircuit) → ingest_nflverse → dbt_build → generate_projections`. Parks off-season via the `IN_SEASON_PIPELINE_END_DATE` Airflow Variable; short-circuits weeks with no scheduled games.

### Data Flow

1. User lookup via Sleeper username → `get_user()` → returns `user_id`
2. Draft retrieval via `user_id` → `get_user_drafts()` → returns draft summaries
3. Draft picks via `draft_id` → `get_draft_picks()` → enriches with player names from cached player universe
4. Available players = player universe - drafted players

### Storage

Player data stored in `data/players/nfl_players.json`. The storage layer in `src/api/storage.py` is designed as an abstraction to allow future migration to S3/DynamoDB without changing API endpoints.

## Testing Conventions

- All tests use `pytest` with `unittest.mock.patch` for mocking
- API tests use `fastapi.testclient.TestClient`
- Mock Sleeper API responses rather than making real HTTP calls
- Use temporary files (`tmp_path` fixture) for storage tests
- Test file naming: `test_<module>.py`

### Test Structure

```python
class TestEndpointName:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    @pytest.fixture
    def mock_data(self):
        return {...}

    def test_success_case(self, client, mock_data):
        with patch("src.api.main.sleeper_client.method", return_value=mock_data):
            response = client.get("/api/v1/endpoint")
        assert response.status_code == 200
```

## Code Patterns

### Import Style
Use absolute imports from `src`:
```python
from src.api.models import DraftSummary
from src.data_sources.sleeper_client import SleeperClient
```

### Error Handling
Handle None/invalid values at the data source layer, not in API responses. Sleeper API sometimes returns None for player fields - these are converted to "UNKNOWN" or "FA" in `SleeperClient` methods.

### ID Normalization
All IDs (user_ids, roster_ids, draft_ids) are normalized to strings throughout the API for consistency, even though Sleeper's API returns mixed types.

### Rate Limiting
`SleeperClient` enforces 0.1s delay between API requests. Sleeper's limit is 1000 requests/minute.

## Key Files to Understand

- `src/api/main.py` - All API endpoints defined here (draft + in-season under `/api/v1/in-season/`)
- `src/data_sources/sleeper_client.py` - Core Sleeper API integration
- `src/services/` - In-season prediction/modeling services
- `tests/test_draft_endpoints.py` - Integration tests showing expected behavior
- `tests/test_in_season_*.py` - In-season endpoint integration tests
- `tests/property_tests/` - Hypothesis property-based tests
- `docs/ARCHITECTURE.md` - Detailed architecture decisions
- `docs/API.md` - Complete API documentation
- `docs/DEPLOYMENT_IN_SEASON.md` - In-season pipeline deployment (env vars, S3 layout, Airflow)
