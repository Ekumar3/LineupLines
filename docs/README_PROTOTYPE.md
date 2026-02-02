Vegas Lines Pipeline — Prototype

Usage
1. Create a Python virtualenv and install deps:
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt

2. Local fetch (no API key required - returns sample data):
   python scripts\run_local.py --sport americanfootball_nfl

3. To use The Odds API, set env var:
   set ODDS_API_KEY=your_key_here

4. To run the Lambda locally with SAM (optional):
   - Install AWS SAM CLI
   - sam build && sam local invoke VegasLinesFunction -e events/sample_event.json

Run a minimal API server (FastAPI)
- Install deps (see requirements.txt)
- Run locally with:
  - python scripts\run_api.py
  - Open http://localhost:8000/docs for the OpenAPI UI

Demo frontend
- Serve the `public/` folder (e.g., `python -m http.server 8080` from project root) and point your browser at http://localhost:8080/index.html

Configuration
- S3_BUCKET: when set, the API/Lambda will attempt to read from S3. Otherwise it reads `data/latest.json` locally.
- ODDS_API_KEY: The Odds API key (optional for local tests)

Next steps
- Add DynamoDB schema for quickly querying latest lines per player
- Implement provenance & schema validations
- Implement EventBridge dead-lettering & retries
