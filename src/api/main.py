"""Draft Helper API - Main application."""

import asyncio
import json
import logging
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from fastapi.middleware.cors import CORSMiddleware

from src.data_sources.sleeper_client import SleeperClient, Roster, roster_bench
from src.data_sources.sleeper_projections_client import SleeperProjectionsClient
from src.analytics.adp_service import adp_service
from src.services import adp_sources, environment_score
from src.api.models import (
    UserDraftsResponse,
    DraftSummary,
    ErrorResponse,
    UserLookupResponse,
    DraftPicksResponse,
    PickDetail,
    AvailablePlayersResponse,
    PlayerSummary,
    DraftDetails,
    DraftSettings,
    DraftMetadata,
    LeagueSettings,
    LeagueSettingsResponse,
    UserRosterResponse,
    PositionNeed,
    AvailablePlayerDetail,
    AvailableByPositionResponse,
    VORPlayerDetail,
    VORDraftRecommendation,
    VORAnalysisResponse,
    MatchupGradeResponse,
    RosterPlayer,
    RosterResponse,
    LeagueRostersResponse,
    StartSitRecommendation,
    RecommendationsResponse,
    WaiverRecResponse,
    WaiverResponse,
    DropAddRecResponse,
    DropAddResponse,
)
from src.api.storage import load_player_universe, save_player_universe
from src.api.draft_stream import BroadcasterCapacityError, DraftBroadcaster
from src.api.correlation import new_correlation_id
from src.api.logging_config import configure_logging
from src.api.feedback import router as feedback_router
from src.api.analytics_tracking import router as analytics_router
from src.api.rate_limit import limiter, shared_draft_limit

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

configure_logging()
logger = logging.getLogger(__name__)

import os

app = FastAPI(
    title="Draft Helper API",
    version="1.0",
    description="Fantasy football draft helper using Sleeper API and historical ADP data",
)

# Set up CORS origins
origins = [
    "http://localhost:5173",  # Local Vite dev server
    "http://localhost:3000",  # Local React dev server
]

# Add production Vercel frontend URL from environment variable
frontend_url = os.environ.get("FRONTEND_URL")
if frontend_url:
    origins.extend([url.strip() for url in frontend_url.split(",")])

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    # Tightened from "*" — only the methods/headers the frontend actually uses.
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)

# Wire the IP-based rate limiter. Limits are applied per-endpoint via
# decorators (see shared_draft_limit on draft reads, @limiter.limit on
# /feedback). The previous SlowAPIMiddleware was removed because it is
# built on Starlette's BaseHTTPMiddleware, which buffers StreamingResponse
# bodies and broke the /stream SSE endpoint.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Initialize Sleeper client (singleton)
sleeper_client = SleeperClient()
draft_broadcaster = DraftBroadcaster(sleeper_client)

# Initialize Sleeper projections client (singleton, 24-hour cache)
sleeper_projections_client = SleeperProjectionsClient()


app.include_router(feedback_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "draft-helper"}


@app.get(
    "/api/v1/users/lookup/{username}",
    response_model=UserLookupResponse,
    responses={
        200: {"description": "Successfully retrieved user info"},
        404: {"model": ErrorResponse, "description": "User not found"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    summary="Look up user by username",
    description="Get user information including user_id from Sleeper username",
    tags=["Users"],
)
def lookup_user(username: str):
    """
    Look up a user by their Sleeper username.

    Returns their user_id and other profile information, which can be used
    to fetch their drafts.

    - **username**: Sleeper username (e.g., 'sleeperuser')

    Returns the user_id needed for other endpoints.
    """
    logger.info(f"Looking up user: {username}")

    try:
        user_data = sleeper_client.get_user(username)

        if not user_data:
            raise HTTPException(
                status_code=404,
                detail=f"User not found: {username}",
            )

        return UserLookupResponse(
            user_id=user_data.get("user_id", ""),
            username=user_data.get("username", username),
            display_name=user_data.get("display_name"),
            avatar=user_data.get("avatar"),
            verified=user_data.get("verified", False),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error looking up user {username}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {str(e)}"
        )


@app.get(
    "/api/v1/users/{username}/drafts",
    response_model=UserDraftsResponse,
    responses={
        200: {"description": "Successfully retrieved user drafts"},
        404: {"model": ErrorResponse, "description": "User not found or no drafts"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    summary="Get drafts by username",
    description="Get all drafts for a user by their username (automatically looks up user_id)",
    tags=["Drafts"],
)
def get_user_drafts_by_username(
    username: str,
    sport: str = Query(default="nfl", description="Sport type (nfl, nba, etc)"),
    season: str = Query(default="2026", description="Season year"),
    status_filter: Optional[str] = Query(
        default=None,
        description="Filter by status: 'active' (in_progress + pre_draft), 'complete', or leave it empty for all",
        pattern="^(active|complete)$|^$",
    ),
):
    """
    Get all drafts for a user by their username.

    This endpoint automatically looks up the user_id from the username,
    then fetches their drafts.

    - **username**: Sleeper username (e.g., 'sleeperuser')
    - **sport**: Sport type, defaults to 'nfl'
    - **season**: Season year, defaults to '2026'
    - **status_filter**: Filter drafts by status (active/complete/all)
    """
    logger.info(f"Fetching drafts for username {username}")

    try:
        # Look up user by username
        user_data = sleeper_client.get_user(username)

        if not user_data:
            raise HTTPException(
                status_code=404,
                detail=f"User not found: {username}",
            )

        user_id = user_data.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=500,
                detail="Invalid user data returned from Sleeper API",
            )

        # Fetch drafts using the user_id
        raw_drafts = sleeper_client.get_user_drafts(user_id, sport, season)

        if not raw_drafts:
            raise HTTPException(
                status_code=404,
                detail=f"No drafts found for user {username} in {sport} {season}",
            )

        # Fetch leagues to enrich metadata (e.g. TE Premium)
        raw_leagues = sleeper_client.get_user_leagues(user_id, sport, season)
        user_leagues = {l.get("league_id"): l for l in raw_leagues}

        # Transform to DraftSummary objects
        draft_summaries = _transform_drafts(raw_drafts, user_leagues)

        # Remove drafts whose parent league has been deleted on Sleeper
        draft_summaries = _filter_orphaned_drafts(draft_summaries, user_leagues)

        # Apply status filtering
        if status_filter == "active":
            filtered_drafts = [
                d for d in draft_summaries if d.status in ["pre_draft", "in_progress", "drafting"]
            ]
        elif status_filter == "complete":
            filtered_drafts = [d for d in draft_summaries if d.status == "complete"]
        else:
            filtered_drafts = draft_summaries

        # Sort by status priority and start_time
        filtered_drafts = _sort_drafts(filtered_drafts)

        # Calculate active draft count
        active_count = sum(
            1 for d in draft_summaries if d.status in ["pre_draft", "in_progress", "drafting"]
        )

        return UserDraftsResponse(
            user_id=user_id,
            sport=sport,
            season=season,
            total_drafts=len(draft_summaries),
            active_drafts=active_count,
            drafts=filtered_drafts,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching drafts for username {username}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {str(e)}"
        )


@app.get(
    "/api/v1/users/by-id/{user_id}/drafts",
    response_model=UserDraftsResponse,
    responses={
        200: {"description": "Successfully retrieved user drafts"},
        404: {"model": ErrorResponse, "description": "User not found or no drafts"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    summary="Get user's drafts by user ID",
    description="Fetch all drafts for a given Sleeper user ID, with optional filtering by status",
    tags=["Drafts"],
)
def get_user_drafts_by_id(
    user_id: str,
    sport: str = Query(default="nfl", description="Sport type (nfl, nba, etc)"),
    season: str = Query(default="2026", description="Season year"),
    status_filter: Optional[str] = Query(
        default=None,
        description="Filter by status: 'active' (in_progress + pre_draft), 'complete', or None for all",
        pattern="^(active|complete)$|^$",
    ),
):
    """
    Get all drafts for a user with optional filtering.

    - **user_id**: Sleeper user ID (required path parameter)
    - **sport**: Sport type, defaults to 'nfl'
    - **season**: Season year, defaults to '2026'
    - **status_filter**: Filter drafts by status:
        - 'active': Only pre_draft and in_progress drafts
        - 'complete': Only completed drafts
        - None: All drafts
    """
    logger.info(
        f"Fetching drafts for user {user_id} (sport={sport}, season={season}, filter={status_filter})"
    )

    try:
        # Fetch drafts from Sleeper
        raw_drafts = sleeper_client.get_user_drafts(user_id, sport, season)

        if not raw_drafts:
            raise HTTPException(
                status_code=404,
                detail=f"No drafts found for user_id: {user_id} in {sport} {season}",
            )

        # Fetch leagues to enrich metadata (e.g. TE Premium)
        raw_leagues = sleeper_client.get_user_leagues(user_id, sport, season)
        user_leagues = {l.get("league_id"): l for l in raw_leagues}

        # Transform to DraftSummary objects
        draft_summaries = _transform_drafts(raw_drafts, user_leagues)

        # Remove drafts whose parent league has been deleted on Sleeper
        draft_summaries = _filter_orphaned_drafts(draft_summaries, user_leagues)

        # Apply status filtering
        if status_filter == "active":
            filtered_drafts = [
                d for d in draft_summaries if d.status in ["pre_draft", "in_progress", "drafting"]
            ]
        elif status_filter == "complete":
            filtered_drafts = [d for d in draft_summaries if d.status == "complete"]
        else:
            filtered_drafts = draft_summaries

        # Sort by status priority and start_time
        filtered_drafts = _sort_drafts(filtered_drafts)

        # Calculate active draft count
        active_count = sum(
            1 for d in draft_summaries if d.status in ["pre_draft", "in_progress", "drafting"]
        )

        return UserDraftsResponse(
            user_id=user_id,
            sport=sport,
            season=season,
            total_drafts=len(draft_summaries),
            active_drafts=active_count,
            drafts=filtered_drafts,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching drafts for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {str(e)}"
        )


@app.get(
    "/api/v1/users/by-id/{user_id}/drafts/active",
    response_model=UserDraftsResponse,
    responses={
        200: {"description": "Successfully retrieved active drafts"},
        404: {"model": ErrorResponse, "description": "No active drafts found"},
    },
    summary="Get user's active drafts by user ID",
    description="Convenience endpoint to fetch only active drafts (in_progress + pre_draft)",
    tags=["Drafts"],
)
def get_active_user_drafts_by_id(
    user_id: str,
    sport: str = Query(default="nfl", description="Sport type"),
    season: str = Query(default="2026", description="Season year"),
):
    """
    Get only active/live drafts for a user by user ID.

    Shorthand for GET /users/by-id/{user_id}/drafts?status_filter=active

    - **user_id**: Sleeper user ID
    - **sport**: Sport type, defaults to 'nfl'
    - **season**: Season year, defaults to '2026'
    """
    return get_user_drafts_by_id(user_id, sport, season, status_filter="active")


@app.get(
    "/api/v1/drafts/{draft_id}/picks",
    response_model=DraftPicksResponse,
    responses={
        200: {"description": "Successfully retrieved draft picks"},
        404: {"model": ErrorResponse, "description": "Draft not found or no picks"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    summary="Get all picks from a draft",
    description="Fetch all picks made in a draft so far, with player information",
    tags=["Drafts"],
)
@shared_draft_limit
def get_draft_picks(request: Request, draft_id: str):
    """
    Get all picks from a draft.

    Returns picks in chronological order with enriched player data including
    names, positions, and teams.

    - **draft_id**: Sleeper draft ID (required path parameter)
    """
    logger.info(f"Fetching picks for draft {draft_id}")

    try:
        # Fetch picks from Sleeper (includes player enrichment and roster mapping)
        draft_picks = sleeper_client.get_draft_picks(draft_id)

        if not draft_picks:
            raise HTTPException(
                status_code=404,
                detail=f"No picks found for draft_id: {draft_id}",
            )

        # Load Sleeper projections for ADP enrichment (24-hour cache, fast after first call)
        draft_details_for_picks = sleeper_client.get_draft_details(draft_id)
        _picks_year = int(draft_details_for_picks.get("season", 2026)) if draft_details_for_picks else 2026
        _picks_league_id = draft_details_for_picks.get("league_id") if draft_details_for_picks else None
        _picks_scoring = sleeper_client.get_scoring_format(_picks_league_id) if _picks_league_id else "ppr"
        _picks_proj = sleeper_projections_client.fetch_projections(_picks_year, _picks_scoring)

        # Transform DraftPick dataclasses to PickDetail Pydantic models
        # Include ADP data for value analysis
        pick_details = []
        for pick in draft_picks:
            # Look up Sleeper ADP directly by player_id (O(1), no name matching)
            _pick_proj = _picks_proj.get(pick.player_id)
            adp_ppr = _pick_proj.adp if _pick_proj else None

            # Calculate delta (pick_no - adp: positive = picked later than ADP = value)
            adp_delta = None
            if adp_ppr:
                adp_delta = pick.pick_no - adp_ppr

            pick_detail = PickDetail(
                pick_no=pick.pick_no,
                round=pick.round,
                user_id=pick.user_id,
                player_id=pick.player_id,
                player_name=pick.player_name,
                position=pick.position,
                team=pick.team,
                timestamp=pick.timestamp.isoformat(),
                adp_ppr=adp_ppr,
                adp_delta=adp_delta,
            )
            pick_details.append(pick_detail)

        return DraftPicksResponse(
            draft_id=draft_id,
            total_picks=len(pick_details),
            picks=pick_details,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching picks for draft {draft_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {str(e)}"
        )


@app.get(
    "/api/v1/drafts/{draft_id}",
    response_model=DraftDetails,
    responses={
        200: {"description": "Successfully retrieved draft details"},
        404: {"model": ErrorResponse, "description": "Draft not found"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    summary="Get complete draft details including roster mapping",
    description="Returns full draft information including draft order and user-to-roster mapping for tracking picks",
    tags=["Drafts"],
)
@shared_draft_limit
def get_draft_details(request: Request, draft_id: str):
    """
    Get complete draft details with roster mapping.

    This endpoint returns the draft's configuration, status, and most importantly
    the draft_order and roster_to_user mapping, which tells you which user is
    at which draft position. Use this to identify which picks belong to a specific user.

    - **draft_id**: Sleeper draft ID (required path parameter)

    The roster_to_user mapping is a dict mapping roster_id (str) to user_id,
    allowing you to identify which user made each pick by matching the pick's roster_id.
    """
    logger.info(f"Fetching details for draft {draft_id}")

    try:
        draft_details = sleeper_client.get_draft_details(draft_id)

        if not draft_details:
            raise HTTPException(
                status_code=404,
                detail=f"Draft not found: {draft_id}",
            )

        # Convert dict response to DraftDetails model for validation and docs
        return DraftDetails(
            draft_id=draft_details["draft_id"],
            league_id=draft_details["league_id"],
            status=draft_details["status"],
            settings=DraftSettings(
                teams=draft_details["settings"]["teams"],
                rounds=draft_details["settings"]["rounds"],
                reversal_round=draft_details["settings"].get("reversal_round"),
                type=draft_details["settings"]["type"],
                slots_qb=draft_details["settings"].get("slots_qb", 1),
                slots_super_flex=draft_details["settings"].get("slots_super_flex", 0),
            ),
            metadata=DraftMetadata(
                name=draft_details["metadata"].get("name"),
                scoring_type=draft_details["metadata"].get("scoring_type"),
            ),
            draft_order=draft_details["draft_order"],
            roster_to_user=draft_details["roster_to_user"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching draft details: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {str(e)}"
        )


@app.get(
    "/api/v1/drafts/{draft_id}/league-settings",
    response_model=LeagueSettingsResponse,
    responses={
        200: {"description": "Successfully retrieved league settings"},
        404: {"model": ErrorResponse, "description": "Draft or league not found"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    summary="Get league scoring settings",
    description="Returns league settings including scoring format (PPR/Half-PPR/Standard) for ADP matching",
    tags=["Drafts"],
)
@shared_draft_limit
def get_league_settings(request: Request, draft_id: str):
    """Get league settings for a draft, including scoring format.

    This endpoint determines the league's scoring format to match appropriate
    ADP data. Returns PPR, Half-PPR, or Standard based on the league's
    points-per-reception setting.

    - **draft_id**: Sleeper draft ID (required path parameter)
    """
    logger.info(f"Fetching league settings for draft {draft_id}")

    try:
        # Get draft details to find league_id
        draft_details = sleeper_client.get_draft_details(draft_id)
        if not draft_details:
            raise HTTPException(
                status_code=404,
                detail=f"Draft not found: {draft_id}",
            )

        league_id = draft_details["league_id"]

        # Get scoring format
        scoring_format = sleeper_client.get_scoring_format(league_id)
        if not scoring_format:
            raise HTTPException(
                status_code=404,
                detail=f"Could not determine scoring format for league: {league_id}",
            )

        # Get full league info
        league_info = sleeper_client.get_league_info(league_id)
        roster_positions = league_info.get("roster_positions", []) if league_info else []
        total_rosters = league_info.get("total_rosters", 12) if league_info else 12

        return LeagueSettingsResponse(
            draft_id=draft_id,
            league_id=league_id,
            settings=LeagueSettings(
                league_id=league_id,
                scoring_format=scoring_format,
                roster_positions=roster_positions,
                total_rosters=total_rosters,
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching league settings: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {str(e)}"
        )


@app.get(
    "/api/v1/leagues/{league_id}/settings",
    response_model=LeagueSettings,
    responses={
        200: {"description": "Successfully retrieved league settings"},
        404: {"model": ErrorResponse, "description": "League not found"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    summary="Get league settings by league ID",
    description="Returns league settings including scoring format and roster positions",
    tags=["Leagues"],
)
def get_league_settings_by_id(league_id: str):
    """Get league settings directly by league ID.

    Returns roster positions, scoring format, and team count.

    - **league_id**: Sleeper league ID (required path parameter)
    """
    logger.info(f"Fetching settings for league {league_id}")

    try:
        league_info = sleeper_client.get_league_info(league_id)
        if not league_info:
            raise HTTPException(
                status_code=404,
                detail=f"League not found: {league_id}",
            )

        scoring_format = sleeper_client.get_scoring_format(league_id) or "ppr"
        roster_positions = league_info.get("roster_positions", [])
        total_rosters = league_info.get("total_rosters", 12)

        return LeagueSettings(
            league_id=league_id,
            scoring_format=scoring_format,
            roster_positions=roster_positions,
            total_rosters=total_rosters,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching league settings: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {str(e)}"
        )


@app.get(
    "/api/v1/drafts/{draft_id}/available-players",
    response_model=AvailablePlayersResponse,
    responses={
        200: {"description": "Successfully retrieved available players"},
        404: {"model": ErrorResponse, "description": "Draft not found"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    summary="Get available (undrafted) players for a draft",
    description="Returns all players who have not been drafted yet, with optional position filtering",
    tags=["Drafts"],
)
@shared_draft_limit
def get_available_players(
    request: Request,
    draft_id: str,
    position: Optional[str] = Query(None, description="Filter by position (RB, WR, QB, TE, etc.)"),
    limit: int = Query(100, description="Maximum number of players to return", le=500),
):
    """
    Get available (undrafted) players for draft recommendations.

    - **draft_id**: Sleeper draft ID
    - **position**: Optional position filter (e.g., 'RB', 'WR', 'QB', 'TE')
    - **limit**: Max players to return (default: 100, max: 500)

    Returns players sorted by recommendation score (integrated with ADP in future versions).
    """
    logger.info(f"Fetching available players for draft {draft_id}")

    try:
        # Get all picks made in this draft
        draft_picks = sleeper_client.get_draft_picks(draft_id)
        drafted_player_ids = {pick.player_id for pick in draft_picks}

        logger.info(f"Found {len(drafted_player_ids)} drafted players")

        # Load player universe
        all_players = load_player_universe()

        if not all_players:
            # Fallback: fetch from Sleeper if no local data
            logger.warning("No local player data, fetching from Sleeper...")
            all_players = sleeper_client.get_players()
            if all_players:
                save_player_universe(all_players)

        if not all_players:
            raise HTTPException(
                status_code=500,
                detail="Unable to load player data",
            )

        # Filter out drafted players
        available = {
            pid: player
            for pid, player in all_players.items()
            if pid not in drafted_player_ids
        }

        logger.info(f"Found {len(available)} available players")

        # Apply position filter if specified
        if position:
            position_upper = position.upper()
            available = {
                pid: player
                for pid, player in available.items()
                if player.get("position") == position_upper
            }
            logger.info(f"Filtered to {len(available)} {position} players")

        # Convert to list and limit results
        player_list = []
        for pid, player in list(available.items())[:limit]:
            player_list.append(PlayerSummary(
                player_id=pid,
                name=f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
                position=player.get("position") or "UNKNOWN",
                team=player.get("team") or "FA",
                age=player.get("age"),
                years_exp=player.get("years_exp"),
            ))

        return AvailablePlayersResponse(
            draft_id=draft_id,
            total_available=len(available),
            position_filter=position,
            players=player_list,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching available players: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {str(e)}"
        )


@app.get(
    "/api/v1/drafts/{draft_id}/available-by-position",
    response_model=AvailableByPositionResponse,
    responses={
        404: {"description": "Draft not found"},
        500: {"description": "Server error"},
    },
    summary="Get available players by position with ADP delta analysis",
    description="Returns top available players at each position sorted by ADP delta relative to current overall pick",
    tags=["Drafts"],
)
@shared_draft_limit
def get_available_by_position(
    request: Request,
    draft_id: str,
    limit: int = Query(default=20, ge=1, le=100, description="Max players per position"),
    adp_source: str = Query(default="draftsharks", pattern="^(sleeper|draftsharks)$", description="Which ADP source drives adp_delta"),
) -> AvailableByPositionResponse:
    """Get available players grouped by position with ADP delta analysis.

    Returns the top available players at each position sorted by ADP delta
    relative to the current overall pick in the draft. Helps identify best
    value picks available right now.

    Args:
        draft_id: The draft ID
        limit: Maximum players to return per position (1-100, default 20)
        adp_source: Which ADP source to use for adp_delta ("sleeper" or "draftsharks")

    Returns:
        Available players grouped by position with ADP deltas
    """
    from collections import defaultdict

    correlation_id = new_correlation_id()
    start = time.time()
    try:
        logger.info(f"Fetching available players by position for draft {draft_id}")

        # Step 1: Get draft details for league_id
        draft_details = sleeper_client.get_draft_details(draft_id)
        if not draft_details:
            raise HTTPException(404, f"Draft not found: {draft_id}")

        league_id = draft_details.get("league_id")

        # Step 2: Get all picks to determine current pick and drafted players
        draft_picks = sleeper_client.get_draft_picks(draft_id)
        drafted_player_ids = {pick.player_id for pick in draft_picks}
        current_overall_pick = draft_picks[-1].pick_no + 1 if draft_picks else 1
        current_round = draft_picks[-1].round if draft_picks else 1
        # Step 3: Get scoring format for ADP matching
        scoring_format = sleeper_client.get_scoring_format(league_id) or "ppr"

        # Resolve league type (redraft/keeper/dynasty), superflex, and TE premium
        # so DraftSharks rankings reflect how this league actually drafts, not
        # just its PPR/half-PPR/standard scoring format.
        league_info = sleeper_client.get_league_info(league_id) or {}
        league_type = str(league_info.get("settings", {}).get("type", 0))
        slots_super_flex = draft_details.get("settings", {}).get("slots_super_flex", 0) or 0
        slots_qb = draft_details.get("settings", {}).get("slots_qb", 1) or 1
        is_superflex = slots_super_flex > 0 or slots_qb > 1
        is_te_premium = league_info.get("scoring_settings", {}).get("bonus_rec_te", 0) > 0

        # Step 4: Load player universe
        all_players = load_player_universe()
        if not all_players:
            all_players = sleeper_client.get_players()
            if all_players:
                save_player_universe(all_players)

        if not all_players:
            raise HTTPException(500, "Unable to load player data")

        # Step 5: Filter available players and enrich with Sleeper ADP
        available_by_position = defaultdict(list)
        positions = ["QB", "RB", "WR", "TE", "K", "DEF"]

        # Load Sleeper projections for ADP/points (24-hour cache, keyed by player_id).
        # projected_pts/avg_ppg always come from here regardless of adp_source, since
        # no other ADP provider supplies points projections.
        _avail_year = int(draft_details.get("season", 2026))
        sleeper_proj = sleeper_projections_client.fetch_projections(_avail_year, scoring_format)

        # Resolve which ADP source drives adp_delta. For DraftSharks, match the
        # league's actual format (dynasty/keeper/superflex/TE premium) rather than
        # always using the plain redraft rankings. Non-Sleeper sources fall back
        # to Sleeper ADP silently if their snapshot is missing.
        draftsharks_ranking_key = adp_sources.resolve_draftsharks_ranking_key(
            scoring_format, league_type, is_superflex, is_te_premium
        )
        ranking_key = draftsharks_ranking_key if adp_source == "draftsharks" else scoring_format
        adp_map, tier_map, adp_source_available = adp_sources.get_adp_map(
            adp_source, ranking_key, all_players, sleeper_proj
        )
        if adp_source != "sleeper" and not adp_source_available:
            adp_map, tier_map, _ = adp_sources.get_adp_map("sleeper", scoring_format, all_players, sleeper_proj)

        environment_map = environment_score.get_environment_map()

        for player_id, player_data in all_players.items():
            # Skip drafted players
            if player_id in drafted_player_ids:
                continue

            position = player_data.get("position")
            if not position or position not in positions:
                continue

            # Skip inactive players (avoids name collisions with retired/FA players)
            if not player_data.get("active"):
                continue

            # Build player name
            first = player_data.get("first_name", "")
            last = player_data.get("last_name", "")
            player_name = f"{first} {last}".strip()
            if not player_name:
                continue

            # Look up ADP directly by player_id from the active source's map.
            # projected_pts/avg_ppg still come from Sleeper's own projection regardless.
            _proj = sleeper_proj.get(player_id)
            adp_value = adp_map.get(player_id)

            # Skip players without ADP data — filters out irrelevant depth/practice players
            if adp_value is None:
                continue

            # Calculate ADP delta: current_overall_pick - adp_ppr
            # Positive = player available later than ADP (value)
            # Negative = player expected earlier (reaching if drafted now)
            adp_delta = current_overall_pick - adp_value

            # Create player detail
            player_tier = tier_map.get(player_id)
            team = player_data.get("team") or "FA"
            player_environment = environment_map.get(team)
            available_player = AvailablePlayerDetail(
                player_id=player_id,
                player_name=player_name,
                position=position,
                team=team,
                age=player_data.get("age"),
                years_exp=player_data.get("years_exp"),
                adp_ppr=adp_value,
                adp_delta=adp_delta,
                projected_pts=round(_proj.projected_pts, 1) if _proj else None,
                avg_ppg=round(_proj.avg_ppg, 1) if _proj else None,
                tier=player_tier.get("tier") if player_tier else None,
                positional_tier=player_tier.get("positional_tier") if player_tier else None,
                environment_rank=player_environment.get("rank") if player_environment else None,
                environment_score=player_environment.get("score") if player_environment else None
            )

            available_by_position[position].append(available_player)

        # Step 6: Sort each position by tier (ascending), then environment score
        # (descending) to break ties within a tier, then ADP delta (descending)
        # as a final tiebreak. Missing data always sorts last within its level.
        for position in available_by_position:
            available_by_position[position].sort(
                key=lambda p: (
                    p.tier is None, p.tier or 0,
                    p.environment_score is None, -(p.environment_score or 0),
                    p.adp_delta is None, -(p.adp_delta or 0),
                )
            )

        # Step 7: Limit to top N per position
        limited_by_position = {}
        for position in positions:
            limited_by_position[position] = available_by_position[position][:limit]

        logger.info(
            f"Returning available players by position for draft {draft_id} "
            f"at pick {current_overall_pick}"
        )

        total_duration_ms = round((time.time() - start) * 1000, 1)
        logger.info(
            "enriched response ready",
            extra={
                "event": "enriched_response_ready",
                "endpoint": "available-by-position",
                "draft_id": draft_id,
                "total_duration_ms": total_duration_ms,
            },
        )

        return AvailableByPositionResponse(
            draft_id=draft_id,
            current_overall_pick=current_overall_pick,
            current_round=current_round,
            scoring_format=scoring_format,
            limit=limit,
            players_by_position=limited_by_position,
            adp_source=adp_source,
            adp_source_available=adp_source_available,
            ranking_key=ranking_key if adp_source == "draftsharks" else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching available by position: {e}", exc_info=True)
        raise HTTPException(500, f"Internal server error: {str(e)}")


@app.get(
    "/api/v1/drafts/{draft_id}/users/{user_id}/roster",
    response_model=UserRosterResponse,
    responses={
        200: {"description": "Successfully retrieved user roster"},
        404: {"model": ErrorResponse, "description": "Draft or user not found"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    summary="Get user's roster grouped by position",
    description="Returns a specific user's draft picks organized by position with strength analysis",
    tags=["Drafts"],
)
@shared_draft_limit
def get_user_roster(request: Request, draft_id: str, user_id: str):
    """
    Get user's drafted roster grouped by position.

    Returns picks organized by position (QB, RB, WR, TE, K, DEF) with:
    - Full pick details for each position
    - Position needs analysis (what positions need more players)
    - Draft slot information

    This is used for generating draft recommendations based on team construction.

    - **draft_id**: Sleeper draft ID (required path parameter)
    - **user_id**: Sleeper user ID (required path parameter)
    """
    logger.info(f"Fetching roster for user {user_id} in draft {draft_id}")

    try:
        # Fetch all picks from draft
        all_picks = sleeper_client.get_draft_picks(draft_id)

        if not all_picks:
            all_picks = []

        # Filter picks to only this user
        user_picks = [pick for pick in all_picks if pick.user_id == user_id]

        # Get draft details to find user's draft slot
        draft_details = sleeper_client.get_draft_details(draft_id)
        draft_slot = 0
        if draft_details:
            draft_order = draft_details.get("draft_order", [])
            for idx, uid in enumerate(draft_order):
                if uid == user_id:
                    draft_slot = idx + 1  # Convert 0-indexed to 1-indexed
                    break

        # Group picks by position
        from collections import defaultdict

        picks_by_position = defaultdict(list)
        for pick in user_picks:
            pick_detail = PickDetail(
                pick_no=pick.pick_no,
                round=pick.round,
                user_id=pick.user_id,
                player_id=pick.player_id,
                player_name=pick.player_name,
                position=pick.position,
                team=pick.team,
                timestamp=pick.timestamp.isoformat(),
            )
            picks_by_position[pick.position].append(pick_detail)

        # Calculate current round (round of last pick, or 1 if no picks)
        current_round = max((pick.round for pick in user_picks), default=1)

        # Calculate current pick number for ADP value scoring
        # Use the actual pick number from the most recent draft pick
        current_pick_number = all_picks[-1].pick_no + 1 if all_picks else 1

        # Get available players by position for value calculation
        available_by_position = None
        if current_pick_number:
            try:
                from collections import defaultdict

                drafted_ids = {p.player_id for p in all_picks}
                all_players = load_player_universe()

                if all_players:
                    available_by_position = defaultdict(list)
                    for pid, player in all_players.items():
                        if pid not in drafted_ids and player.get("active"):
                            pos = player.get("position")
                            if pos:
                                available_by_position[pos].append(
                                    {
                                        "id": pid,
                                        "name": f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
                                    }
                                )
            except Exception as e:
                logger.debug(f"Could not fetch available players for value calc: {e}")

        # Calculate position needs with ADP enhancement
        position_summary = _calculate_position_needs(
            picks_by_position,
            current_round,
            draft_id=draft_id,
            current_pick=current_pick_number,
            available_players=available_by_position,
        )

        # Ensure all positions are in the response
        for position in ["QB", "RB", "WR", "TE", "K", "DEF"]:
            if position not in picks_by_position:
                picks_by_position[position] = []
            if position not in position_summary:
                position_summary[position] = PositionNeed(
                    count=0, needs_more=True, priority="medium"
                )

        return UserRosterResponse(
            draft_id=draft_id,
            user_id=user_id,
            draft_slot=draft_slot,
            total_picks=len(user_picks),
            league_name=draft_details.get("metadata", {}).get("name") if draft_details else None,
            roster_by_position=dict(picks_by_position),
            position_summary=position_summary,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user roster: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {str(e)}"
        )


def _calculate_position_needs(
    picks_by_position: dict,
    current_round: int,
    draft_id: Optional[str] = None,
    current_pick: Optional[int] = None,
    available_players: Optional[dict] = None,
) -> dict[str, PositionNeed]:
    """Calculate position needs for draft recommendations with ADP-based value scoring.

    Args:
        picks_by_position: User's picks grouped by position
        current_round: Current draft round (inferred from latest pick)
        draft_id: Optional draft ID for fetching league settings
        current_pick: Optional current pick number for ADP value calculation
        available_players: Optional dict mapping position to list of available player dicts

    Returns:
        Dict mapping position to PositionNeed analysis
    """
    # Standard roster requirements
    targets = {
        "QB": {"min": 1, "target": 1, "max": 2},
        "RB": {"min": 2, "target": 3, "max": 4},
        "WR": {"min": 2, "target": 3, "max": 4},
        "TE": {"min": 1, "target": 1, "max": 2},
        "K": {"min": 0, "target": 1, "max": 1},
        "DEF": {"min": 0, "target": 1, "max": 1},
    }

    needs = {}

    # Try to get scoring format for ADP matching
    scoring_format = None
    if draft_id:
        try:
            draft_details = sleeper_client.get_draft_details(draft_id)
            if draft_details:
                league_id = draft_details.get("league_id")
                if league_id:
                    scoring_format = sleeper_client.get_scoring_format(league_id)
                    logger.debug(f"Using scoring format: {scoring_format}")
        except Exception as e:
            logger.debug(f"Could not determine scoring format: {e}")

    for position, requirements in targets.items():
        count = len(picks_by_position.get(position, []))

        # Determine if more needed
        needs_more = count < requirements["target"]

        # Calculate base priority
        if count == 0 and position in ["QB", "RB", "WR", "TE"]:
            # No player at this critical position
            if current_round >= 8:
                base_priority = "high"  # Late in draft, need starter
            else:
                base_priority = "medium"
        elif count < requirements["min"]:
            base_priority = "high"  # Below minimum
        elif count < requirements["target"]:
            base_priority = "medium"  # Below target
        else:
            base_priority = "low"  # At or above target

        # ADP-based value adjustment
        final_priority = base_priority
        value_score = 0.0

        if scoring_format and current_pick and available_players:
            try:
                from src.analytics.adp_service import adp_service

                pos_available = available_players.get(position, [])
                if pos_available:
                    # Calculate positional value
                    value_score = adp_service.calculate_positional_value(
                        position, current_pick, pos_available, scoring_format
                    )

                    # Boost priority if exceptional value available
                    # value_score > 30: exceptional value (ADP 30+ picks later)
                    # value_score > 15: good value (ADP 15+ picks later)
                    if value_score > 30 and base_priority in ["medium", "low"]:
                        final_priority = "high"
                        logger.debug(
                            f"Boosted {position} priority to high (value_score: {value_score:.1f})"
                        )
                    elif value_score > 15 and base_priority == "low":
                        final_priority = "medium"
                        logger.debug(
                            f"Boosted {position} priority to medium (value_score: {value_score:.1f})"
                        )
            except Exception as e:
                logger.debug(f"ADP value calculation failed for {position}: {e}")

        needs[position] = PositionNeed(
            count=count,
            needs_more=needs_more,
            priority=final_priority,
        )

    return needs


def _transform_drafts(raw_drafts: list, user_leagues: dict = None) -> list[DraftSummary]:
    """Transform raw Sleeper API response to DraftSummary objects.

    Args:
        raw_drafts: List of draft dicts from Sleeper API
        user_leagues: Optional dict of league_id -> league dict for enriching metadata

    Returns:
        List of DraftSummary objects
    """
    user_leagues = user_leagues or {}
    summaries = []

    for draft in raw_drafts:
        try:
            league_id = draft.get("league_id", "")
            league_data = user_leagues.get(league_id)

            scoring_type = draft.get("metadata", {}).get("scoring_type")
            league_type = draft.get("metadata", {}).get("league_type")
            te_premium = None

            # Enrich scoring_type from league_data if available and draft metadata is vague
            if league_data:
                # Get league type from league settings (0=redraft, 1=keeper, 2=dynasty)
                # Sleeper stores this in settings.type on the league object
                l_type = league_data.get("settings", {}).get("type")
                if l_type is not None:
                    league_type = str(l_type)

                scoring_settings = league_data.get("scoring_settings", {})
                rec = scoring_settings.get("rec", 0)
                if rec == 1.0:
                    scoring_type = "ppr"
                elif rec == 0.5:
                    scoring_type = "half_ppr"
                elif rec == 0.0:
                    scoring_type = "standard"

                bonus_rec_te = scoring_settings.get("bonus_rec_te", 0)
                if bonus_rec_te > 0:
                    te_premium = bonus_rec_te

            # Fallback if league_type is still null/None (legacy drafts or missing league data)
            if not league_type:
                # Sometimes sleeper shoves 'dynasty_2qb' or 'keeper' into the scoring_type string
                if scoring_type and 'dynasty' in scoring_type.lower():
                    league_type = "2"
                elif scoring_type and 'keeper' in scoring_type.lower():
                    league_type = "1"
                else:
                    league_type = "0"

            # If scoring type is something like 'dynasty_2qb', clean it up since we show SFX elsewhere
            if scoring_type and ('dynasty' in scoring_type.lower() or 'keeper' in scoring_type.lower()):
                # Fallback to PPR if we couldn't resolve it from actual league settings
                scoring_type = "ppr"

            summary = DraftSummary(
                draft_id=draft.get("draft_id", ""),
                league_id=league_id,
                status=draft.get("status", "unknown"),
                settings={
                    "teams": draft.get("settings", {}).get("teams", 0),
                    "rounds": draft.get("settings", {}).get("rounds", 0),
                    "reversal_round": draft.get("settings", {}).get("reversal_round"),
                    "type": draft.get("type", "snake"),
                    "slots_qb": draft.get("settings", {}).get("slots_qb", 1),
                    "slots_super_flex": draft.get("settings", {}).get("slots_super_flex", 0),
                },
                metadata={
                    "name": draft.get("metadata", {}).get("name"),
                    "scoring_type": scoring_type,
                    "league_type": league_type,
                    "te_premium": te_premium,
                }
                if draft.get("metadata")
                else None,
                start_time=draft.get("start_time"),
                sport=draft.get("sport", "nfl"),
                season=draft.get("season", ""),
            )
            summaries.append(summary)
        except Exception as e:
            logger.warning(f"Skipping malformed draft: {e}")
            continue

    return summaries


def _filter_orphaned_drafts(
    draft_summaries: list[DraftSummary],
    user_leagues: dict,
) -> list[DraftSummary]:
    """Remove drafts whose parent league has been deleted on Sleeper.

    Sleeper's drafts endpoint returns all drafts historically, even after a
    league is deleted.  The leagues endpoint, however, only returns active
    (non-deleted) leagues.  Any draft whose league_id doesn't appear in
    user_leagues is therefore orphaned and should be hidden.

    Drafts without a league_id (rare standalone/mock drafts) are kept.

    Args:
        draft_summaries: List of DraftSummary objects.
        user_leagues: Dict of {league_id: league_data} for active leagues.

    Returns:
        Filtered list with orphaned drafts removed.
    """
    if not user_leagues:
        # If we couldn't fetch leagues at all, show everything rather than
        # accidentally hiding real drafts.
        return draft_summaries

    active_league_ids = set(user_leagues.keys())
    kept = []
    dropped = 0
    for draft in draft_summaries:
        league_id = draft.league_id
        if not league_id or league_id in active_league_ids:
            kept.append(draft)
        else:
            dropped += 1
            logger.debug(
                f"Hiding orphaned draft {draft.draft_id} "
                f"(league {league_id} not in active leagues)"
            )
    if dropped:
        logger.info(f"Filtered out {dropped} orphaned draft(s) from deleted leagues")
    return kept


def _sort_drafts(drafts: list[DraftSummary]) -> list[DraftSummary]:
    """Sort drafts by status priority and start time.

    Priority: in_progress (1) > pre_draft (2) > complete (3)
    Then by start_time (newest first)

    Args:
        drafts: List of DraftSummary objects

    Returns:
        Sorted list of drafts
    """
    # Status priority: in_progress (1) > pre_draft (2) > complete (3)
    status_priority = {"in_progress": 1, "pre_draft": 2, "complete": 3}

    def sort_key(draft):
        priority = status_priority.get(draft.status, 999)
        # Use negative start_time so newest comes first (None sorts to end)
        start = -draft.start_time if draft.start_time else float("inf")
        return (priority, start)

    return sorted(drafts, key=sort_key)


# ============================================================================
# VOR (Value Over Replacement) Analysis Endpoints
# ============================================================================

# Initialize VOR calculator (lazy-loaded on first use)
vor_calculator = None

def get_vor_calculator():
    """Get or initialize VOR calculator, enriching it with projections when available."""
    global vor_calculator
    if vor_calculator is None:
        from src.services.vor_calculator import VORCalculator
        from src.data_sources.projections_client import ProjectionsClient
        from pathlib import Path
        import glob

        repo_root = Path(__file__).parent.parent.parent
        data_dir = repo_root / "data/players"

        # Find the latest PPR ADP file
        players_file = None
        if data_dir.exists():
            ppr_files = sorted(glob.glob(str(data_dir / "ppr_*.json")), reverse=True)
            if ppr_files:
                players_file = ppr_files[0]

        if not players_file:
            debug_dir = repo_root / "debug_html"
            if debug_dir.exists():
                ppr_files = sorted(glob.glob(str(debug_dir / "ppr_*.json")), reverse=True)
                if ppr_files:
                    players_file = ppr_files[0]

        if not players_file:
            raise FileNotFoundError(f"No player data found in {data_dir}")

        logger.info(f"Loading VOR player data from: {players_file}")
        vor_calculator = VORCalculator(players_file)

        # Try to enrich with projections (2025 preferred, graceful fallback)
        proj_dir = repo_root / "data/projections"
        for season in (2025, 2026):
            proj_file = proj_dir / f"projections_{season}.json"
            if proj_file.exists():
                try:
                    proj_client = ProjectionsClient(str(proj_file))
                    matched = vor_calculator.load_projections(proj_client)
                    logger.info(
                        f"Projections loaded from {proj_file.name}: "
                        f"{matched} players matched"
                    )
                    break  # use the first season that works
                except Exception as e:
                    logger.warning(f"Could not load projections from {proj_file}: {e}")

    return vor_calculator


@app.get(
    "/api/v1/draft/{draft_id}/vor",
    response_model=VORAnalysisResponse,
    responses={
        200: {"description": "VOR analysis for available players"},
        404: {"model": ErrorResponse, "description": "Draft not found"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    summary="Get VOR analysis for draft",
    tags=["Draft Analysis"],
)
@shared_draft_limit
def get_draft_vor_analysis(
    request: Request,
    draft_id: str,
    limit_per_position: int = 10,
    vor_mode: str = "replacement_rank",
):
    """
    Get VOR (Value Over Replacement) analysis for available players in a draft.

    Returns top 10 recommendations per position, ranked by VOR score (highest value first).

    Args:
        draft_id: Draft ID
        limit_per_position: Maximum recommendations per position (default 10)

    Returns:
        VORAnalysisResponse with top recommendations by position and replacement levels
    """
    correlation_id = new_correlation_id()
    start = time.time()
    try:
        # Fetch draft details
        draft = sleeper_client.get_draft_details(draft_id)
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")

        league_id = draft.get("league_id")

        # Fetch draft picks
        available = sleeper_client.get_draft_picks(draft_id)
        if not available:
            available = []

        # Get drafted player IDs so we can exclude them
        drafted_player_ids = set()
        for pick in available:
            if pick.player_id:
                drafted_player_ids.add(pick.player_id)

        # Determine if we're in the last 2 rounds (suppresses DEF/K until then)
        import math
        # ! don't need to do a calculation on picks right? We could pass the current round # in
        _teams = draft.get("settings", {}).get("teams", 12)
        _total_rounds = draft.get("settings", {}).get("rounds", 15)
        _picks_made = len(available)
        _current_round = math.ceil(_picks_made / _teams) if _picks_made > 0 else 1
        _in_late_rounds = _current_round >= (_total_rounds - 1)
        LATE_ROUND_POSITIONS = {"DEF", "K"}

        # Load Sleeper projections (24-hour cache) — provides both ADP and avg PPG
        scoring_format = sleeper_client.get_scoring_format(league_id) or "ppr"
        _vor_year = int(draft.get("season", 2026))
        sleeper_proj = sleeper_projections_client.fetch_projections(_vor_year, scoring_format)

        # Build VOR calculator from Sleeper projections (no FantasyPros file needed)
        from src.services.vor_calculator import VORCalculator
        vor = VORCalculator()
        vor.load_sleeper_projections(sleeper_proj)

        # Replacement level rank per position: last drafted starter (num_teams × starters)
        _num_teams = draft.get("settings", {}).get("teams", 12)
        _starters_per_pos = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DEF": 1}
        _replacement_ranks = {pos: _num_teams * n for pos, n in _starters_per_pos.items()}

        # Build valid player pool: top VOR_POOL_SIZE per position by ADP delta.
        # Sleeper projections are already keyed by player_id — no name matching needed.
        current_overall_pick = available[-1].pick_no + 1 if available else 1
        VOR_POOL_SIZE = 10
        _by_pos: dict[str, list[tuple[float, str]]] = {}
        for _pid, _proj in sleeper_proj.items():
            if _pid in drafted_player_ids:
                continue
            _delta = current_overall_pick - _proj.adp
            _by_pos.setdefault(_proj.position, []).append((_delta, _pid))

        valid_available_ids: set[str] = set()
        for _pos, _entries in _by_pos.items():
            _entries.sort(key=lambda x: x[0], reverse=True)
            for _, _pid in _entries[:VOR_POOL_SIZE]:
                valid_available_ids.add(_pid)

        # Iterate directly over Sleeper projections — player_id is already the Sleeper ID
        recommendations = []
        for player_id, proj in sleeper_proj.items():
            if player_id not in valid_available_ids:
                continue
            if player_id in drafted_player_ids:
                continue
            # Suppress DEF/K until the last 2 rounds
            if proj.position in LATE_ROUND_POSITIONS and not _in_late_rounds:
                continue

            try:
                _rank = _replacement_ranks.get(proj.position, 12)
                vor_score = vor.calculate_vor(
                    position=proj.position,
                    adp=proj.adp,
                    projected_pts=proj.projected_pts,
                    replacement_rank=_rank,
                    mode=vor_mode,
                )

                if vor_mode == "next_available":
                    replacement_player = vor.get_next_available_player(proj.position, proj.projected_pts)
                else:
                    replacement_player = vor.get_replacement_player(proj.position, _rank)
                replacement_pts = replacement_player.get("projected_pts") if replacement_player else None

                recommendations.append({
                    "league_id": league_id,
                    "draft_id": draft_id,
                    "player_id": player_id,
                    "player_name": proj.player_name,
                    "position": proj.position,
                    "adp_overall": proj.adp,
                    "replacement_level_adp": replacement_pts,
                    "vor_score": vor_score,
                    "interpretation": vor._interpret_vor(vor_score, basis="projection"),
                    "picks_remaining": len(sleeper_proj) - len(drafted_player_ids),
                    "projected_points": proj.projected_pts,
                    "avg_ppg": round(proj.avg_ppg, 1),
                    "vor_basis": vor_mode,
                    "replacement_player_id": replacement_player.get("player_id") if replacement_player else None,
                    "replacement_player_name": replacement_player.get("player_name") if replacement_player else None,
                    "replacement_player_team": replacement_player.get("team") if replacement_player else None,
                    "replacement_player_points": replacement_pts
                })
            except Exception as e:
                logger.warning(f"Could not calculate VOR for {proj.player_name}: {e}")
                continue

        logger.info(
            f"VOR: {len(drafted_player_ids)} drafted, {len(recommendations)} recommendations, "
            f"projections_loaded={bool(vor.projection_groups)}"
        )

        # Group by position and sort by VOR within each position
        by_position = {}
        for rec in recommendations:
            pos = rec['position']
            if pos not in by_position:
                by_position[pos] = []
            by_position[pos].append(rec)

        # Sort each position by VOR (descending) and limit to top N per position
        all_top_recommendations = []
        for pos in ['QB', 'RB', 'WR', 'TE', 'K', 'DEF']:
            if pos in by_position:
                sorted_pos = sorted(by_position[pos], key=lambda x: x['vor_score'], reverse=True)
                all_top_recommendations.extend(sorted_pos[:limit_per_position])

        # Re-sort all recommendations by VOR globally for consistency
        all_top_recommendations.sort(key=lambda x: x['vor_score'], reverse=True)

        if not all_top_recommendations:
            raise HTTPException(status_code=400, detail="No available players to analyze")

        # Replacement level summary: projected pts of the Nth player per position
        replacement_by_position = {}
        for pos in ['QB', 'RB', 'WR', 'TE', 'K', 'DEF']:
            try:
                rank = _replacement_ranks.get(pos, 12)
                replacement_by_position[pos] = vor.get_replacement_player(pos, rank).get("projected_pts", 0.0)
            except Exception:
                pass

        total_duration_ms = round((time.time() - start) * 1000, 1)
        logger.info(
            "enriched response ready",
            extra={
                "event": "enriched_response_ready",
                "endpoint": "draft-vor",
                "draft_id": draft_id,
                "total_duration_ms": total_duration_ms,
            },
        )

        return VORAnalysisResponse(
            league_id=league_id,
            draft_id=draft_id,
            recommendations=all_top_recommendations,
            top_value_pick=all_top_recommendations[0],
            replacement_level_by_position=replacement_by_position,
            projections_loaded=bool(vor.projection_groups),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating VOR for draft {draft_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to calculate VOR")

@app.get(
    "/api/v1/draft/{draft_id}/player/{player_id}/vor",
    response_model=VORPlayerDetail,
    responses={
        200: {"description": "VOR for specific player"},
        404: {"model": ErrorResponse, "description": "Player not found"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    summary="Get VOR for specific player",
    tags=["Draft Analysis"],
)
@shared_draft_limit
def get_player_vor(request: Request, draft_id: str, player_id: str):
    """
    Get VOR analysis for a specific player.

    Args:
        draft_id: Draft ID (for context)
        player_id: Player ID to analyze

    Returns:
        VORPlayerDetail with VOR score and interpretation
    """
    try:
        vor = get_vor_calculator()

        # Find player in our dataset
        player = next(
            (p for p in vor.players if p.get("player_id") == player_id),
            None
        )

        if not player:
            raise HTTPException(status_code=404, detail="Player not found")

        replacement_level = vor.get_replacement_level(
            player['position'],
            replacement_percentile=50
        )

        projected_pts = player.get('projected_pts')
        vor_score = vor.calculate_vor(
            player['position'],
            player['adp_overall'],
            projected_pts=projected_pts,
        )
        basis = "projection" if projected_pts is not None and vor.projection_groups else "adp"

        return VORPlayerDetail(
            player_id=player_id,
            player_name=player['player_name'],
            position=player['position'],
            adp_overall=player['adp_overall'],
            replacement_level_adp=replacement_level,
            vor_score=vor_score,
            interpretation=vor._interpret_vor(vor_score, basis=basis),
            projected_points=projected_pts,
            vor_basis=basis,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating VOR for player {player_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to calculate VOR")


@app.get(
    "/api/v1/drafts/{draft_id}/stream",
    summary="Stream live draft events via SSE",
    tags=["Draft Analysis"],
)
async def stream_draft_events(draft_id: str):
    """Server-Sent Events stream for a live draft.

    Emits:
      event: pick   — a new pick was made (data: pick JSON)
      event: status — draft status changed (data: {"status": "..."})
      : keepalive   — sent every ~15s to prevent proxy timeouts
    """
    # Subscribe BEFORE returning the StreamingResponse so that a capacity
    # rejection surfaces as a normal 429, not as a broken stream.
    try:
        queue = await draft_broadcaster.subscribe(draft_id)
    except BroadcasterCapacityError as exc:
        raise HTTPException(status_code=429, detail=str(exc))

    async def event_generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20.0)
                    if event["type"] == "keepalive":
                        yield ": keepalive\n\n"
                    elif event["type"] == "pick":
                        yield f"event: pick\ndata: {json.dumps(event['data'])}\n\n"
                    elif event["type"] == "status":
                        yield f"event: status\ndata: {json.dumps(event['data'])}\n\n"
                        if event["data"].get("status") == "complete":
                            break
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await draft_broadcaster.unsubscribe(draft_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# In-Season Matchup Recommendations endpoints
#
# All routes live under /api/v1/in-season/ and are kept entirely separate from
# the draft endpoints above. Optional prediction services (projections store /
# matchup grade service) are imported defensively: if they are not wired up yet
# (concurrent tasks), the roster endpoints still return rosters with the
# projection/matchup fields omitted rather than failing.
# ---------------------------------------------------------------------------


def _get_matchup_grade_service():
    """Return a MatchupGradeService instance, or None if unavailable.

    The matchup grade service (Task 5) may not be wired up yet. Import it
    defensively so roster enrichment degrades gracefully instead of 500ing.
    """
    try:
        from src.services.matchup_grade import MatchupGradeService

        return MatchupGradeService()
    except Exception as e:  # pragma: no cover - optional dependency
        logger.debug(f"Matchup grade service unavailable: {e}")
        return None


def _gsis_to_sleeper_map(all_players):
    """Build a map from nflverse ``gsis_id`` -> Sleeper ``player_id``.

    The projection parquet is keyed by nflverse player ids (e.g. "00-0033873"),
    but Sleeper rosters are keyed by Sleeper ids (e.g. "4046"). Each Sleeper
    player entry carries its nflverse id in the ``gsis_id`` field — sometimes
    with a stray leading/trailing space — so we strip it before indexing. This
    bridge lets the serving layer attach nflverse-keyed projections to a
    Sleeper-keyed roster.
    """
    mapping = {}
    for sleeper_id, player_data in (all_players or {}).items():
        if not isinstance(player_data, dict):
            continue
        gsis = player_data.get("gsis_id")
        if gsis is None:
            continue
        gsis = str(gsis).strip()
        if gsis:
            mapping[gsis] = str(sleeper_id)
    return mapping


def _load_week_projections(season: int, week: int, scoring_format: str, all_players=None):
    """Load projected points keyed by Sleeper player_id, or empty dict.

    Reads the projection output via projections_store (Task 5), which may not
    exist yet. Degrades gracefully to an empty mapping on any failure.

    The projection parquet is keyed by nflverse ids; when ``all_players`` (the
    Sleeper universe) is provided, each projection is re-keyed to its Sleeper
    id so roster lookups — which use Sleeper ids — resolve. Two bridges are
    tried per Sleeper player, in order:

    1. ``gsis_id`` exact match (nflverse id carried on the Sleeper entry).
    2. ``(normalized_name, position)`` fallback — many players (notably recent
       draftees) have no ``gsis_id`` on Sleeper even though nflverse has them,
       so we match the projection's ``player_name`` + ``position`` against the
       Sleeper player's normalized name + position.

    When ``all_players`` is omitted the dict stays nflverse-keyed (back-compat).
    """
    try:
        from src.data_sources.projections_store import load_projections
        from src.services.player_id_resolver import normalize_fantasypros_name

        df = load_projections(season, week, scoring_format)
        if df is None or len(df) == 0:
            return {}

        # Back-compat path: no universe -> keep the parquet's nflverse ids.
        if not all_players:
            projections = {}
            for row in df.iter_rows(named=True):
                pid = row.get("player_id")
                pts = row.get("projected_points")
                if pid is not None and pts is not None:
                    projections[str(pid)] = float(pts)
            return projections

        # Build both projection indexes from the parquet in one pass:
        #   by nflverse id, and by (normalized_name, position).
        proj_by_gsis = {}
        proj_by_name_pos = {}
        for row in df.iter_rows(named=True):
            pid = row.get("player_id")
            pts = row.get("projected_points")
            if pts is None:
                continue
            pts = float(pts)
            if pid is not None:
                proj_by_gsis[str(pid)] = pts
            name = row.get("player_name")
            position = row.get("position")
            if name and position:
                proj_by_name_pos[(normalize_fantasypros_name(name), position)] = pts

        # For each Sleeper player, attach points via gsis_id, else name+position.
        projections = {}
        for sleeper_id, player_data in all_players.items():
            if not isinstance(player_data, dict):
                continue

            gsis = player_data.get("gsis_id")
            if gsis is not None:
                pts = proj_by_gsis.get(str(gsis).strip())
                if pts is not None:
                    projections[str(sleeper_id)] = pts
                    continue  # exact match wins; skip the name fallback

            # Fallback: normalized full name + position.
            full_name = (
                f"{player_data.get('first_name', '') or ''} "
                f"{player_data.get('last_name', '') or ''}"
            ).strip()
            position = player_data.get("position")
            if full_name and position:
                pts = proj_by_name_pos.get(
                    (normalize_fantasypros_name(full_name), position)
                )
                if pts is not None:
                    projections[str(sleeper_id)] = pts

        return projections
    except Exception as e:  # pragma: no cover - optional dependency
        logger.debug(f"Projections unavailable for {season} wk{week} {scoring_format}: {e}")
        return {}


def _schedule_available(matchup_service) -> bool:
    """True when the matchup mart is loaded and non-empty.

    Bye detection relies on the schedule-backed matchup mart. When it's
    unavailable we can't distinguish "on bye" from "unknown", so callers must
    not infer a bye — otherwise a missing mart would sit every player.
    """
    if matchup_service is None:
        return False
    try:
        df = matchup_service._load()
        return df is not None and not df.is_empty()
    except Exception:  # pragma: no cover - defensive
        return False


def _opponent_for(team, season: int, week: int, matchup_service):
    """Resolve the opponent for a team's (season, week) from the matchup mart.

    ``mart_matchup_grade`` is keyed (season, week, team, opponent) and is built
    from the schedule, so it carries opponent rows even for upcoming/unplayed
    weeks. We reuse the already-cached mart on the MatchupGradeService instead
    of opening a second reader. Returns the opponent team abbreviation, or None
    when the team has no scheduled game that week (or the mart is unavailable).
    """
    if not matchup_service or not team or team == "FA":
        return None
    try:
        df = matchup_service._load()  # cached mart_matchup_grade
        if df is None or df.is_empty():
            return None
        import polars as _pl

        row = df.filter(
            (_pl.col("team") == team)
            & (_pl.col("season") == season)
            & (_pl.col("week") == week)
        )
        if row.is_empty():
            return None
        return row.to_dicts()[0].get("opponent")
    except Exception as e:  # pragma: no cover - defensive
        logger.debug(f"Opponent lookup failed for {team} {season} wk{week}: {e}")
        return None


def _resolve_nfl_week_season():
    """Resolve the current (season, week) from Sleeper NFL state.

    Falls back to (current year, 1) if the state call fails so the roster
    endpoints always return a usable season/week.
    """
    from datetime import datetime as _dt

    try:
        state = sleeper_client.get_nfl_state()
    except Exception:
        state = None

    season = None
    week = None
    if state:
        try:
            season = int(state.get("season")) if state.get("season") is not None else None
        except (TypeError, ValueError):
            season = None
        try:
            week = int(state.get("week")) if state.get("week") is not None else None
        except (TypeError, ValueError):
            week = None

    if season is None:
        season = _dt.now().year
    if week is None or week < 1:
        week = 1
    return season, week


def _build_matchup_response(player_team, opponent, season, week, matchup_service):
    """Build a MatchupGradeResponse for a player's team, or None if unavailable."""
    if not matchup_service or not player_team or player_team == "FA":
        return None
    try:
        grade = matchup_service.grade_for(player_team, opponent or "", season, week)
        if grade is None:
            return None
        return MatchupGradeResponse(
            team=getattr(grade, "team", player_team),
            opponent=getattr(grade, "opponent", opponent or ""),
            season=getattr(grade, "season", season),
            week=getattr(grade, "week", week),
            pass_matchup=getattr(grade, "pass_matchup", None),
            rush_matchup=getattr(grade, "rush_matchup", None),
            overall_matchup=getattr(grade, "overall_matchup", None),
            pass_signal=getattr(grade, "pass_signal", "neutral"),
            rush_signal=getattr(grade, "rush_signal", "neutral"),
            overall_signal=getattr(grade, "overall_signal", "neutral"),
            ol_grade=getattr(grade, "ol_grade", None),
            dl_grade=getattr(grade, "dl_grade", None),
        )
    except Exception as e:  # pragma: no cover - optional dependency
        logger.debug(f"Matchup grade lookup failed for {player_team}: {e}")
        return None


def _build_roster_player(
    player_id,
    slot,
    all_players,
    projections,
    matchup_service,
    season,
    week,
):
    """Enrich a raw Sleeper player_id into a RosterPlayer response model.

    Pulls name/position/team/injury from the cached player universe. Adds
    projected points and matchup grade when those services are available.
    """
    player_id = str(player_id)
    player_data = all_players.get(player_id) or {}

    first = player_data.get("first_name", "") or ""
    last = player_data.get("last_name", "") or ""
    player_name = f"{first} {last}".strip() or player_id

    position = player_data.get("position") or "UNKNOWN"
    team = player_data.get("team") or "FA"
    injury_status = player_data.get("injury_status")

    projected_points = projections.get(player_id)

    opponent = _opponent_for(team, season, week, matchup_service)
    matchup_grade = _build_matchup_response(
        team, opponent, season, week, matchup_service
    )

    # A player on a real NFL team with no scheduled opponent this week is on
    # bye. Free agents also have no opponent, so only a non-FA team counts; and
    # we only infer bye when the schedule mart is actually available (else a
    # missing mart would mark everyone on bye).
    on_bye = (
        team != "FA"
        and opponent is None
        and _schedule_available(matchup_service)
    )

    return RosterPlayer(
        player_id=player_id,
        player_name=player_name,
        position=position,
        team=team,
        slot=slot,
        projected_points=projected_points,
        matchup_grade=matchup_grade,
        on_bye=on_bye,
        injury_status=injury_status,
    )


def _roster_to_response(
    roster: Roster,
    league_id: str,
    season: int,
    week: int,
    all_players,
    projections,
    matchup_service,
) -> RosterResponse:
    """Convert a Sleeper Roster into an enriched RosterResponse.

    Categorizes players into starters / bench / reserve using roster_bench()
    (bench = players - starters - reserve). Starter slot labels come from the
    league's roster_positions when available, else the player's position.
    """
    bench_ids = roster_bench(roster)
    reserve_set = set(roster.reserve)

    starters = []
    for idx, pid in enumerate(roster.starters):
        pid = str(pid)
        player_data = all_players.get(pid) or {}
        # Default the slot to the player's own position; empty Sleeper starter
        # slots are represented as "0" and get a BENCH-style EMPTY label.
        if pid == "0":
            slot = "EMPTY"
        else:
            slot = player_data.get("position") or "FLEX"
        starters.append(
            _build_roster_player(
                pid, slot, all_players, projections, matchup_service, season, week
            )
        )

    bench = [
        _build_roster_player(
            pid, "BENCH", all_players, projections, matchup_service, season, week
        )
        for pid in bench_ids
    ]

    reserve = [
        _build_roster_player(
            pid, "RESERVE", all_players, projections, matchup_service, season, week
        )
        for pid in roster.reserve
    ]

    return RosterResponse(
        league_id=str(league_id),
        user_id=str(roster.owner_id),
        roster_id=str(roster.roster_id),
        week=week,
        season=season,
        starters=starters,
        bench=bench,
        reserve=reserve,
    )


def _load_in_season_players():
    """Load the player universe for in-season enrichment.

    Prefers the locally stored universe; falls back to a live Sleeper fetch
    (cached 24h) and persists it. Raises HTTP 500 if neither is available.
    """
    all_players = load_player_universe()
    if not all_players:
        logger.warning("No local player data for in-season roster, fetching from Sleeper")
        all_players = sleeper_client.get_players()
        if all_players:
            save_player_universe(all_players)

    if not all_players:
        raise HTTPException(status_code=500, detail="Unable to load player data")
    return all_players


@app.get(
    "/api/v1/in-season/{league_id}/rosters",
    response_model=LeagueRostersResponse,
    responses={
        200: {"description": "Successfully retrieved league rosters"},
        404: {"model": ErrorResponse, "description": "League not found or has no rosters"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    summary="Get all rosters in a league (in-season)",
    description=(
        "Returns every roster in a league, enriched with player names, positions, "
        "and teams. Players are categorized into starters / bench / reserve. "
        "Projected points and matchup grades are included when available."
    ),
    tags=["In-Season"],
)
def get_in_season_league_rosters(league_id: str):
    """All rosters in a league, enriched with player name/position/team.

    - **league_id**: Sleeper league ID (required path parameter)
    """
    logger.info(f"Fetching in-season rosters for league {league_id}")

    try:
        rosters = sleeper_client.get_league_rosters(league_id)
        if not rosters:
            raise HTTPException(
                status_code=404,
                detail=f"No rosters found for league: {league_id}",
            )

        season, week = _resolve_nfl_week_season()
        all_players = _load_in_season_players()
        scoring_format = sleeper_client.get_scoring_format(league_id) or "ppr"
        projections = _load_week_projections(season, week, scoring_format, all_players)
        matchup_service = _get_matchup_grade_service()

        roster_responses = [
            _roster_to_response(
                roster, league_id, season, week, all_players, projections, matchup_service
            )
            for roster in rosters
        ]

        return LeagueRostersResponse(
            league_id=str(league_id),
            week=week,
            season=season,
            rosters=roster_responses,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching in-season rosters: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {str(e)}"
        )


@app.get(
    "/api/v1/in-season/{league_id}/{user_id}/roster",
    response_model=RosterResponse,
    responses={
        200: {"description": "Successfully retrieved user roster"},
        404: {"model": ErrorResponse, "description": "League or user roster not found"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    summary="Get a specific user's roster (in-season)",
    description=(
        "Returns a specific user's roster with starters, bench, and reserve, "
        "enriched with player names/positions/teams plus projections and matchup "
        "grades when available."
    ),
    tags=["In-Season"],
)
def get_in_season_user_roster(league_id: str, user_id: str):
    """A specific user's roster: starters, bench, reserve.

    - **league_id**: Sleeper league ID (required path parameter)
    - **user_id**: Sleeper user ID / roster owner (required path parameter)
    """
    logger.info(f"Fetching in-season roster for user {user_id} in league {league_id}")

    try:
        rosters = sleeper_client.get_league_rosters(league_id)
        if not rosters:
            raise HTTPException(
                status_code=404,
                detail=f"No rosters found for league: {league_id}",
            )

        user_id_str = str(user_id)
        target = next(
            (r for r in rosters if str(r.owner_id) == user_id_str), None
        )
        if target is None:
            raise HTTPException(
                status_code=404,
                detail=f"No roster found for user {user_id} in league {league_id}",
            )

        season, week = _resolve_nfl_week_season()
        all_players = _load_in_season_players()
        scoring_format = sleeper_client.get_scoring_format(league_id) or "ppr"
        projections = _load_week_projections(season, week, scoring_format, all_players)
        matchup_service = _get_matchup_grade_service()

        return _roster_to_response(
            target, league_id, season, week, all_players, projections, matchup_service
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching in-season user roster: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {str(e)}"
        )


def _get_waiver_service():
    """Return a WaiverService wired to the Sleeper singleton, or None.

    Imported defensively so a missing/incomplete service module degrades to a
    clear error rather than an import-time failure of the whole app.
    """
    try:
        from src.services.waiver_service import WaiverService

        return WaiverService(sleeper_client)
    except Exception as e:  # pragma: no cover - optional dependency
        logger.debug(f"Waiver service unavailable: {e}")
        return None


@app.get(
    "/api/v1/in-season/{league_id}/waiver",
    response_model=WaiverResponse,
    responses={
        200: {"description": "Successfully retrieved waiver recommendations"},
        404: {"model": ErrorResponse, "description": "League not found or has no rosters"},
        503: {"model": ErrorResponse, "description": "Projections not yet available"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    summary="Get waiver-wire recommendations (in-season, Phase 1)",
    description=(
        "Returns the top free agents for a league ranked by projected points, "
        "augmented with Sleeper trending-add counts. Supports an optional "
        "position filter and a result limit (default 50). Free agents are the "
        "player universe minus every player rostered anywhere in the league."
    ),
    tags=["In-Season"],
)
def get_in_season_waiver_recommendations(
    league_id: str,
    position: Optional[str] = Query(
        None, description="Filter by position (RB, WR, QB, TE, etc.)"
    ),
    limit: int = Query(
        50, description="Maximum number of recommendations to return", ge=1, le=500
    ),
):
    """Phase 1 waiver: top FAs by projected points, augmented with trending adds.

    - **league_id**: Sleeper league ID (required path parameter)
    - **position**: Optional position filter (e.g., 'RB', 'WR', 'QB', 'TE')
    - **limit**: Max recommendations to return (default: 50, max: 500)
    """
    logger.info(
        f"Fetching in-season waiver recommendations for league {league_id} "
        f"(position={position}, limit={limit})"
    )

    try:
        # A valid league must have rosters; absent rosters -> 404.
        rosters = sleeper_client.get_league_rosters(league_id)
        if not rosters:
            raise HTTPException(
                status_code=404,
                detail=f"No rosters found for league: {league_id}",
            )

        season, week = _resolve_nfl_week_season()
        scoring_format = sleeper_client.get_scoring_format(league_id) or "ppr"

        # Distinguish "no projections at all" (503, pending) from "projections
        # exist but no free agents rank" (200 with an empty list). The service
        # returns [] for both, so probe projection availability directly.
        available_projections = _load_week_projections(season, week, scoring_format)
        if not available_projections:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Projections pending for season {season} week {week} "
                    f"({scoring_format}); try again later."
                ),
            )

        service = _get_waiver_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Waiver service unavailable",
            )

        recs = service.free_agent_ranking(
            league_id=str(league_id),
            season=season,
            week=week,
            scoring_format=scoring_format,
            position=position,
            limit=limit,
        )

        recommendations = [
            WaiverRecResponse(
                player_id=str(rec.player_id),
                player_name=rec.player_name,
                position=rec.position,
                team=rec.team,
                projected_points=rec.projected_points,
                trending_add_count=rec.trending_add_count,
                rank=rec.rank,
            )
            for rec in recs
        ]

        return WaiverResponse(
            league_id=str(league_id),
            week=week,
            season=season,
            position=position,
            recommendations=recommendations,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching in-season waiver recommendations: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {str(e)}"
        )


@app.get(
    "/api/v1/in-season/{league_id}/{user_id}/drop-add",
    response_model=DropAddResponse,
    responses={
        200: {"description": "Successfully retrieved drop/add recommendations"},
        404: {
            "model": ErrorResponse,
            "description": "League has no rosters, or user owns no roster",
        },
        503: {"model": ErrorResponse, "description": "Projections not yet available"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    summary="Get drop/add recommendations (in-season, Phase 2)",
    description=(
        "Returns ranked drop/add pairs that upgrade a user's roster: each pair "
        "swaps a bench player (drop) for a league-wide free agent (add) with a "
        "strictly positive net projected-points gain. Pairs are ranked by net "
        "gain descending, tie-broken to prefer same-position swaps. Supports a "
        "result limit (default 20)."
    ),
    tags=["In-Season"],
)
def get_in_season_drop_add_recommendations(
    league_id: str,
    user_id: str,
    limit: int = Query(
        20, description="Maximum number of recommendations to return", ge=1, le=500
    ),
):
    """Phase 2 drop/add: rank bench-for-FA swaps by net projected points gained.

    - **league_id**: Sleeper league ID (required path parameter)
    - **user_id**: Sleeper user ID / roster owner (required path parameter)
    - **limit**: Max recommendations to return (default: 20, max: 500)
    """
    logger.info(
        f"Fetching in-season drop/add recommendations for user {user_id} "
        f"in league {league_id} (limit={limit})"
    )

    try:
        # A valid league must have rosters; absent rosters -> 404.
        rosters = sleeper_client.get_league_rosters(league_id)
        if not rosters:
            raise HTTPException(
                status_code=404,
                detail=f"No rosters found for league: {league_id}",
            )

        # The user must own a roster in this league; otherwise -> 404.
        if not any(str(r.owner_id) == str(user_id) for r in rosters):
            raise HTTPException(
                status_code=404,
                detail=f"No roster for user {user_id} in league: {league_id}",
            )

        season, week = _resolve_nfl_week_season()
        scoring_format = sleeper_client.get_scoring_format(league_id) or "ppr"

        # Distinguish "no projections at all" (503, pending) from "projections
        # exist but no positive-gain swaps" (200 with an empty list). The
        # service returns [] for both, so probe projection availability directly.
        available_projections = _load_week_projections(season, week, scoring_format)
        if not available_projections:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Projections pending for season {season} week {week} "
                    f"({scoring_format}); try again later."
                ),
            )

        service = _get_waiver_service()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Waiver service unavailable",
            )

        recs = service.drop_add_optimization(
            league_id=str(league_id),
            user_id=str(user_id),
            season=season,
            week=week,
            scoring_format=scoring_format,
            limit=limit,
        )

        recommendations = [
            DropAddRecResponse(
                drop_player_id=str(rec.drop_player_id),
                drop_player_name=rec.drop_player_name,
                drop_projected_points=rec.drop_projected_points,
                add_player_id=str(rec.add_player_id),
                add_player_name=rec.add_player_name,
                add_projected_points=rec.add_projected_points,
                position=rec.position,
                net_gain=rec.net_gain,
                rank=rec.rank,
            )
            for rec in recs
        ]

        return DropAddResponse(
            league_id=str(league_id),
            user_id=str(user_id),
            week=week,
            season=season,
            recommendations=recommendations,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error fetching in-season drop/add recommendations: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {str(e)}"
        )


def _build_optimizer_players(
    roster: Roster,
    all_players,
    projections,
    season: int,
    week: int,
    matchup_service,
):
    """Build OptimizerPlayer objects for every non-reserve player on a roster.

    Position comes from the player universe, expected_points from the loaded
    projections (0.0 when unavailable so an unprojected player can still fill a
    slot as a last resort), and injury/roster status from the universe + the
    roster's reserve list. Players in the reserve list are tagged with an "IR"
    roster_status so :func:`apply_exclusions` drops them from the eligible pool.

    Bye weeks: Sleeper doesn't flag byes, but the NFL schedule does. A player on
    a real NFL team whose team has NO scheduled game that week (``_opponent_for``
    returns None) is on bye. Free agents also have no opponent, so we only treat
    "no opponent" as a bye when the player has a non-FA team — otherwise a stale
    FA label would be misread as a bye. On-bye players are excluded from the
    lineup and labeled ``SIT (BYE)``.

    Returns a tuple ``(optimizer_players, meta)`` where ``meta`` maps player_id
    to the raw enrichment dict used later to build the response rows.
    """
    from src.services.lineup_optimizer import OptimizerPlayer

    reserve_set = {str(pid) for pid in roster.reserve}

    # Bye detection needs the schedule (matchup mart). If it's unavailable we
    # can't tell bye from "unknown", so we must NOT infer bye — otherwise a
    # missing mart would sit every player.
    can_detect_bye = _schedule_available(matchup_service)

    # Cache opponent lookups per team so a 15-player roster does at most one
    # lookup per distinct team, not one per player.
    bye_by_team: dict = {}

    def _is_on_bye(team: str) -> bool:
        if not can_detect_bye:
            return False  # no schedule data -> cannot determine bye
        if not team or team == "FA":
            return False  # a free agent's lack of opponent is not a bye
        if team not in bye_by_team:
            bye_by_team[team] = _opponent_for(team, season, week, matchup_service) is None
        return bye_by_team[team]

    optimizer_players = []
    meta = {}
    # All rostered players except empty slots ("0"); reserve players are
    # included so apply_exclusions can drop them (they'll be labeled SIT below).
    for pid in roster.players:
        pid = str(pid)
        if pid == "0":
            continue

        player_data = all_players.get(pid) or {}
        first = player_data.get("first_name", "") or ""
        last = player_data.get("last_name", "") or ""
        player_name = f"{first} {last}".strip() or pid
        position = player_data.get("position") or "UNKNOWN"
        team = player_data.get("team") or "FA"
        injury_status = player_data.get("injury_status")
        roster_status = "IR" if pid in reserve_set else None
        projected_points = projections.get(pid)
        on_bye = _is_on_bye(team)

        meta[pid] = {
            "player_name": player_name,
            "position": position,
            "team": team,
            "injury_status": injury_status,
            "roster_status": roster_status,
            "projected_points": projected_points,
            "on_bye": on_bye,
        }

        optimizer_players.append(
            OptimizerPlayer(
                player_id=pid,
                position=position,
                expected_points=float(projected_points) if projected_points is not None else 0.0,
                on_bye=on_bye,
                injury_status=injury_status,
                roster_status=roster_status,
            )
        )

    return optimizer_players, meta


def _sit_reason(info) -> str:
    """Classify why a benched player is sitting.

    SIT (BYE) for a bye week, SIT (INJURY) for OUT/DOUBTFUL/IR/reserve, plain
    SIT otherwise (simply out-scored for every slot).
    """
    if info.get("on_bye"):
        return "SIT (BYE)"
    injury = (info.get("injury_status") or "").upper()
    roster_status = (info.get("roster_status") or "").upper()
    if injury in {"OUT", "DOUBTFUL", "IR"} or roster_status in {"IR", "TAXI"}:
        return "SIT (INJURY)"
    return "SIT"


@app.get(
    "/api/v1/in-season/{league_id}/{user_id}/recommendations",
    response_model=RecommendationsResponse,
    responses={
        200: {"description": "Successfully computed start/sit recommendations"},
        404: {"model": ErrorResponse, "description": "League or user roster not found"},
        503: {"model": ErrorResponse, "description": "Projections pending / unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    summary="Get start/sit recommendations (in-season)",
    description=(
        "Returns personalized START/SIT recommendations for a user's roster. "
        "Computes the optimal starting lineup via max-weight bipartite matching "
        "(not a greedy fill) against the league's roster positions, and enriches "
        "each player with an OL/DL matchup grade when available."
    ),
    tags=["In-Season"],
)
def get_in_season_recommendations(league_id: str, user_id: str):
    """Start/sit recommendations: optimal lineup via bipartite matching + matchup grade.

    - **league_id**: Sleeper league ID (required path parameter)
    - **user_id**: Sleeper user ID / roster owner (required path parameter)
    """
    logger.info(
        f"Computing start/sit recommendations for user {user_id} in league {league_id}"
    )

    try:
        from src.services.lineup_optimizer import apply_exclusions, assign_lineup

        rosters = sleeper_client.get_league_rosters(league_id)
        if not rosters:
            raise HTTPException(
                status_code=404,
                detail=f"No rosters found for league: {league_id}",
            )

        user_id_str = str(user_id)
        target = next((r for r in rosters if str(r.owner_id) == user_id_str), None)
        if target is None:
            raise HTTPException(
                status_code=404,
                detail=f"No roster found for user {user_id} in league {league_id}",
            )

        season, week = _resolve_nfl_week_season()
        all_players = _load_in_season_players()
        scoring_format = sleeper_client.get_scoring_format(league_id) or "ppr"

        # Projections are required for recommendations: without them there is
        # nothing to optimize. Signal "pending" rather than returning a lineup
        # built on zeros. Pass the universe so projections are re-keyed from
        # nflverse ids to the Sleeper ids the roster uses.
        projections = _load_week_projections(season, week, scoring_format, all_players)
        if not projections:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Projections are not available yet for "
                    f"{season} week {week} ({scoring_format}). Please try again later."
                ),
            )

        # League roster slots drive the optimal assignment.
        league_info = sleeper_client.get_league_info(league_id) or {}
        roster_positions = league_info.get("roster_positions", []) or []

        matchup_service = _get_matchup_grade_service()

        optimizer_players, meta = _build_optimizer_players(
            target, all_players, projections, season, week, matchup_service
        )

        # Empty roster -> no recommendations, optimal lineup not set.
        if not optimizer_players:
            return RecommendationsResponse(
                league_id=str(league_id),
                user_id=user_id_str,
                week=week,
                season=season,
                scoring_format=scoring_format,
                recommendations=[],
                optimal_lineup_set=False,
            )

        eligible = apply_exclusions(optimizer_players)
        assignment = assign_lineup(eligible, roster_positions)
        starting_slot_labels = [
            slot for slot in roster_positions if slot not in {"BN", "IR", "TAXI"}
        ]

        # Map each assigned player_id -> its slot label.
        assigned_slot = {}
        for slot_label, assigned in zip(starting_slot_labels, assignment):
            if assigned is not None:
                assigned_slot[assigned.player_id] = slot_label

        # A full optimal lineup means every real starting slot got a player.
        optimal_lineup_set = bool(starting_slot_labels) and all(
            a is not None for a in assignment
        )

        recommendations = []
        for pid, info in meta.items():
            slot_label = assigned_slot.get(pid)
            if slot_label is not None:
                recommendation = "START"
            else:
                recommendation = _sit_reason(info)

            opponent = _opponent_for(info["team"], season, week, matchup_service)
            matchup_grade = _build_matchup_response(
                info["team"], opponent, season, week, matchup_service
            )

            recommendations.append(
                StartSitRecommendation(
                    player_id=pid,
                    player_name=info["player_name"],
                    position=info["position"],
                    team=info["team"],
                    projected_points=info["projected_points"],
                    recommendation=recommendation,
                    slot=slot_label,
                    matchup_grade=matchup_grade,
                    on_bye=info["on_bye"],
                    injury_status=info["injury_status"],
                )
            )

        # Starters first (highest projected first), then bench, for a stable,
        # UI-friendly ordering.
        recommendations.sort(
            key=lambda r: (
                0 if r.recommendation == "START" else 1,
                -(r.projected_points or 0.0),
            )
        )

        return RecommendationsResponse(
            league_id=str(league_id),
            user_id=user_id_str,
            week=week,
            season=season,
            scoring_format=scoring_format,
            recommendations=recommendations,
            optimal_lineup_set=optimal_lineup_set,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error computing start/sit recommendations: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {str(e)}"
        )
