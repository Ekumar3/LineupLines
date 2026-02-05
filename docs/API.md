# API Documentation

Complete reference for all Draft Helper API endpoints.

## Base URL

```
http://localhost:8000
```

## Authentication

No authentication required. Sleeper API is public.

## Response Format

All responses are JSON with consistent structure:

**Success (2xx)**:
```json
{
  // Response-specific data
}
```

**Error (4xx, 5xx)**:
```json
{
  "detail": "Error message describing what went wrong"
}
```

---

## Endpoints

### Health Check

**GET /health**

Health check endpoint to verify API is running.

**Response**:
```json
{
  "status": "ok",
  "service": "draft-helper"
}
```

**Example**:
```bash
curl http://localhost:8000/health
```

---

### User Lookup

**GET /api/v1/users/lookup/{username}**

Look up a Sleeper user by username.

**Parameters**:
- `username` (path, required): Sleeper username (e.g., 'sleeperuser')

**Response** (200):
```json
{
  "user_id": "123456789",
  "username": "sleeperuser",
  "display_name": "Sleeper User",
  "avatar": "https://example.com/avatar.jpg",
  "verified": false
}
```

**Errors**:
- 404: User not found
- 500: Server error

**Example**:
```bash
curl http://localhost:8000/api/v1/users/lookup/sleeperuser
```

---

### Get User Drafts by Username

**GET /api/v1/users/{username}/drafts**

Get all drafts for a user by their username. Automatically looks up user_id.

**Parameters**:
- `username` (path, required): Sleeper username
- `sport` (query, optional): Sport type (default: 'nfl')
- `season` (query, optional): Season year (default: '2026')
- `status_filter` (query, optional): Filter by status: 'active' or 'complete'

**Response** (200):
```json
{
  "user_id": "123456789",
  "sport": "nfl",
  "season": "2026",
  "total_drafts": 5,
  "active_drafts": 2,
  "drafts": [
    {
      "draft_id": "789012345",
      "league_id": "456789012",
      "status": "in_progress",
      "settings": {
        "teams": 12,
        "rounds": 15,
        "reversal_round": 1,
        "type": "snake"
      },
      "metadata": {
        "name": "My Fantasy League 2026",
        "scoring_type": "ppr"
      },
      "start_time": 1735689600000,
      "sport": "nfl",
      "season": "2026"
    }
  ]
}
```

**Errors**:
- 404: User not found or no drafts found
- 500: Server error

**Examples**:
```bash
# Get all drafts
curl http://localhost:8000/api/v1/users/sleeperuser/drafts

# Get only active drafts
curl "http://localhost:8000/api/v1/users/sleeperuser/drafts?status_filter=active"

# Get only complete drafts
curl "http://localhost:8000/api/v1/users/sleeperuser/drafts?status_filter=complete"
```

---

### Get User Drafts by User ID

**GET /api/v1/users/by-id/{user_id}/drafts**

Get all drafts for a user by their user ID.

**Parameters**:
- `user_id` (path, required): Sleeper user ID
- `sport` (query, optional): Sport type (default: 'nfl')
- `season` (query, optional): Season year (default: '2026')
- `status_filter` (query, optional): Filter by status: 'active' or 'complete'

**Response** (200): Same as "Get User Drafts by Username"

**Errors**:
- 404: User not found or no drafts found
- 500: Server error

**Example**:
```bash
curl "http://localhost:8000/api/v1/users/by-id/123456789/drafts?status_filter=active"
```

---

### Get Active Drafts (Convenience)

**GET /api/v1/users/by-id/{user_id}/drafts/active**

Convenience endpoint to get only active drafts. Shorthand for `?status_filter=active`.

**Parameters**:
- `user_id` (path, required): Sleeper user ID
- `sport` (query, optional): Sport type (default: 'nfl')
- `season` (query, optional): Season year (default: '2026')

**Response** (200): Same as "Get User Drafts by Username"

**Example**:
```bash
curl http://localhost:8000/api/v1/users/by-id/123456789/drafts/active
```

---

### Get Draft Details

**GET /api/v1/drafts/{draft_id}**

Get complete draft information including the draft order and user-to-roster mapping. This endpoint is essential for the draft board UI to identify which user made each pick.

**Parameters**:

- `draft_id` (path, required): Sleeper draft ID

**Response** (200):
```json
{
  "draft_id": "789012345",
  "league_id": "456789012",
  "status": "in_progress",
  "settings": {
    "teams": 12,
    "rounds": 15,
    "reversal_round": 1,
    "type": "snake"
  },
  "metadata": {
    "name": "My Fantasy League 2026",
    "scoring_type": "ppr"
  },
  "draft_order": ["942348475046494208", "765432109876543210", "123456789012345678", null, "876543210123456789"],
  "roster_to_user": {
    "1": "942348475046494208",
    "2": "765432109876543210",
    "3": "123456789012345678",
    "4": "876543210123456789",
    "5": "555555555555555555"
  }
}
```

#### Key Fields

- `draft_order`: Array indexed by slot position (0-based), containing user_ids as strings or `null` for unpicked slots. Index 0 = 1st pick, index 1 = 2nd pick, etc.
- `roster_to_user`: Maps roster_id (string key) to user_id (string value). All IDs are normalized to strings for API consistency. Use this to identify which user made each pick by matching the pick's `roster_id`.

#### ID Normalization

All IDs (user_ids, roster_ids, draft_ids) are normalized to strings throughout the API. This avoids type conversion issues and provides consistency. Even though Sleeper's API returns mixed types, this endpoint always returns strings.

#### Example Usage

To identify which user made a pick:

1. Get the pick's `roster_id` from the `/picks` endpoint (string: "1", "2", etc.)
2. Look it up in `roster_to_user` to find the `user_id` (string: "942348475046494208", etc.)
3. Use the `user_id` to display the pick owner's name

**Code Example**:

```javascript
const draftDetails = await fetch(`/api/v1/drafts/${draftId}`).then(r => r.json());
const pick = picks[0];  // { roster_id: "1", player_id: "2307", ... }
const userId = draftDetails.roster_to_user[pick.roster_id];
// userId = "942348475046494208"
```

**Errors**:

- 404: Draft not found
- 500: Server error

**Example**:
```bash
curl http://localhost:8000/api/v1/drafts/789012345
```

---

### Get Draft Picks

**GET /api/v1/drafts/{draft_id}/picks**

Get all picks made in a draft so far, with enriched player data.

**Parameters**:
- `draft_id` (path, required): Sleeper draft ID

**Response** (200):
```json
{
  "draft_id": "789012345",
  "total_picks": 24,
  "picks": [
    {
      "pick_no": 1,
      "round": 1,
      "roster_id": 1,
      "player_id": "2307",
      "player_name": "Christian McCaffrey",
      "position": "RB",
      "team": "SF",
      "timestamp": "2026-08-15T19:30:00"
    },
    {
      "pick_no": 2,
      "round": 1,
      "roster_id": 2,
      "player_id": "4866",
      "player_name": "CeeDee Lamb",
      "position": "WR",
      "team": "DAL",
      "timestamp": "2026-08-15T19:32:00"
    }
  ]
}
```

**Errors**:
- 404: Draft not found or no picks
- 500: Server error

**Example**:
```bash
curl http://localhost:8000/api/v1/drafts/789012345/picks
```

---

### Get Available Players

**GET /api/v1/drafts/{draft_id}/available-players**

Get all players who have not been drafted yet, with optional filtering.

**Parameters**:
- `draft_id` (path, required): Sleeper draft ID
- `position` (query, optional): Filter by position (RB, WR, QB, TE, etc.)
- `limit` (query, optional): Max players to return (default: 100, max: 500)

**Response** (200):
```json
{
  "draft_id": "789012345",
  "total_available": 450,
  "position_filter": null,
  "players": [
    {
      "player_id": "2307",
      "name": "Christian McCaffrey",
      "position": "RB",
      "team": "SF",
      "age": 27,
      "years_exp": 7
    },
    {
      "player_id": "4866",
      "name": "CeeDee Lamb",
      "position": "WR",
      "team": "DAL",
      "age": 24,
      "years_exp": 3
    }
  ]
}
```

**Errors**:
- 500: Server error (if player data unavailable)

**Examples**:
```bash
# Get all available players
curl "http://localhost:8000/api/v1/drafts/789012345/available-players"

# Filter by position
curl "http://localhost:8000/api/v1/drafts/789012345/available-players?position=RB"

# Limit results
curl "http://localhost:8000/api/v1/drafts/789012345/available-players?limit=50"

# Combine filters
curl "http://localhost:8000/api/v1/drafts/789012345/available-players?position=QB&limit=20"
```

---

## Status Values

Sleeper uses these draft status values:

| Status | Meaning |
|--------|---------|
| `pre_draft` | Draft scheduled but not started |
| `drafting` | Draft is happening now (active) |
| `in_progress` | Draft is happening now (active) |
| `complete` | Draft finished |

For the `status_filter` parameter:
- `active` - Returns drafts with status "pre_draft", "drafting", or "in_progress"
- `complete` - Returns drafts with status "complete"
- Not specified - Returns all drafts

---

## Data Models

### DraftSummary

```json
{
  "draft_id": "string",
  "league_id": "string",
  "status": "pre_draft|drafting|in_progress|complete",
  "settings": {
    "teams": number,
    "rounds": number,
    "reversal_round": number (optional),
    "type": "snake|linear|auction"
  },
  "metadata": {
    "name": "string (optional)",
    "scoring_type": "ppr|standard|half_ppr (optional)"
  },
  "start_time": number (unix timestamp in ms, optional),
  "sport": "nfl|nba|mlb|etc",
  "season": "string"
}
```

### PickDetail

```json
{
  "pick_no": number,
  "round": number,
  "roster_id": number,
  "player_id": "string",
  "player_name": "string",
  "position": "RB|WR|QB|TE|etc",
  "team": "SF|DAL|etc",
  "timestamp": "2026-08-15T19:30:00 (ISO format)"
}
```

### PlayerSummary

```json
{
  "player_id": "string",
  "name": "string",
  "position": "RB|WR|QB|TE|etc",
  "team": "SF|DAL|FA|etc",
  "age": number (optional),
  "years_exp": number (optional)
}
```

---

## OpenAPI Documentation

Full interactive API documentation available at `/docs` (Swagger UI) or `/redoc` (ReDoc).

Visit `http://localhost:8000/docs` to explore all endpoints with:
- Parameter descriptions
- Example requests/responses
- Try-it-out functionality
- Schema definitions

Raw OpenAPI schema available at `/openapi.json`.

---

## Rate Limiting

Sleeper API rate limit: **1000 requests per minute**

The draft helper respects this limit with built-in rate limiting. For production deployments, implement:
- Client-side request queueing
- Cache responses where appropriate
- Monitor rate limit headers

---

## Error Handling

All errors return JSON with `detail` field:

```json
{
  "detail": "Error message describing what went wrong"
}
```

### Common Error Codes

| Code | Meaning | Solution |
|------|---------|----------|
| 400 | Bad request | Check request parameters and format |
| 404 | Not found | Verify resource ID (user_id, draft_id) |
| 422 | Validation error | Check parameter types and constraints |
| 500 | Server error | Check logs, verify Sleeper API is accessible |

---

## Testing

Manual testing scripts available:

```bash
# Test user/draft endpoints
python scripts/test_draft_api.py <username>

# Test draft picks
python scripts/test_draft_picks.py <draft_id>

# Test available players
python scripts/test_available_players.py <draft_id> --position QB
```

Or use curl directly:

```bash
# Test health
curl http://localhost:8000/health

# Test user lookup
curl http://localhost:8000/api/v1/users/lookup/<username>

# Test drafts
curl http://localhost:8000/api/v1/users/by-id/<user_id>/drafts

# Test picks
curl http://localhost:8000/api/v1/drafts/<draft_id>/picks

# Test available players
curl http://localhost:8000/api/v1/drafts/<draft_id>/available-players
```
