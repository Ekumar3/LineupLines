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

### Submit Feedback

**POST /api/v1/feedback**

Accepts a user feedback submission and forwards it to the configured SES inbox.
Rate-limited to **5 requests per minute per IP**.

**Request Body**:
```json
{
  "message": "string (1-2000 chars, required)",
  "page": "string (max 200 chars, optional, defaults to '/')",
  "email": "string (max 200 chars, optional reply-to)"
}
```

**Response (200)**:
```json
{
  "success": true,
  "detail": "Feedback received. Thanks!"
}
```

**Behavior**:
- If `SES_FROM_EMAIL` / `SES_TO_EMAIL` env vars are missing (e.g. local dev), the request is logged via `logger.warning` and still returns `success: true` so the UI doesn't break.
- In production the message is sent via AWS SES using the ECS task IAM role (no hardcoded credentials).
- Returns **429** if the rate limit is exceeded; **500** if SES rejects the send.

**Implementation**: `src/api/feedback.py`. The frontend widget is `frontend/src/components/common/FeedbackWidget.jsx`.

---

### Record Usage Event

**POST /api/v1/events**

Records a self-hosted usage-analytics event (page view, draft completion, or feature click) to DynamoDB. Rate-limited to **30 requests per minute per IP**. No PII is collected — `anonymous_id` is a random UUID generated and stored client-side in `localStorage`.

**Request Body**:
```json
{
  "event_type": "page_view | draft_completed | feature_used",
  "anonymous_id": "string (client-generated UUID)",
  "page": "string (max 200 chars, optional, defaults to '/')",
  "metadata": "object (optional, e.g. { \"feature\": \"vor_mode_next_available\" })"
}
```

**Response (200)**: `{ "success": true }`

**Behavior**:
- If `ANALYTICS_TABLE_NAME` isn't set (e.g. local dev), the event is logged instead of written and the request still returns `success: true`.
- Never returns an error for a failed write — tracking failures must not break the app.

**Implementation**: `src/api/analytics_tracking.py`. Frontend calls go through `frontend/src/utils/analytics.js`.

---

### Usage Summary

**GET /api/v1/summary?days=7**

Returns aggregated usage counts for the trailing N days. Requires an `Authorization: Bearer <ANALYTICS_ADMIN_TOKEN>` header.

**Response (200)**:
```json
{
  "days": 7,
  "unique_visitors": 42,
  "page_views": 210,
  "draft_sessions_completed": 8,
  "feature_usage": { "vor_mode_next_available": 15 }
}
```

Returns **401** if the token is missing/invalid, **503** if `ANALYTICS_TABLE_NAME` isn't configured.

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
      "user_id": "942348475046494208",
      "player_id": "2307",
      "player_name": "Christian McCaffrey",
      "position": "RB",
      "team": "SF",
      "timestamp": "2026-08-15T19:30:00"
    },
    {
      "pick_no": 2,
      "round": 1,
      "user_id": "765432109876543210",
      "player_id": "4866",
      "player_name": "CeeDee Lamb",
      "position": "WR",
      "team": "DAL",
      "timestamp": "2026-08-15T19:32:00"
    }
  ]
}
```

**Key Fields**:

- `user_id`: Sleeper user ID of the user who made the pick. Use this with the draft order endpoint to identify the user's name and other details.

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

### Get League Settings

**GET /api/v1/drafts/{draft_id}/league-settings**

Get league scoring settings to determine the appropriate ADP format (PPR, half-PPR, or standard).

**Parameters**:
- `draft_id` (path, required): Sleeper draft ID

**Response** (200):
```json
{
  "draft_id": "789012345",
  "league_id": "456789012",
  "settings": {
    "league_id": "456789012",
    "scoring_format": "ppr",
    "roster_positions": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "K", "DEF"],
    "total_rosters": 12
  }
}
```

**Errors**:
- 404: Draft or league not found
- 500: Server error

**Example**:
```bash
curl http://localhost:8000/api/v1/drafts/789012345/league-settings
```

---

### Get Available Players by Position

**GET /api/v1/drafts/{draft_id}/available-by-position**

Get available (undrafted) players grouped by position, sorted by ADP delta. This is useful for real-time draft recommendations at each pick.

**Parameters**:
- `draft_id` (path, required): Sleeper draft ID
- `limit` (query, optional): Max players to return per position (default: 20, max: 100)

**Response** (200):
```json
{
  "draft_id": "789012345",
  "current_overall_pick": 25,
  "current_round": 3,
  "scoring_format": "ppr",
  "limit": 20,
  "players_by_position": {
    "QB": [
      {
        "player_id": "2307",
        "player_name": "Christian McCaffrey",
        "position": "QB",
        "team": "SF",
        "age": 27,
        "years_exp": 7,
        "adp_ppr": 15.2,
        "adp_delta": 9.8
      }
    ],
    "RB": [],
    "WR": [],
    "TE": [],
    "K": [],
    "DEF": []
  }
}
```

**Key Fields**:
- `current_overall_pick`: The next pick number to be made (total picks made + 1)
- `current_round`: Current draft round
- `scoring_format`: League's scoring format (ppr, half_ppr, standard)
- `adp_delta` in AvailablePlayerDetail: Positive means player is available later than their ADP (good value), negative means they're expected to go earlier (reaching if drafted now)

**Errors**:
- 404: Draft not found
- 500: Server error

**Example**:
```bash
curl "http://localhost:8000/api/v1/drafts/789012345/available-by-position?limit=10"
```

---

### Get User Roster

**GET /api/v1/drafts/{draft_id}/users/{user_id}/roster**

Get a user's drafted picks organized by position with position strength analysis.

**Parameters**:
- `draft_id` (path, required): Sleeper draft ID
- `user_id` (path, required): Sleeper user ID

**Response** (200):
```json
{
  "draft_id": "789012345",
  "user_id": "942348475046494208",
  "draft_slot": 3,
  "total_picks": 7,
  "roster_by_position": {
    "QB": [],
    "RB": [
      {
        "pick_no": 3,
        "round": 1,
        "user_id": "942348475046494208",
        "player_id": "2307",
        "player_name": "Christian McCaffrey",
        "position": "RB",
        "team": "SF",
        "timestamp": "2026-08-15T19:30:00"
      }
    ],
    "WR": [],
    "TE": [],
    "K": [],
    "DEF": []
  },
  "position_summary": {
    "QB": {"count": 0, "needs_more": true, "priority": "high"},
    "RB": {"count": 1, "needs_more": true, "priority": "medium"},
    "WR": {"count": 0, "needs_more": true, "priority": "medium"},
    "TE": {"count": 0, "needs_more": true, "priority": "high"},
    "K": {"count": 0, "needs_more": false, "priority": "low"},
    "DEF": {"count": 0, "needs_more": false, "priority": "low"}
  }
}
```

**Key Fields**:
- `draft_slot`: User's draft position (1-based)
- `position_summary`: Analysis of position needs with priority (high/medium/low)
  - `count`: Number of players at this position
  - `needs_more`: Whether roster still needs players at this position
  - `priority`: Drafting priority based on roster construction and ADP-based value

**Errors**:
- 404: Draft or user not found
- 500: Server error

**Example**:
```bash
curl "http://localhost:8000/api/v1/drafts/789012345/users/942348475046494208/roster"
```

---

### VOR Analysis

**GET /api/v1/draft/{draft_id}/vor**

Get Value Over Replacement (VOR) analysis for available players in a draft. Returns top recommendations per position, ranked by VOR score.

> **Note**: This endpoint uses `/draft/` (singular), not `/drafts/`.

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `draft_id` | string | Sleeper draft ID |

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit_per_position` | int | 5 | Max recommendations per position |

**Response** (`VORAnalysisResponse`):
```json
{
  "league_id": "string",
  "draft_id": "string",
  "recommendations": [
    {
      "league_id": "string",
      "draft_id": "string",
      "player_id": "string",
      "player_name": "Bijan Robinson",
      "position": "RB",
      "adp_overall": 3.2,
      "replacement_level_adp": 45.0,
      "vor_score": 41.8,
      "interpretation": "Elite Value",
      "draft_position": null,
      "picks_remaining": 150
    }
  ],
  "top_value_pick": { /* same shape as above */ },
  "replacement_level_by_position": {
    "QB": 85.0,
    "RB": 45.0,
    "WR": 40.0,
    "TE": 95.0
  }
}
```

**Errors**:
| Code | Detail |
|------|--------|
| 400 | No available players to analyze |
| 404 | Draft not found |
| 500 | Failed to calculate VOR |

**Example**:
```bash
curl http://localhost:8000/api/v1/draft/12345/vor?limit_per_position=3
```

---

### Player VOR

**GET /api/v1/draft/{draft_id}/player/{player_id}/vor**

Get VOR analysis for a specific player.

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `draft_id` | string | Sleeper draft ID |
| `player_id` | string | Player ID to analyze |

**Response** (`VORPlayerDetail`):
```json
{
  "player_id": "string",
  "player_name": "CeeDee Lamb",
  "position": "WR",
  "adp_overall": 5.1,
  "replacement_level_adp": 40.0,
  "vor_score": 34.9,
  "interpretation": "Elite Value"
}
```

**Errors**:
| Code | Detail |
|------|--------|
| 404 | Player not found |
| 500 | Server error |

**Example**:
```bash
curl http://localhost:8000/api/v1/draft/12345/player/6786/vor
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
  "user_id": "string",
  "player_id": "string",
  "player_name": "string",
  "position": "RB|WR|QB|TE|etc",
  "team": "SF|DAL|etc",
  "timestamp": "2026-08-15T19:30:00 (ISO format)",
  "adp_ppr": number (optional, player's ADP in PPR format),
  "adp_delta": number (optional, positive=value/picked later than ADP, negative=reach/picked earlier)
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

### VORPlayerDetail

```json
{
  "player_id": "string",
  "player_name": "string",
  "position": "QB|RB|WR|TE",
  "adp_overall": number,
  "replacement_level_adp": number,
  "vor_score": number,
  "interpretation": "Elite Value|Strong Value|Moderate Value|etc"
}
```

### VORDraftRecommendation

```json
{
  "league_id": "string",
  "draft_id": "string",
  "player_id": "string",
  "player_name": "string",
  "position": "string",
  "adp_overall": number,
  "replacement_level_adp": number,
  "vor_score": number,
  "interpretation": "string",
  "draft_position": number (optional),
  "picks_remaining": number
}
```

### VORAnalysisResponse

```json
{
  "league_id": "string",
  "draft_id": "string",
  "recommendations": [VORDraftRecommendation],
  "top_value_pick": VORDraftRecommendation,
  "replacement_level_by_position": {"QB": number, "RB": number, ...}
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

### Inbound (clients → this API)

IP-based rate limits are enforced by `slowapi`, keyed on the X-Forwarded-For client IP when the request arrives via CloudFront/ALB:

| Endpoint pattern | Limit | Rationale |
|------------------|-------|-----------|
| `POST /api/v1/feedback` | **5/minute per IP** | Tightest cap — protects SES quota + your inbox from spam |
| `POST /api/v1/events` | **30/minute per IP** | Fires on every page view/interaction; generous but bounded |
| All other endpoints (default) | **60/minute per IP** | Generous for an active drafter polling + manual refreshes |

When a limit is exceeded the API returns **HTTP 429** with `{"detail": "Rate limit exceeded: ..."}`. The `Retry-After` header is set when applicable.

Implementation: `src/api/rate_limit.py` defines the `Limiter` (custom XFF-aware `key_func`); `src/api/main.py` wires it in via `SlowAPIMiddleware` and registers `_rate_limit_exceeded_handler`.

### SSE concurrency caps

The `DraftBroadcaster` (`src/api/draft_stream.py`) caps in-memory state to prevent abuse:
- `MAX_ACTIVE_DRAFTS = 50` — total unique `draft_id`s being polled at once
- `MAX_SUBSCRIBERS_PER_DRAFT = 50` — viewers on any single draft

Hitting either cap returns **HTTP 429** with `detail: "Too many active drafts ..."` from `GET /api/v1/drafts/{draft_id}/stream`.

### Outbound (this API → Sleeper)

Sleeper API rate limit: **1000 requests per minute**. The `SleeperClient` enforces a 0.1s minimum gap between outbound requests.

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
| 429 | Rate limited / capacity exceeded | Back off and retry; see `Retry-After` header. Either an IP rate limit or a `DraftBroadcaster` cap was hit. |
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
