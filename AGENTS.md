# AGENTS.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

LineupLines is a Fantasy Football draft helper API that integrates with Sleeper's fantasy football platform. It provides endpoints for tracking live drafts, fetching player data, and analyzing ADP (Average Draft Position) data from FantasyPros.

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
- `sleeper_client.py`: Sleeper Fantasy API client with rate limiting (0.1s between requests), player caching (24hr TTL), and defensive programming (returns "UNKNOWN"/"FA" instead of None for missing data).
- `fantasypros_client.py`: FantasyPros ADP scraper with scoring format support (PPR, standard, half-PPR).

**`src/analytics/`** - Data analysis
- `adp_analyzer.py`: Analyzes ADP data to identify round patterns, positional tiers, and value picks.

**`src/sleeper_pipeline/`** - AWS Lambda pipeline for fetching odds data
- `handler.py`: Lambda entrypoint supporting both game-level odds and season props.

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

- `src/api/main.py` - All API endpoints defined here
- `src/data_sources/sleeper_client.py` - Core Sleeper API integration
- `tests/test_draft_endpoints.py` - Integration tests showing expected behavior
- `docs/ARCHITECTURE.md` - Detailed architecture decisions
- `docs/API.md` - Complete API documentation
