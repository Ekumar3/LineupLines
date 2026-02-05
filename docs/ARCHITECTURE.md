# Architecture & Design Decisions

This document explains the key architectural decisions and design patterns used in the Draft Helper API.

## Framework Choice: FastAPI

### Why FastAPI?

**Selected**: FastAPI
**Alternatives Considered**: Flask, Django, Starlette

### Key Benefits

1. **Seamless Pydantic Integration**
   - FastAPI natively supports Pydantic models
   - Automatic request/response validation
   - Type hints are enforced both in code and at runtime

2. **Automatic API Documentation**
   - Generates OpenAPI 3.0 schema automatically
   - Provides Swagger UI at `/docs`
   - ReDoc at `/redoc`
   - No manual documentation maintenance needed

3. **Asynchronous Support**
   - Built-in async/await support
   - Better performance for I/O-bound operations
   - Non-blocking HTTP requests to Sleeper API

4. **Type Safety**
   - Full Python type hints throughout
   - IDE autocomplete and type checking
   - Catches errors at development time

5. **Minimal Boilerplate**
   - Decorators define endpoints cleanly
   - Dependencies injected automatically
   - CORS and other middleware easy to add

### Trade-offs

| Aspect | FastAPI | Flask | Django |
|--------|---------|-------|--------|
| Learning Curve | Moderate | Low | High |
| Async Support | Native | Third-party | Built-in |
| Auto Docs | Yes | No | No |
| Pydantic Integration | Native | Manual | Manual |
| Performance | Excellent | Good | Good |
| Ecosystem Size | Growing | Mature | Mature |

**Decision**: FastAPI's async capabilities, auto-documentation, and Pydantic integration make it ideal for APIs that need to integrate with external APIs (Sleeper) and provide comprehensive documentation.

---

## Data Validation: Pydantic Models

### Why Pydantic?

**Selected**: Pydantic
**Alternatives**: dataclasses, TypedDict, marshmallow

### Key Benefits

1. **Automatic Validation**
   - Runtime validation of request data
   - Type coercion (string "100" → int 100)
   - Custom validators for complex rules

2. **OpenAPI Integration**
   - FastAPI uses Pydantic schema for OpenAPI docs
   - Model examples shown in Swagger UI
   - Documentation is never out of sync

3. **Clear API Contracts**
   - Models define exact request/response format
   - Changes to API are explicit
   - Breaking changes are obvious

4. **Error Messages**
   - Validation errors include field names and reasons
   - Example: `"position: 'QB' is not a valid position (valid: RB, WR, etc)"`
   - Clients understand what went wrong

### Example: PlayerSummary Model

```python
from pydantic import BaseModel, Field
from typing import Optional

class PlayerSummary(BaseModel):
    """Summary of a player for recommendations."""

    player_id: str = Field(..., description="Sleeper player ID")
    name: str = Field(..., description="Player full name")
    position: str = Field(..., description="Player position")
    team: str = Field(..., description="NFL team abbreviation")
    age: Optional[int] = Field(None, description="Player age")
    years_exp: Optional[int] = Field(None, description="Years of NFL experience")
```

**What this provides**:
- ✅ Runtime validation of all fields
- ✅ Type hints for IDE support
- ✅ Swagger UI examples
- ✅ Clear field descriptions
- ✅ Optional fields with defaults

### Validation in Action

Request validation example:
```json
// Invalid request (missing 'name')
{
  "player_id": "2307",
  "position": "RB",
  "team": "SF"
}
```

Response (422 Unprocessable Entity):
```json
{
  "detail": [
    {
      "loc": ["body", "name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

## Storage Strategy: Local JSON + Future S3

### Why Local JSON Storage?

**Selected**: Local JSON file
**Alternatives**: PostgreSQL, MongoDB, DynamoDB, S3

### Architecture Decision

**Phase 1 (Current)**: Local JSON storage
**Phase 2+**: Upgrade to S3/DynamoDB

### Trade-offs Analysis

| Aspect | Local JSON | Database | S3 | DynamoDB |
|--------|-----------|----------|----|----|
| Setup Time | Immediate | Hours | Hours | Hours |
| Cost | Free | $5-50/mo | $0.50-5/mo | $1-20/mo |
| Query Speed | Medium | Fast | Slow | Very Fast |
| Scale | 10K-100K items | Unlimited | Unlimited | Unlimited |
| Reliability | Local only | Managed | Managed | Managed |
| Suitable for Phase 1 | Yes | No | Maybe | No |

### Why JSON for Phase 1

1. **No Database Setup**
   - Developers can clone and run immediately
   - No Docker containers or database servers needed
   - Focus on API logic, not infrastructure

2. **Sufficient for Current Data**
   - 11,546 players = 19MB JSON file
   - Loads in <100ms
   - Fits in memory easily

3. **Development Friendly**
   - Human-readable format
   - Easy to debug and inspect
   - Git-compatible (for testing)

4. **Easy Migration Path**
   - Storage layer abstraction in `src/api/storage.py`
   - Can add S3/DynamoDB without changing endpoints
   - Fallback to JSON if cloud storage fails

### Storage Layer Abstraction

```python
# src/api/storage.py

def save_player_universe(players: Dict) -> None:
    """Abstraction for persistence - can be swapped for S3/DynamoDB."""
    # Currently: local JSON
    # Future: S3 upload
    # Future: DynamoDB put_item batch

def load_player_universe() -> Optional[Dict]:
    """Abstraction for retrieval - can be swapped."""
    # Currently: local JSON
    # Future: S3 get_object
    # Future: DynamoDB query
```

**Future Upgrade Path**:
```python
# Phase 2 Implementation
def load_player_universe():
    try:
        # Try S3 first (fast, authoritative)
        return s3_client.get_object(Bucket=bucket, Key="players.json")
    except Exception:
        # Fallback to local (development/offline)
        return load_local_json()
```

---

## Error Handling Strategy

### Defensive Programming at Data Layer

**Principle**: Handle None/invalid values at the data source, not in API responses.

### Example: Player Position & Team

**Problem**: Sleeper API sometimes returns None for team/position fields.

**Bad Approach** (API validation layer):
```python
@app.get("/api/v1/...")
def get_draft_picks(draft_id: str):
    picks = sleeper_client.get_draft_picks(draft_id)  # May contain None values
    # Pydantic validation fails because position is None
    return DraftPicksResponse(picks=picks)  # 500 error!
```

**Good Approach** (Data source layer):
```python
# src/data_sources/sleeper_client.py
def _get_player_position(self, player_id: str) -> str:
    """Always return valid string, never None."""
    if not self._player_cache:
        self.get_players()

    if self._player_cache and player_id in self._player_cache:
        position = self._player_cache[player_id].get("position")
        return position if position else "UNKNOWN"  # Defensive!

    return "UNKNOWN"  # Defensive!
```

**Benefits**:
- ✅ Pydantic never receives None for string fields
- ✅ API always returns valid responses
- ✅ Easier to test (no invalid state)
- ✅ Clearer error messages to clients

### HTTP Status Codes

| Code | When | Example |
|------|------|---------|
| 200 | Success | Retrieved draft successfully |
| 404 | Not found | Draft ID doesn't exist |
| 422 | Invalid request | Missing required parameter |
| 500 | Server error | Unexpected exception |

**Never returning 500**: With defensive programming, 500s are prevented.

---

## API Design Patterns

### Path Hierarchy

```
/api/v1/users/lookup/{username}              # GET user info by username
/api/v1/users/{username}/drafts              # GET drafts by username
/api/v1/users/by-id/{user_id}/drafts         # GET drafts by user ID
/api/v1/users/by-id/{user_id}/drafts/active  # GET active drafts only (convenience)
/api/v1/drafts/{draft_id}/picks              # GET picks from draft
/api/v1/drafts/{draft_id}/available-players  # GET available players
```

**Design Principles**:
- Hierarchical path structure reflects data relationships
- Clear distinction between username and user_id lookups
- Convenience endpoints reduce client code complexity
- Consistent `/api/v1/` versioning

### Query Parameters

```
GET /api/v1/users/{username}/drafts?sport=nfl&season=2026&status_filter=active
                                     ^^^^^^^^  ^^^^^^^^^^^^  ^^^^^^^^^^^^^^
                                     optional  optional      optional
```

**Design Principles**:
- Required data in path
- Optional filters in query params
- Defaults applied on server
- Validation via Pydantic Query()

### Response Consistency

All responses follow consistent structure:

```json
{
  // Success response
  "field1": "value",
  "nested": {
    "field2": "value"
  }
}
```

```json
{
  // Error response
  "detail": "Error message"
}
```

**Benefits**:
- Predictable API for clients
- Easy error handling
- Consistent across all endpoints

---

## Testing Strategy

### Test Pyramid

```
                    /\
                   /  \
                  / E2E \
                 /--------\
                /          \
               / Integration \
              /----------------\
             /                  \
            /     Unit Tests      \
           /------------------------\
```

### Test Coverage

| Layer | Tests | Type | Example |
|-------|-------|------|---------|
| Unit | 19 | Mocked | SleeperClient.get_user() |
| Integration | 32 | TestClient | GET /api/v1/users/by-id/{id}/drafts |
| Storage | 9 | File I/O | save_player_universe() |
| **Total** | **52** | **100% pass** | All scenarios |

### Mocking Strategy

**Unit tests use mocks**:
```python
@pytest.fixture
def mock_user_data():
    return {"user_id": "123", "username": "testuser"}

def test_lookup_user(client, mock_user_data):
    with patch("src.api.main.sleeper_client.get_user", return_value=mock_user_data):
        response = client.get("/api/v1/users/lookup/testuser")
    assert response.status_code == 200
```

**Benefits**:
- ✅ Fast (no real API calls)
- ✅ Reliable (no Sleeper API downtime)
- ✅ Isolated (test one thing)
- ✅ Repeatable (same result every time)

---

## Rate Limiting & Reliability

### Sleeper API Rate Limit

- **Limit**: 1000 requests per minute
- **Draft polling needs**: 12 requests/minute (1 every 5 seconds)
- **Headroom**: 98 requests/minute available

### Rate Limiting Implementation

```python
# src/data_sources/sleeper_client.py

class SleeperClient:
    RATE_LIMIT_DELAY = 0.1  # seconds between requests

    def _make_request(self, endpoint: str):
        # Enforce rate limit
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)

        # Make request
        response = requests.get(url)
        self.last_request_time = time.time()
        return response.json()
```

### Fallback Mechanisms

**Player data**:
```python
def get_available_players(draft_id: str):
    # Try local storage first
    all_players = load_player_universe()

    if not all_players:
        # Fallback: fetch from Sleeper
        logger.warning("No local player data, fetching from Sleeper...")
        all_players = sleeper_client.get_players()
        save_player_universe(all_players)  # Cache for next time

    # Use players...
```

**Benefits**:
- ✅ Works offline (with cached data)
- ✅ Survives temporary network issues
- ✅ Degrades gracefully

---

## Logging Strategy

### Log Levels

| Level | When | Example |
|-------|------|---------|
| DEBUG | Low-level details | Cache hit/miss |
| INFO | Normal operations | User lookup, API request |
| WARNING | Potentially problematic | Fallback to Sleeper API |
| ERROR | Something failed | API request exception |

### Log Output

```python
logger.info(f"Looking up user: {username}")
logger.info(f"Found {len(drafted_player_ids)} drafted players")
logger.warning("No local player data, fetching from Sleeper...")
logger.error(f"Failed to fetch picks: {e}", exc_info=True)
```

**Benefits**:
- ✅ Troubleshoot production issues
- ✅ Monitor API performance
- ✅ Track data flow

---

## Future Scaling

### Phase 2: Historical Analysis

**Architectural needs**:
- DynamoDB for fast pattern lookups
- S3 for large analytics files
- Lambda for batch processing

**No changes needed to**:
- FastAPI endpoints (just add new routes)
- Pydantic models (extend, don't modify)
- Storage layer (add S3 implementation)

### Phase 3: Real-Time Recommendations

**Architectural needs**:
- WebSockets or Server-Sent Events
- Real-time database (Redis)
- Notification service

**Supports these patterns**:
- FastAPI supports async websockets
- Recommendation engine as separate module
- Storage layer abstraction ready for Redis

### Phase 4: Frontend

**API readiness**:
- ✅ CORS configured
- ✅ Complete OpenAPI docs
- ✅ Type hints for client generation
- ✅ Consistent error responses

---

## Summary

**Key Architectural Decisions**:

1. **FastAPI** - Async, auto-docs, Pydantic integration
2. **Pydantic** - Validation, type safety, auto-docs
3. **Local JSON** - Simple for Phase 1, easy to upgrade
4. **Defensive Programming** - Handle errors at data source
5. **Test Pyramid** - 52 tests covering all layers
6. **Fallback Mechanisms** - Resilient to failures
7. **Storage Abstraction** - Ready for S3/DynamoDB upgrade

These decisions prioritize **developer experience** in Phase 1 while maintaining **scalability** for future phases.
