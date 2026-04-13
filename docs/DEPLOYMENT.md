# Deployment Guide

Comprehensive guide for running the Draft Helper API locally and deploying to production.

## Table of Contents

1. [Local Development](#local-development)
2. [Running Tests](#running-tests)
3. [Frontend Build & Preview](#frontend-build--preview)
4. [Daily Player Data Sync](#daily-player-data-sync)
5. [Production Deployment](#production-deployment)
6. [Monitoring & Troubleshooting](#monitoring--troubleshooting)

---

## Local Development

### Prerequisites

**System Requirements:**
- Python 3.11+
- pip (Python package manager)
- Git
- 1GB free disk space (for player data)

**Verify Setup:**
```bash
python --version          # Should be 3.11+
pip --version             # Should be 23.0+
git --version             # Should be 2.30+
```

### Installation

#### Step 1: Clone Repository

```bash
git clone <repository-url>
cd LineupLines
```

#### Step 2: Create Virtual Environment

```bash
# On Windows
python -m venv venv
venv\Scripts\activate

# On macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

**Verify activation** (prompt should show `(venv)` prefix):
```bash
which python  # macOS/Linux
# or
where python  # Windows
```

#### Step 3: Install Dependencies

```bash
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

**Verify Installation:**
```bash
python -c "import fastapi; import pytest; import pydantic; print('All dependencies installed')"
```

#### Step 4: Sync Player Data

Before running the API, fetch the player universe:

```bash
python scripts/sync_player_data.py
```

**Expected Output:**
```
INFO:root:Starting player data sync...
INFO:root:Fetching players from Sleeper API...
INFO:root:Fetched 11546 players from Sleeper
INFO:root:Saved 11546 players to data/players/nfl_players.json
INFO:root:Player data sync complete
```

**Verify Data:**
```bash
# Check file was created
ls -lh data/players/nfl_players.json
# Should be ~19MB

# Verify JSON structure
python -c "
import json
with open('data/players/nfl_players.json') as f:
    data = json.load(f)
    print(f'Players: {data[\"player_count\"]}')
    print(f'Updated: {data[\"updated_at\"]}')
"
```

### Running the API Server

#### Start Development Server

```bash
uvicorn src.api.main:app --reload --port 8000
```

**Expected Output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete
```

**Access the API:**
- Main API: http://localhost:8000/
- Interactive Docs: http://localhost:8000/docs
- Alternative Docs: http://localhost:8000/redoc
- OpenAPI Schema: http://localhost:8000/openapi.json

#### Testing the API

```bash
# Health check
curl http://localhost:8000/health

# Expected response:
# {"status":"ok","service":"draft-helper"}
```

### Environment Configuration

**Optional:** Create `.env` file for custom configuration:

```bash
# .env
PYTHONPATH=/path/to/project
LOG_LEVEL=INFO
SLEEPER_API_BASE=https://api.sleeper.app
PLAYER_DATA_DIR=data/players
```

**Load environment variables:**
```bash
# Create .env file
cat > .env << 'EOF'
PYTHONPATH=$(pwd)
LOG_LEVEL=INFO
EOF

# Load (optional - uvicorn reads from environment)
source .env
```

### Frontend

#### Prerequisites

**System Requirements:**
- Node.js 18+
- npm 9+

**Verify Setup:**
```bash
node --version         # Should be 18+
npm --version          # Should be 9+
```

#### Installation

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install
```

**Verify Installation:**
```bash
npm list react react-dom vite
```

#### Start Development Server

```bash
npm run dev
```

**Expected Output:**
```
  VITE v5.0.0  ready in 245 ms

  ➜  Local:   http://localhost:3000/
  ➜  press h to show help
```

**Access the App:**

- Frontend: [http://localhost:3000/](http://localhost:3000/)
- API will proxy `/api` and `/health` requests to the backend at [http://localhost:8000](http://localhost:8000)

**Important:** The backend API server (running on port 8000) must be running for the frontend to work correctly. In another terminal, run:
```bash
python scripts/run_api.py
# or
uvicorn src.api.main:app --reload --port 8000
```

### Running Frontend & Backend Together

To develop with both frontend and backend running simultaneously:

**Terminal 1 (Backend) — From project root:**
```bash
python scripts/run_api.py
# or: uvicorn src.api.main:app --reload --port 8000
```

**Expected output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete
```

**Terminal 2 (Frontend) — From project root:**
```bash
cd frontend
npm run dev
```

**Expected output:**
```
  VITE v5.0.0  ready in 245 ms

  ➜  Local:   http://localhost:3000/
  ➜  press h to show help
```

**Access the application:**

- Open your browser to [http://localhost:3000](http://localhost:3000)

**How it works:**

- The Vite dev server automatically proxies all `/api` and `/health` requests to the backend at port 8000
- Frontend and backend communicate seamlessly without any additional configuration
- Changes to either frontend or backend code trigger hot-reload, so you see updates instantly

---

## Running Tests

### Prerequisites

All tests use `pytest` and `pytest-mock`. Already installed via `requirements.txt`.

### Run All Tests

```bash
# Standard run
pytest tests/ -v

# With coverage report
pytest tests/ --cov=src --cov-report=html

# Run and show slowest tests
pytest tests/ -v --durations=10
```

**Expected Output:**
```
tests/test_api.py::test_health PASSED                                    [  2%]
tests/test_fetcher.py::TestGetUserDrafts::test_get_user_drafts_success PASSED
...
======================== 52 passed in 1.23s ========================
```

### Run Specific Test Files

```bash
# API health check only
pytest tests/test_api.py -v

# SleeperClient unit tests
pytest tests/test_fetcher.py -v

# API endpoint integration tests
pytest tests/test_draft_endpoints.py -v

# Storage layer tests
pytest tests/test_api_storage.py -v
```

### Run Specific Test Classes

```bash
# All user draft tests
pytest tests/test_draft_endpoints.py::TestGetUserDrafts -v

# All available player tests
pytest tests/test_draft_endpoints.py::TestGetAvailablePlayers -v

# All storage tests
pytest tests/test_api_storage.py::TestPlayerUniverseStorage -v
```

### Run Specific Test

```bash
# Single test
pytest tests/test_draft_endpoints.py::TestGetAvailablePlayers::test_get_available_players_success -v

# Run with print statements
pytest tests/test_draft_endpoints.py::test_name -v -s
```

### Frontend Linting

Since the frontend does not have a test framework configured, linting is the primary code quality check.

#### Run ESLint

```bash
cd frontend
npm run lint
```

**Expected Output (with no issues):**
```
No files matching the pattern were found: ""
```

Or if files are checked:
```
✓ All files pass ESLint checks
```

**Fix linting errors automatically:**
```bash
npm run lint -- --fix
```

This will automatically fix formatting and common code issues in all JavaScript/JSX files.

---

## Frontend Build & Preview

### Build for Production

```bash
cd frontend
npm run build
```

**Expected Output:**
```
vite v5.0.0 building for production...
✓ 1234 modules transformed.
dist/index.html                   0.45 kB
dist/assets/index-xxx.css         45.67 kB │ gzip: 7.89 kB
dist/assets/index-yyy.js          123.45 kB │ gzip: 35.67 kB

✓ built in 5.23s
```

The production bundle is now in `frontend/dist/` and ready to be served.

### Preview Production Build Locally

To test the production build before deployment:

```bash
cd frontend
npm run preview
```

**Expected Output:**
```
  ➜  Local:   http://localhost:4173/
```

Visit [http://localhost:4173](http://localhost:4173) to view the production build.

**Note:** The `preview` mode does NOT proxy to the backend API. It serves only the static frontend files. This is useful for testing the UI and build output but won't connect to the backend. For full testing with API integration, use `npm run dev` instead.

### Serving the Production Build with Backend

In production, serve the `dist/` folder as static files alongside the backend API.

#### Option 1: Nginx (Recommended)

Configure Nginx to serve frontend from `dist/` and proxy API requests to the backend:

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    # Serve static frontend files
    location / {
        alias /path/to/LineupLines/frontend/dist/;
        try_files $uri $uri/ /index.html;
    }

    # Proxy API requests to backend
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Proxy health check
    location /health {
        proxy_pass http://127.0.0.1:8000/health;
        access_log off;
    }
}
```

#### Option 2: Quick Testing with Python

For quick local testing without Nginx:

```bash
cd frontend/dist
python -m http.server 4173
```

Then visit [http://localhost:4173](http://localhost:4173). The API calls will fail without a backend running, but you can verify the frontend builds and loads correctly.

#### Option 3: Include in FastAPI

Serve frontend static files directly from FastAPI:

```python
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# In src/api/main.py
app.mount("/", StaticFiles(directory=Path("frontend/dist"), html=True), name="frontend")
```

Then run the API normally:
```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

The frontend will be available at [http://localhost:8000](http://localhost:8000) along with all API endpoints.

---

## Generate Coverage Report

```bash
# Generate HTML coverage report
pytest tests/ --cov=src --cov-report=html

# Open in browser
# macOS:
open htmlcov/index.html

# Linux:
xdg-open htmlcov/index.html

# Windows:
start htmlcov/index.html
```

**Coverage Targets:**
- Overall: >80%
- Critical paths: >90%
- Storage layer: 100% (9/9 tests)

### Continuous Testing During Development

```bash
# Automatically run tests on file changes
pytest-watch tests/ -- -v

# Or use pytest's native option:
pytest tests/ -v --looponfail
```

---

## Daily Player Data Sync

### Manual Sync

For development and testing, manually sync player data:

```bash
python scripts/sync_player_data.py
```

### Automated Sync (Cron Job)

For production, schedule daily sync via cron (Linux/macOS):

#### Setup Cron Job

```bash
# Open cron editor
crontab -e

# Add this line to run daily at 2 AM
0 2 * * * cd /path/to/LineupLines && /path/to/venv/bin/python scripts/sync_player_data.py >> /var/log/draft-helper-sync.log 2>&1

# Verify cron was added
crontab -l
```

**Cron Expression Breakdown:**
```
0       2       *       *       *
│       │       │       │       │
│       │       │       │       └─ Day of week (0-6, 0 = Sunday)
│       │       │       └───────── Month (1-12)
│       │       └───────────────── Day of month (1-31)
│       └───────────────────────── Hour (0-23, 2 = 2 AM UTC)
└───────────────────────────────── Minute (0-59)
```

**Example Cron Schedules:**
```bash
# Daily at 2 AM
0 2 * * * cd /path/to/project && python scripts/sync_player_data.py

# Every 12 hours (2 AM and 2 PM)
0 2,14 * * * cd /path/to/project && python scripts/sync_player_data.py

# Every Sunday at 1 AM (for weekend draft preparation)
0 1 * * 0 cd /path/to/project && python scripts/sync_player_data.py

# Hourly during draft season (August-December)
# Use a wrapper script that checks month before running
0 * 8-12 * * cd /path/to/project && python scripts/sync_player_data.py
```

#### Monitoring Cron Jobs

```bash
# View cron logs (macOS)
log stream --predicate 'process == "cron"'

# View cron logs (Linux)
sudo journalctl -u cron --since "1 hour ago"

# Check log file if redirecting output
tail -f /var/log/draft-helper-sync.log
```

### Windows Task Scheduler (Alternative to Cron)

```powershell
# Create scheduled task to run daily at 2 AM
$trigger = New-ScheduledTaskTrigger -Daily -At 02:00
$action = New-ScheduledTaskAction -Execute "C:\path\to\venv\Scripts\python.exe" `
    -Argument "scripts/sync_player_data.py" `
    -WorkingDirectory "C:\path\to\LineupLines"
Register-ScheduledTask -TaskName "DraftHelperSync" -Trigger $trigger -Action $action -RunLevel Highest
```

---

## Production Deployment

### Pre-Deployment Checklist

- [ ] All 95 tests passing locally (`pytest tests/ -v`)
- [ ] Player data synced within last 24 hours
- [ ] Environment variables configured
- [ ] API docs generated at `/docs`
- [ ] Rate limiting tested (no >1000 req/min)
- [ ] Error handling verified (404, 422, 500 responses)

### Option 1: Self-Hosted (VPS/EC2)

#### System Setup

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install Python and dependencies
sudo apt install -y python3.11 python3-pip python3-venv git

# Create deploy directory
sudo mkdir -p /opt/draft-helper
sudo chown $USER:$USER /opt/draft-helper
cd /opt/draft-helper
```

#### Deploy Application

```bash
# Clone repo
git clone <repository-url> .

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Sync player data
python scripts/sync_player_data.py

# Verify API starts
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 &
```

#### Setup systemd Service

Create `/etc/systemd/system/draft-helper.service`:

```ini
[Unit]
Description=Draft Helper API
After=network.target

[Service]
Type=notify
User=draft-helper
WorkingDirectory=/opt/draft-helper
ExecStart=/opt/draft-helper/venv/bin/uvicorn src.api.main:app \
    --host 0.0.0.0 --port 8000 --workers 4
Restart=on-failure
RestartSec=10

Environment="PATH=/opt/draft-helper/venv/bin"

[Install]
WantedBy=multi-user.target
```

**Enable and Start:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable draft-helper
sudo systemctl start draft-helper

# Check status
sudo systemctl status draft-helper

# View logs
sudo journalctl -u draft-helper -f
```

#### Setup Reverse Proxy (Nginx)

Create `/etc/nginx/sites-available/draft-helper`:

```nginx
server {
    listen 80;
    server_name api.draft-helper.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /health {
        proxy_pass http://127.0.0.1:8000/health;
        access_log off;
    }
}
```

**Enable Site:**
```bash
sudo ln -s /etc/nginx/sites-available/draft-helper /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### Option 2: AWS Deployment (Lambda + API Gateway)

#### Infrastructure Setup

The project includes a SAM (Serverless Application Model) template for AWS deployment.

**Current Template Location:** `infra/template.yaml`

**Deploy to AWS:**
```bash
# Install AWS SAM CLI
pip install aws-sam-cli

# Configure AWS credentials
aws configure

# Build and deploy
sam build
sam deploy --guided

# Follow prompts:
# Stack name: draft-helper
# Region: us-east-1
# Confirm changes before deploy: Y
```

#### Lambda Function Configuration

The SAM template includes:

**DraftHelperAPIFunction:**
- Handler: `src.api.main.handler` (ASGI application)
- Runtime: Python 3.11
- Memory: 512 MB (for Pydantic serialization)
- Timeout: 30 seconds
- Environment: `SLEEPER_API_BASE`, `LOG_LEVEL`

**PlayerSyncFunction (Optional):**
- Schedule: Daily at 2 AM UTC
- Timeout: 120 seconds
- Updates S3 with player data

#### S3 Configuration for Player Data

**Create S3 Bucket:**
```bash
aws s3 mb s3://draft-helper-players-prod --region us-east-1
aws s3api put-bucket-versioning \
    --bucket draft-helper-players-prod \
    --versioning-configuration Status=Enabled
```

**Update Storage Layer for S3:**

Modify `src/api/storage.py` to use S3 fallback:

```python
import boto3

S3_CLIENT = boto3.client('s3')
S3_BUCKET = os.getenv('PLAYER_DATA_BUCKET', 'draft-helper-players-prod')

def load_player_universe() -> Optional[Dict]:
    """Load player data from S3 or local fallback."""
    # Try S3 first
    try:
        response = S3_CLIENT.get_object(Bucket=S3_BUCKET, Key='nfl_players.json')
        data = json.load(response['Body'])
        return data.get('players', {})
    except:
        pass

    # Fallback to local
    if not PLAYER_DATA_FILE.exists():
        return None

    try:
        with open(PLAYER_DATA_FILE, 'r') as f:
            data = json.load(f)
        return data.get('players', {})
    except:
        return None
```

#### CloudWatch Monitoring

**View API Logs:**
```bash
aws logs tail /aws/lambda/DraftHelperAPIFunction --follow

# Search for errors
aws logs filter-log-events \
    --log-group-name /aws/lambda/DraftHelperAPIFunction \
    --filter-pattern "ERROR"
```

**Create Alarms:**
```bash
# High error rate alarm
aws cloudwatch put-metric-alarm \
    --alarm-name draft-helper-errors \
    --alarm-description "Alert on high error rate" \
    --metric-name Errors \
    --namespace AWS/Lambda \
    --statistic Sum \
    --period 300 \
    --threshold 10 \
    --comparison-operator GreaterThanThreshold
```

### Option 3: Docker (Local Testing & Deployment)

A `Dockerfile` is included in the repo root. Key characteristics:
- **Base image**: Python 3.10-slim
- Installs `gcc` and `python3-dev` for C extension compilation (scipy, scikit-learn)
- Copies `src/`, `data/`, and `debug_html/` directories separately (not the whole repo)
- Runs uvicorn on port 8000

> **Important**: The Docker image expects player data in `data/`. Run `python scripts/sync_player_data.py` on your host **before** building so the data directory is populated.

#### Local Testing Workflow

```bash
# 1. Ensure player data exists
python scripts/sync_player_data.py

# 2. Build the image
docker build -t draft-helper:latest .

# 3. Run locally
docker run -p 8000:8000 draft-helper:latest

# 4. Verify it's running
curl http://localhost:8000/health

# 5. Access interactive API docs
# Open http://localhost:8000/docs in your browser
```

#### Push to Registry (Production)

```bash
docker tag draft-helper:latest your-registry/draft-helper:latest
docker push your-registry/draft-helper:latest
```

---

## Monitoring & Troubleshooting

### Common Issues

#### Issue: "Player data file not found"

**Symptom:** API returns `null` for available players

**Solution:**
```bash
# Sync player data
python scripts/sync_player_data.py

# Verify file exists
ls -lh data/players/nfl_players.json

# Check file contents
python -c "import json; print(json.load(open('data/players/nfl_players.json')).keys())"
```

#### Issue: "Connection refused" to Sleeper API

**Symptom:** SleeperClient methods fail with connection error

**Solution:**
```bash
# Check internet connectivity
curl https://api.sleeper.app/v1/players/nfl -I

# Test with verbose output
python -c "
from src.data_sources.sleeper_client import SleeperClient
client = SleeperClient()
print(client.get_players())
" 2>&1 | head -20

# Check rate limiting
# Sleeper API limit: 1000 req/minute
# Current code: 1 req / 5 sec = 12 req/min (safe)
```

#### Issue: Import errors after deployment

**Symptom:** `ModuleNotFoundError: No module named 'src'`

**Solution:**

The `src/` directory requires `__init__.py` files to be recognized as a Python package.
Verify these files exist:
```bash
# These should all exist (can be empty files)
ls src/__init__.py src/api/__init__.py
```

If missing, create them:
```bash
touch src/__init__.py src/api/__init__.py
```

The `scripts/run_api.py` script automatically adds the project root to `sys.path`,
so running via `python scripts/run_api.py` should work from any directory. If running
`uvicorn` directly, ensure you run from the project root:
```bash
cd /path/to/LineupLines
uvicorn src.api.main:app --reload --port 8000
```

#### Issue: Tests fail with "Permission denied"

**Symptom:** `pytest` cannot create temp directories

**Solution:**
```bash
# Check directory permissions
ls -la data/
ls -la tests/

# Fix permissions
chmod 755 data/
chmod 755 tests/

# Or run with sudo (not recommended)
sudo pytest tests/ -v
```

### Performance Tuning

#### API Response Time

**Current baseline:** <100ms for all endpoints

**Optimize if slower:**
```bash
# Profile requests
python -c "
import time
import requests

start = time.time()
response = requests.get('http://localhost:8000/health')
print(f'Response time: {(time.time() - start) * 1000:.2f}ms')
print(f'Status: {response.status_code}')
"

# Test available-players endpoint (slowest)
time curl 'http://localhost:8000/api/v1/drafts/<id>/available-players'
```

**Optimizations:**
1. Increase `PLAYER_DATA_CACHE_HOURS` (currently 24 hours)
2. Use S3 with CloudFront for global distribution
3. Add Redis cache layer for available players
4. Implement pagination for large result sets

#### Memory Usage

**Monitor memory:**
```bash
# macOS
top -p $(pgrep -f uvicorn)

# Linux
ps aux | grep uvicorn
watch -n 1 'ps aux | grep uvicorn'

# Expected: 200-300 MB for API + cached players
```

**Reduce if needed:**
- Use generators for large lists
- Stream responses instead of buffering
- Implement request queuing for peak loads

### Health Checks

**Setup endpoint health monitoring:**

```bash
# Simple health check
curl http://localhost:8000/health

# Expected response:
# {"status":"ok","service":"draft-helper"}

# Add to monitoring service (DataDog, New Relic, etc.)
# HTTP GET http://your-api.com/health
# Check for 200 status code and "ok" status field
```

**Uptime Monitoring Command:**
```bash
# Check API availability
watch -n 60 'curl -s http://localhost:8000/health | jq .status'
```

### Logs and Debugging

**View application logs:**

```bash
# Standard output
uvicorn src.api.main:app --log-level DEBUG

# To file
uvicorn src.api.main:app --log-level DEBUG > api.log 2>&1 &

# Follow logs
tail -f api.log
```

**Debug specific requests:**

```bash
# With verbose HTTP logging
python -c "
import logging
logging.basicConfig(level=logging.DEBUG)
import requests
response = requests.get('http://localhost:8000/api/v1/users/test/drafts')
print(response.json())
"
```

**Check API metrics:**

```bash
# Request count (from logs)
grep "GET /api" api.log | wc -l

# Error rate (4xx, 5xx responses)
grep -E '"4[0-9]{2}|5[0-9]{2}"' api.log | wc -l

# Slowest endpoints
grep "completed_in" api.log | sort -t: -k2 -nr | head -10
```

### Backup and Recovery

**Backup player data:**

```bash
# Backup locally
cp data/players/nfl_players.json data/players/nfl_players.backup.json

# Backup to S3
aws s3 cp data/players/nfl_players.json \
    s3://draft-helper-backup/$(date +%Y-%m-%d).json

# Restore from backup
cp data/players/nfl_players.backup.json data/players/nfl_players.json

# Restore from S3
aws s3 cp s3://draft-helper-backup/2026-02-04.json \
    data/players/nfl_players.json
```

---

## Next Steps

### Phase 2 Preparation

Once Phase 1 deployment is stable:

1. **Integrate FantasyPros ADP Data**
   - Fetch and cache ADP rankings
   - Compare available players to ADP
   - Highlight value picks

2. **Build Draft Board UI**
   - Display draft picks
   - Show available players
   - Real-time updates with WebSocket

3. **Add Recommendations Engine**
   - Position recommendations
   - Archetype matching
   - Scarcity alerts

### Monitoring Dashboard

Consider setting up a monitoring dashboard:

```bash
# AWS CloudWatch Dashboard
aws cloudwatch put-dashboard \
    --dashboard-name DraftHelperDashboard \
    --dashboard-body file://dashboard-config.json
```

### Scaling Considerations

**For 1000+ concurrent users:**

1. Use Lambda with auto-scaling
2. Add CloudFront CDN for player data
3. Implement request queuing
4. Add Redis cache layer for hot data
5. Split into multiple Lambda functions by endpoint

---

## Support

For issues or questions:

1. Check logs: `tail -f api.log`
2. Review docs: `open http://localhost:8000/docs`
3. Run tests: `pytest tests/ -v`
4. Check GitHub Issues: `<repository>/issues`

