# LineupLines

Fantasy football draft helper that integrates with [Sleeper](https://sleeper.com) for live draft tracking, scrapes [FantasyPros](https://www.fantasypros.com) for ADP data, and provides VOR (Value Over Replacement) analysis to identify value picks in real time.

## Tech Stack

- **Backend**: FastAPI + Python (Pydantic models, uvicorn)
- **Frontend**: React 19 + Vite + Tailwind CSS + React Router v7
- **Data**: Sleeper API integration + FantasyPros ADP scraping + local JSON storage

## Quick Start

```bash
# Backend
pip install -r requirements.txt
python scripts/sync_player_data.py   # Fetch player data
python scripts/run_api.py            # API server on :8000

# Frontend (from frontend/)
npm install
npm run dev                          # Dev server on :3000 (proxies to :8000)
```

### Docker (Local Testing)

```bash
python scripts/sync_player_data.py   # Ensure data/ is populated first
docker build -t draft-helper:latest .
docker run -p 8000:8000 draft-helper:latest
```

## API Docs

Interactive docs at `http://localhost:8000/docs` (Swagger UI) when the server is running.

## Documentation

See [`docs/`](docs/) for detailed documentation:
- [API Reference](docs/API.md) — All 13 endpoints with examples
- [Architecture](docs/ARCHITECTURE.md) — Design decisions and patterns
- [Deployment](docs/DEPLOYMENT.md) — Local dev, Docker, and production setup
- [Testing](docs/TESTING.md) — 88 tests, mocking strategy, test organization
- [Frontend Tech Stack](docs/FRONTEND_TECH_STACK.md) — React components and hooks
