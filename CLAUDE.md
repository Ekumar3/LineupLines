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

**Key File Ownership**:
- `src/api/main.py` - All API endpoints. Uses `SleeperClient` singleton.
- `src/api/models.py` - Pydantic models for validation + OpenAPI docs. All IDs are strings.
- `src/data_sources/sleeper_client.py` - Sleeper API wrapper, rate limiting, player caching.
- `src/api/storage.py` - Player data persistence layer.

**Full architectural details**: See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (layers, testing strategy, scaling path)

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

- Mock `sleeper_client` methods rather than real HTTP calls — patch at `src.api.main.sleeper_client.<method>`
- API tests use `fastapi.testclient.TestClient`

**Full testing guide**: See [docs/TESTING.md](docs/TESTING.md) (test organization, patterns, coverage)

## Code Patterns

- **Imports**: Absolute from `src` (e.g., `from src.api.models import DraftSummary`)
- **Error handling**: Defensive at data source layer, not in API responses. SleeperClient converts None → "UNKNOWN"/"FA".
- **ID normalization**: All IDs are strings throughout the API.
- **Rate limiting**: SleeperClient enforces 0.1s between requests (Sleeper limit: 1000/min).

## On Push: Documentation Review

Before every `git push`, spend 2-3 minutes reviewing documentation for staleness:

1. **API Changes**: If you added/modified endpoints → update `docs/API.md` with endpoint signature, response schema, and examples
2. **Model Changes**: If you modified Pydantic models → update model count in `docs/ARCHITECTURE.md`
3. **Test Changes**: If tests grew significantly → run `pytest --collect-only -q | tail -1` and update counts in `docs/TESTING.md` and `docs/DEPLOYMENT.md`
4. **Feature Completion**: If you completed a major feature → add entry to `docs/PHASE_1_COMPLETE.md` (e.g., "Phase 1.8: Feature Name")
5. **Code Fixes**: If you fixed a bug in models.py or main.py → check if docstrings/comments in that code match CLAUDE.md conventions

**Only update if there are noticeable changes** — skip cosmetic diffs, comment tweaks, or one-line fixes. Focus on substantive API/feature changes that affect future developers' understanding.

**Goal**: Keep docs in sync so future Claude sessions inherit accurate context.
