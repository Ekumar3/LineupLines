"""Draft Helper API - Main application."""

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from fastapi.middleware.cors import CORSMiddleware

from src.data_sources.sleeper_client import SleeperClient
from src.api.models import (
    UserDraftsResponse,
    DraftSummary,
    ErrorResponse,
    UserLookupResponse,
    DraftPicksResponse,
    PickDetail,
    AvailablePlayersResponse,
    PlayerSummary,
)
from src.api.storage import load_player_universe, save_player_universe

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Draft Helper API",
    version="1.0",
    description="Fantasy football draft helper using Sleeper API and historical ADP data",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS", "POST"],
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

        # Transform to DraftSummary objects
        draft_summaries = _transform_drafts(raw_drafts)

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

        # Transform to DraftSummary objects
        draft_summaries = _transform_drafts(raw_drafts)

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
        # Fetch picks from Sleeper (includes player enrichment)
        draft_picks = sleeper_client.get_draft_picks(draft_id)

        if not draft_picks:
            raise HTTPException(
                status_code=404,
                detail=f"No picks found for draft_id: {draft_id}",
            )

        # Transform DraftPick dataclasses to PickDetail Pydantic models
        pick_details = [
            PickDetail(
                pick_no=pick.pick_no,
                round=pick.round,
                roster_id=pick.roster_id,
                player_id=pick.player_id,
                player_name=pick.player_name,
                position=pick.position,
                team=pick.team,
                timestamp=pick.timestamp.isoformat(),
            )
            for pick in draft_picks
        ]

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


def _transform_drafts(raw_drafts: list) -> list[DraftSummary]:
    """Transform raw Sleeper API response to DraftSummary objects.

    Args:
        raw_drafts: List of draft dicts from Sleeper API

    Returns:
        List of DraftSummary objects
    """
    summaries = []

    for draft in raw_drafts:
        try:
            summary = DraftSummary(
                draft_id=draft.get("draft_id", ""),
                league_id=draft.get("league_id", ""),
                status=draft.get("status", "unknown"),
                settings={
                    "teams": draft.get("settings", {}).get("teams", 0),
                    "rounds": draft.get("settings", {}).get("rounds", 0),
                    "reversal_round": draft.get("settings", {}).get("reversal_round"),
                    "type": draft.get("type", "snake"),
                },
                metadata={
                    "name": draft.get("metadata", {}).get("name"),
                    "scoring_type": draft.get("metadata", {}).get("scoring_type"),
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
