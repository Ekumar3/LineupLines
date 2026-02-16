# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LineupLines is a Fantasy Football draft helper with a FastAPI backend and React frontend. It integrates with Sleeper's fantasy football platform and scrapes FantasyPros for ADP (Average Draft Position) data to help users analyze drafts and find value picks.

## Development Commands

### Backend
```bash
# Start API server with hot-reload (port 8000)
python scripts/run_api.py

# Run all tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_draft_endpoints.py -v

# Run a specific test
pytest tests/test_draft_endpoints.py::TestGetUserDrafts::test_get_user_drafts_success -v

# Run tests with coverage
pytest tests/ --cov=src --cov-report=html

# Sync player data from Sleeper API
python scripts/sync_player_data.py

# Fetch ADP data
python scripts/fetch_adp_data.py --format ppr
```

### Frontend
```bash
# From frontend/ directory:
npm run dev      # Dev server on port 3000 (proxies /api and /health to :8000)
npm run build    # Production build
npm run lint     # ESLint
```

### API docs
After starting the backend: http://localhost:8000/docs

## Architecture

**Backend** (`src/`): Python FastAPI with layered architecture:
- `src/api/main.py` - All API endpoints (`/api/v1/...`). Uses a `SleeperClient` singleton.
- `src/api/models.py` - Pydantic models for validation. All IDs normalized to strings.
- `src/api/storage.py` - Player data persistence (local JSON now, designed for S3/DynamoDB migration).
- `src/data_sources/sleeper_client.py` - Sleeper API wrapper with 0.1s rate limiting, 24hr player cache, defensive defaults ("UNKNOWN"/"FA" for None).
- `src/data_sources/fantasypros_client.py` - FantasyPros ADP scraper (BeautifulSoup). Supports PPR/standard/half-PPR.
- `src/analytics/adp_service.py` - ADP caching and lookup coordination.
- `src/analytics/adp_analyzer.py` - Pattern analysis: round patterns, positional tiers, value picks.
- `src/sleeper_pipeline/` - AWS Lambda functions for scheduled data fetching.

**Frontend** (`frontend/`): React 19 + Vite + Tailwind CSS + React Router. Axios for API calls. Vite proxies `/api` and `/health` to the backend on port 8000.

**Data**: Player universe cached in `data/players/nfl_players.json` (~19MB, 11.5K players).

**Infra**: AWS SAM template in `infra/template.yaml` (Lambda + S3 + EventBridge).

### Data Flow
1. User lookup via Sleeper username → `get_user()` → `user_id`
2. Draft retrieval via `user_id` → `get_user_drafts()` → draft summaries
3. Draft picks via `draft_id` → `get_draft_picks()` → enriched with player names from cached player universe
4. Available players = player universe minus drafted players

## ADP Delta Sign Convention (CRITICAL)

- **ADP** = Lower numbers are BETTER (expected to go early in draft)
- **Pick number** = Your draft position

**Positive delta** (picked LATER than ADP) = **GOOD (Green)** - got value
- Example: ADP 15, picked at 20 → delta = +5

**Negative delta** (picked EARLIER than ADP) = **BAD (Red)** - reached
- Example: ADP 25, picked at 15 → delta = -10

### Color Coding:
- Green: delta > 0 (picked later, got value)
- Red: delta < 0 (picked earlier, reached)

This convention applies to ALL frontend display of ADP deltas in the roster view.

## Testing Conventions

- Tests use `pytest` with `unittest.mock.patch`
- API tests use `fastapi.testclient.TestClient`
- Mock `sleeper_client` methods rather than real HTTP calls
- Storage tests use `tmp_path` fixture
- Test structure: class-based with `client` and `mock_data` fixtures, patch at `src.api.main.sleeper_client.<method>`

## Code Patterns

- **Imports**: Absolute from `src` (e.g., `from src.api.models import DraftSummary`)
- **Error handling**: Defensive at data source layer, not in API responses. SleeperClient converts None → "UNKNOWN"/"FA".
- **ID normalization**: All IDs are strings throughout the API.
- **Rate limiting**: SleeperClient enforces 0.1s between requests (Sleeper limit: 1000/min).
