"""Draft Helper API - Main application."""

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from fastapi.middleware.cors import CORSMiddleware

from src.data_sources.sleeper_client import SleeperClient
from src.analytics.adp_service import adp_service
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
)
from src.api.storage import load_player_universe, save_player_universe

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
    allow_methods=["*"],  # Allow all methods including PUT/DELETE
    allow_headers=["*"],
)

# Initialize Sleeper client (singleton)
sleeper_client = SleeperClient()


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
def get_draft_picks(draft_id: str):
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

        # Transform DraftPick dataclasses to PickDetail Pydantic models
        # Include ADP data for value analysis
        pick_details = []
        for pick in draft_picks:
            # Get PPR ADP for this player
            adp_ppr = adp_service.get_player_adp(pick.player_name, "ppr")

            # Calculate delta (pick_no - adp_ppr: positive = reach, negative = value)
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
def get_draft_details(draft_id: str):
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
def get_league_settings(draft_id: str):
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
def get_available_players(
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
def get_available_by_position(
    draft_id: str,
    limit: int = Query(default=20, ge=1, le=100, description="Max players per position"),
) -> AvailableByPositionResponse:
    """Get available players grouped by position with ADP delta analysis.

    Returns the top available players at each position sorted by ADP delta
    relative to the current overall pick in the draft. Helps identify best
    value picks available right now.

    Args:
        draft_id: The draft ID
        limit: Maximum players to return per position (1-100, default 20)

    Returns:
        Available players grouped by position with ADP deltas
    """
    from collections import defaultdict

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

        # Step 4: Load player universe
        all_players = load_player_universe()
        if not all_players:
            all_players = sleeper_client.get_players()
            if all_players:
                save_player_universe(all_players)

        if not all_players:
            raise HTTPException(500, "Unable to load player data")

        # Step 5: Filter available players and enrich with ADP
        available_by_position = defaultdict(list)
        positions = ["QB", "RB", "WR", "TE", "K", "DEF"]

        # Build ADP lookup dict once for O(1) lookups instead of O(M) per player
        adp_lookup = adp_service.get_adp_lookup(scoring_format)

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

            # Get ADP for this player via O(1) dict lookup
            normalized_name = adp_service.normalize_player_name(player_name)
            adp_value = adp_lookup.get(normalized_name)

            # Skip players without ADP data for the Top Available list 
            # so we don't return random historical/practice squad players
            if adp_value is None:
                continue

            # Calculate ADP delta: current_overall_pick - adp_ppr
            # Positive = player available later than ADP (value)
            # Negative = player expected earlier (reaching if drafted now)
            adp_delta = current_overall_pick - adp_value

            # Create player detail
            available_player = AvailablePlayerDetail(
                player_id=player_id,
                player_name=player_name,
                position=position,
                team=player_data.get("team") or "FA",
                age=player_data.get("age"),
                years_exp=player_data.get("years_exp"),
                adp_ppr=adp_value,
                adp_delta=adp_delta,
            )

            available_by_position[position].append(available_player)

        # Step 6: Sort each position by ADP delta (descending - best value first)
        # Players with no ADP data go to end
        for position in available_by_position:
            available_by_position[position].sort(
                key=lambda p: (p.adp_delta is None, -(p.adp_delta or 0))
            )

        # Step 7: Limit to top N per position
        limited_by_position = {}
        for position in positions:
            limited_by_position[position] = available_by_position[position][:limit]

        logger.info(
            f"Returning available players by position for draft {draft_id} "
            f"at pick {current_overall_pick}"
        )

        return AvailableByPositionResponse(
            draft_id=draft_id,
            current_overall_pick=current_overall_pick,
            current_round=current_round,
            scoring_format=scoring_format,
            limit=limit,
            players_by_position=limited_by_position,
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
def get_user_roster(draft_id: str, user_id: str):
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
def get_draft_vor_analysis(
    draft_id: str,
    limit_per_position: int = 5,
):
    """
    Get VOR (Value Over Replacement) analysis for available players in a draft.
    
    Returns top 5 recommendations per position, ranked by VOR score (highest value first).
    
    Args:
        draft_id: Draft ID
        limit_per_position: Maximum recommendations per position (default 5)
    
    Returns:
        VORAnalysisResponse with top recommendations by position and replacement levels
    """
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
        _teams = draft.get("settings", {}).get("teams", 12)
        _total_rounds = draft.get("settings", {}).get("rounds", 15)
        _picks_made = len(available)
        _current_round = math.ceil(_picks_made / _teams) if _picks_made > 0 else 1
        _in_late_rounds = _current_round >= (_total_rounds - 1)
        LATE_ROUND_POSITIONS = {"DEF", "K"}

        # Initialize VOR calculator
        vor = get_vor_calculator()

        # Build player ID resolver to map FantasyPros names -> Sleeper IDs
        sleeper_players_map = sleeper_client.get_players() or {}
        from src.services.player_id_resolver import PlayerIDResolver
        resolver = PlayerIDResolver(sleeper_players_map)

        # Build valid player pool matching available-by-position exactly:
        # rank each position by ADP delta and take the top VOR_POOL_SIZE per position.
        # This excludes players with stale/irrelevant projections (e.g. late-ADP players
        # who ranked high last season but aren't relevant at the current pick).
        scoring_format = sleeper_client.get_scoring_format(league_id) or "ppr"
        adp_lookup = adp_service.get_adp_lookup(scoring_format)
        all_players = load_player_universe() or sleeper_players_map
        current_overall_pick = available[-1].pick_no + 1 if available else 1
        VOR_POOL_SIZE = 5
        _pool_positions = {"QB", "RB", "WR", "TE", "K", "DEF"}
        _by_pos: dict[str, list[tuple[float, str]]] = {}
        for _pid, _pdata in all_players.items():
            if not _pdata.get("active"):
                continue
            _pos = _pdata.get("position")
            if not _pos or _pos not in _pool_positions:
                continue
            _name = f"{_pdata.get('first_name', '')} {_pdata.get('last_name', '')}".strip()
            if not _name:
                continue
            _adp = adp_lookup.get(adp_service.normalize_player_name(_name))
            if _adp is None:
                continue
            _delta = current_overall_pick - _adp
            _by_pos.setdefault(_pos, []).append((_delta, _pid))

        valid_available_ids: set[str] = set()
        for _pos, _entries in _by_pos.items():
            _entries.sort(key=lambda x: x[0], reverse=True)
            for _, _pid in _entries[:VOR_POOL_SIZE]:
                valid_available_ids.add(_pid)

        projections_active = bool(vor.projection_groups)

        # Resolve all VOR players to Sleeper IDs, filtering out drafted players
        recommendations = []
        skipped = 0
        for player in vor.players:
            sleeper_id = resolver.resolve(
                player['player_name'], player['position'], player.get('team')
            )
            if not sleeper_id:
                skipped += 1
                continue
            # Only recommend players present in the available-by-position table
            if sleeper_id not in valid_available_ids:
                skipped += 1
                continue
            # Suppress DEF/K until the last 2 rounds
            if player['position'] in LATE_ROUND_POSITIONS and not _in_late_rounds:
                continue
            if sleeper_id in drafted_player_ids:
                continue

            try:
                projected_pts = player.get('projected_pts')
                vor_score = vor.calculate_vor(
                    position=player['position'],
                    adp=player['adp_overall'],
                    projected_pts=projected_pts,
                )
                basis = "projection" if projected_pts is not None and projections_active else "adp"

                replacement_level = vor.get_replacement_level(
                    position=player['position'],
                    replacement_percentile=50
                )

                recommendations.append({
                    "league_id": league_id,
                    "draft_id": draft_id,
                    "player_id": sleeper_id,
                    "player_name": player['player_name'],
                    "position": player['position'],
                    "adp_overall": player['adp_overall'],
                    "replacement_level_adp": replacement_level,
                    "vor_score": vor_score,
                    "interpretation": vor._interpret_vor(vor_score, basis=basis),
                    "picks_remaining": len(vor.players) - len(drafted_player_ids),
                    "projected_points": projected_pts,
                    "vor_basis": basis,
                })
            except Exception as e:
                logger.warning(f"Could not calculate VOR for {player['player_name']}: {e}")
                continue

        logger.info(
            f"VOR: {len(drafted_player_ids)} drafted, {len(recommendations)} recommendations, "
            f"{skipped} unresolved, projections_active={projections_active}"
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

        # Replacement level summary: use median projected pts if projections active,
        # else median ADP (existing behaviour)
        replacement_by_position = {}
        for pos in ['QB', 'RB', 'WR', 'TE', 'K', 'DEF']:
            try:
                if projections_active and pos in vor.projection_groups:
                    pts_list = [p['projected_pts'] for p in vor.projection_groups[pos]]
                    from statistics import median as _median
                    replacement_by_position[pos] = _median(pts_list)
                else:
                    replacement_by_position[pos] = vor.get_replacement_level(pos, 50)
            except Exception:
                pass

        return VORAnalysisResponse(
            league_id=league_id,
            draft_id=draft_id,
            recommendations=all_top_recommendations,
            top_value_pick=all_top_recommendations[0],
            replacement_level_by_position=replacement_by_position,
            projections_loaded=projections_active,
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
def get_player_vor(draft_id: str, player_id: str):
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
