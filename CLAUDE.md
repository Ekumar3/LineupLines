# CLAUDE.md

Fantasy Football draft helper — FastAPI backend + React frontend. Integrates with Sleeper and scrapes FantasyPros for ADP data.

## Dev Commands

```bash
# Backend
python scripts/run_api.py          # API server :8000 (hot-reload)
pytest tests/ -v                   # Run tests
pytest tests/ --cov=src            # Tests with coverage

# Frontend (from frontend/)
npm run dev                        # Dev server :3000 (proxies to :8000)
npm run build
```

## ADP Delta Sign Convention (CRITICAL)

- **Positive delta** = picked LATER than ADP = **value (green)**
- **Negative delta** = picked EARLIER than ADP = **reach (red)**
- Example: ADP 15, picked at 20 → delta +5 (good). ADP 25, picked at 15 → delta -10 (bad).

## Code Patterns

- **Imports**: Absolute from `src` — `from src.api.models import DraftSummary`
- **IDs**: Always strings throughout the API
- **Testing**: Mock `sleeper_client` methods — patch at `src.api.main.sleeper_client.<method>`
- **Rate limiting**: SleeperClient enforces 0.1s between requests

## On Push: Doc Review

Before `git push`, check if docs need updating:
1. API changes → update `docs/API.md`
2. Model changes → update `docs/ARCHITECTURE.md`
3. Test count changes → update `docs/TESTING.md` and `docs/DEPLOYMENT.md`
4. Major feature → add to `docs/PHASE_1_COMPLETE.md`

Skip cosmetic diffs — only update for substantive changes.
