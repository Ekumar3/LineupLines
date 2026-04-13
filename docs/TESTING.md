# Testing Strategy

Comprehensive guide to running, writing, and maintaining tests for the Draft Helper API.

## Test Overview

**Current Coverage**: 88 tests across 7 files

### Test Distribution

```
tests/test_adp_service.py             (13 tests)  - ADP service unit tests
tests/test_api.py                      (1 test)   - Health check
tests/test_api_storage.py              (9 tests)  - Storage layer unit tests
tests/test_available_by_position.py    (9 tests)  - Available-by-position endpoint tests
tests/test_draft_endpoints.py         (38 tests)  - API endpoint integration tests
tests/test_fetcher.py                 (10 tests)  - SleeperClient unit tests
tests/test_league_settings.py          (8 tests)  - League settings endpoint tests
───────────────────────────────────────────────────
Total:                                88 tests
```

### Test Types

| Type | Count | Purpose | Tools |
|------|-------|---------|-------|
| Unit | 33 | Test individual functions | pytest + mocks |
| Integration | 46 | Test API endpoints | TestClient |
| Storage | 9 | Test persistence | Temp files |
| **Total** | **88** | **Verify all layers** | pytest |

### Coverage Gaps

- VOR endpoints (`/api/v1/draft/{draft_id}/vor`, `/api/v1/draft/{draft_id}/player/{player_id}/vor`) do not have dedicated tests yet

---

## Running Tests

### Run All Tests

```bash
pytest tests/ -v
```

Output:
```
tests/test_api.py::test_health PASSED
tests/test_api_storage.py::TestPlayerUniverseStorage::test_save_and_load_player_universe PASSED
...
======================== 88 passed in 1.23s ========================
```

### Run Specific Test File

```bash
# Run only draft endpoint tests
pytest tests/test_draft_endpoints.py -v

# Run only storage tests
pytest tests/test_api_storage.py -v

# Run only SleeperClient tests
pytest tests/test_fetcher.py -v
```

### Run Specific Test Class

```bash
# Run TestGetUserDrafts class
pytest tests/test_draft_endpoints.py::TestGetUserDrafts -v

# Run TestGetAvailablePlayers class
pytest tests/test_draft_endpoints.py::TestGetAvailablePlayers -v
```

### Run Specific Test

```bash
# Run one test
pytest tests/test_draft_endpoints.py::TestGetUserDrafts::test_get_user_drafts_success -v
```

### Test Coverage Report

```bash
# Install coverage tool
pip install pytest-cov

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Open coverage report
open htmlcov/index.html
```

---

## Test Organization

### tests/test_api.py - API Health Check

```python
def test_health():
    """Test health check endpoint."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "draft-helper"}
```

**Purpose**: Verify API starts and responds.

### tests/test_fetcher.py - SleeperClient Unit Tests

10 tests covering:

```
TestGetUserDrafts:
  ✓ test_get_user_drafts_success
  ✓ test_get_user_drafts_empty
  ✓ test_get_user_drafts_api_error
  ✓ test_get_user_drafts_invalid_response
  ✓ test_get_user_drafts_default_params
  ✓ test_get_user_drafts_custom_params

TestGetUser:
  ✓ test_get_user_success
  ✓ test_get_user_not_found
  ✓ test_get_user_api_error
  ✓ test_get_user_invalid_response
```

**Purpose**: Verify SleeperClient methods work correctly.

**Pattern**:
```python
def test_get_user_drafts_success(self):
    """Test successful draft retrieval."""
    mock_response = [{"draft_id": "123", ...}]

    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = mock_response

        drafts = client.get_user_drafts("user_id")

        assert len(drafts) == 1
        assert drafts[0]["draft_id"] == "123"
```

### tests/test_draft_endpoints.py - API Integration Tests

32 tests organized in 6 classes:

```
TestGetUserDrafts: (10 tests)
  ✓ test_get_user_drafts_success
  ✓ test_get_user_drafts_with_filter_active
  ✓ test_get_user_drafts_with_filter_complete
  ✓ test_get_user_drafts_not_found
  ✓ test_get_user_drafts_server_error
  ✓ test_get_active_drafts_endpoint
  ✓ test_draft_sorting
  ✓ test_custom_sport_and_season
  ✓ test_invalid_status_filter
  ✓ test_draft_sorting_within_status

TestAPIDocumentation: (3 tests)
  ✓ test_openapi_schema
  ✓ test_api_docs_endpoint
  ✓ test_health_endpoint

TestUserLookup: (3 tests)
  ✓ test_lookup_user_success
  ✓ test_lookup_user_not_found
  ✓ test_lookup_user_server_error

TestGetDraftsByUsername: (4 tests)
  ✓ test_get_drafts_by_username_success
  ✓ test_get_drafts_by_username_user_not_found
  ✓ test_get_drafts_by_username_with_filter
  ✓ test_get_drafts_by_username_no_drafts

TestGetDraftPicks: (5 tests)
  ✓ test_get_draft_picks_success
  ✓ test_get_draft_picks_not_found
  ✓ test_get_draft_picks_server_error
  ✓ test_draft_picks_order
  ✓ test_draft_picks_enrichment

TestGetAvailablePlayers: (7 tests)
  ✓ test_get_available_players_success
  ✓ test_get_available_players_excludes_drafted
  ✓ test_get_available_players_with_position_filter
  ✓ test_get_available_players_with_limit
  ✓ test_get_available_players_no_local_data
  ✓ test_get_available_players_server_error
  ✓ test_openapi_schema_includes_available_players
```

**Purpose**: Verify all API endpoints work end-to-end.

**Pattern**:
```python
def test_get_user_drafts_success(self, client, mock_draft_list):
    """Test successful draft retrieval."""
    with patch("src.api.main.sleeper_client.get_user_drafts", return_value=mock_draft_list):
        response = client.get("/api/v1/users/by-id/test_user/drafts")

    assert response.status_code == 200
    data = response.json()
    assert data["total_drafts"] == 3
```

### tests/test_api_storage.py - Storage Unit Tests

9 tests covering:

```
TestPlayerUniverseStorage:
  ✓ test_save_and_load_player_universe
  ✓ test_load_nonexistent_file
  ✓ test_load_corrupted_file
  ✓ test_get_player_universe_age
  ✓ test_save_empty_player_universe
  ✓ test_save_large_player_universe
  ✓ test_player_data_structure_preservation
  ✓ test_create_player_data_directory
  ✓ test_load_preserves_optional_fields
```

**Purpose**: Verify local JSON storage works correctly.

**Pattern**:
```python
def test_save_and_load_player_universe(self, sample_players, tmp_path):
    """Test saving and loading player data."""
    test_file = tmp_path / "test_players.json"

    with patch("src.api.storage.PLAYER_DATA_FILE", test_file):
        save_player_universe(sample_players)
        loaded = load_player_universe()

    assert loaded == sample_players
```

---

## Mocking Strategy

### Why Mock?

**Benefits**:
- ✅ Fast (no real API calls)
- ✅ Reliable (no Sleeper API downtime)
- ✅ Isolated (test one thing)
- ✅ Repeatable (same result every time)

### Common Mocks

#### Mock Sleeper API Response

```python
@pytest.fixture
def mock_draft_list(self):
    """Mock draft list response."""
    return [
        {
            "draft_id": "123",
            "league_id": "456",
            "status": "in_progress",
            "type": "snake",
            "settings": {"teams": 12, "rounds": 15},
            "metadata": {"name": "Test League", "scoring_type": "ppr"},
            "start_time": 1735689600000,
            "sport": "nfl",
            "season": "2026",
        }
    ]
```

#### Mock SleeperClient Method

```python
def test_example(self, client, mock_draft_list):
    """Test with mocked SleeperClient."""
    with patch("src.api.main.sleeper_client.get_user_drafts", return_value=mock_draft_list):
        response = client.get("/api/v1/users/by-id/test_user/drafts")

    assert response.status_code == 200
```

#### Mock File I/O

```python
def test_storage_example(self, sample_players, tmp_path):
    """Test with temporary file instead of real file."""
    test_file = tmp_path / "test_players.json"

    with patch("src.api.storage.PLAYER_DATA_FILE", test_file):
        save_player_universe(sample_players)
        loaded = load_player_universe()

    assert loaded == sample_players
```

---

## Writing New Tests

### Template: Unit Test

```python
def test_my_function():
    """Test my_function with specific input."""
    # Arrange (setup)
    input_data = {"player_id": "2307"}

    # Act (execute)
    result = my_function(input_data)

    # Assert (verify)
    assert result["name"] == "Christian McCaffrey"
```

### Template: Integration Test

```python
def test_my_endpoint(self, client, mock_data):
    """Test endpoint with mock data."""
    # Arrange
    with patch("src.api.main.sleeper_client.method", return_value=mock_data):
        # Act
        response = client.get("/api/v1/endpoint/path")

    # Assert
    assert response.status_code == 200
    assert response.json()["field"] == "expected_value"
```

### Template: Error Test

```python
def test_my_endpoint_not_found(self, client):
    """Test 404 error handling."""
    with patch("src.api.main.sleeper_client.method", return_value=None):
        response = client.get("/api/v1/endpoint/missing_id")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
```

---

## Manual Testing Scripts

### Test User Lookup & Drafts

```bash
python scripts/test_draft_api.py <username>

# Examples:
python scripts/test_draft_api.py sleeperuser
python scripts/test_draft_api.py sleeperuser --active-only
python scripts/test_draft_api.py sleeperuser --base-url https://api.example.com
```

### Test Draft Picks

```bash
python scripts/test_draft_picks.py <draft_id>

# Examples:
python scripts/test_draft_picks.py 1234567890
python scripts/test_draft_picks.py 1234567890 --base-url http://localhost:8000
```

### Test Available Players

```bash
python scripts/test_available_players.py <draft_id> [--position POS]

# Examples:
python scripts/test_available_players.py 1234567890
python scripts/test_available_players.py 1234567890 --position RB
python scripts/test_available_players.py 1234567890 --position QB --limit 20
```

---

## Continuous Integration

### Pre-Commit Testing

Before committing, run tests locally:

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=term-missing

# Only commit if all pass
git add .
git commit -m "Fix bug in user lookup"
```

### Test-Driven Development

Recommended workflow:

1. **Write test** for desired behavior
   ```python
   def test_available_players_with_position_filter():
       response = client.get("/api/v1/drafts/123/available-players?position=RB")
       assert all(p["position"] == "RB" for p in response.json()["players"])
   ```

2. **Run test** (should fail)
   ```bash
   pytest tests/test_draft_endpoints.py::test_available_players_with_position_filter -v
   # FAILED
   ```

3. **Implement feature** to pass test
   ```python
   if position:
       available = {pid: p for pid, p in available.items() if p.get("position") == position.upper()}
   ```

4. **Run test** again (should pass)
   ```bash
   pytest tests/test_draft_endpoints.py::test_available_players_with_position_filter -v
   # PASSED
   ```

5. **Run all tests** to ensure nothing broke
   ```bash
   pytest tests/ -v
   # 88 passed
   ```

---

## Troubleshooting Tests

### Test Fails Locally But Passes in CI

**Possible causes**:
- Different environment (Python version, OS)
- Non-deterministic timing (use fixtures)
- Network dependency (mock it)

**Solution**:
```bash
# Check Python version
python --version

# Clear cache and reinstall
rm -rf .pytest_cache __pycache__
pip install -r requirements.txt

# Run with verbose output
pytest -v -s
```

### Flaky Tests (Intermittent Failures)

**Common causes**:
- Time-dependent logic
- Randomized order
- External API dependency

**Solution**:
```python
# Use pytest-repeat to run test multiple times
pytest tests/test_name.py --count=10

# Use fixtures for setup/teardown
@pytest.fixture
def client():
    # Setup
    yield TestClient(app)
    # Cleanup
```

### Import Errors in Tests

**Solution**:
```bash
# Ensure src/ is in Python path
# pytest automatically adds it, but if needed:
export PYTHONPATH=/path/to/project:$PYTHONPATH
pytest tests/ -v
```

---

## Performance Considerations

### Test Execution Time

Current: ~1.2 seconds for all 88 tests

**Optimization tips**:
- Avoid file I/O in tests (use temp files)
- Avoid network calls (mock everything)
- Use fixtures to share expensive setup

**Profile tests**:
```bash
pytest tests/ --durations=10
# Shows slowest 10 tests
```

---

## Next Steps

- Add load testing (50+ concurrent requests)
- Add contract testing (API version compatibility)
- Set up continuous testing (on each commit)
- Add performance baselines (response time assertions)
