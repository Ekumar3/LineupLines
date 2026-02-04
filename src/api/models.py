"""API data models for Draft Helper API.

Provides Pydantic models for request/response validation and OpenAPI documentation.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class DraftSettings(BaseModel):
    """Draft settings and configuration."""

    teams: int = Field(..., description="Number of teams in the draft")
    rounds: int = Field(..., description="Number of draft rounds")
    reversal_round: Optional[int] = Field(
        None, description="Round where snake draft reverses direction"
    )
    type: str = Field(..., description="Draft type (snake, linear, auction)")


class DraftMetadata(BaseModel):
    """Draft metadata like league name and scoring format."""

    name: Optional[str] = Field(None, description="League or draft name")
    scoring_type: Optional[str] = Field(
        None, description="Scoring format (ppr, half_ppr, standard)"
    )


class DraftSummary(BaseModel):
    """Summary information for displaying a draft to users."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "draft_id": "123456789",
                "league_id": "987654321",
                "status": "in_progress",
                "settings": {
                    "teams": 12,
                    "rounds": 15,
                    "reversal_round": 1,
                    "type": "snake",
                },
                "metadata": {
                    "name": "My Fantasy League 2026",
                    "scoring_type": "ppr",
                },
                "start_time": 1735689600000,
                "sport": "nfl",
                "season": "2026",
            }
        }
    )

    draft_id: str = Field(..., description="Unique draft identifier")
    league_id: str = Field(..., description="Associated league ID")
    status: str = Field(
        ...,
        description="Draft status: pre_draft, in_progress, or complete",
    )
    settings: DraftSettings = Field(..., description="Draft configuration")
    metadata: Optional[DraftMetadata] = Field(
        None, description="Additional draft information"
    )
    start_time: Optional[int] = Field(
        None, description="Draft start time (Unix timestamp in milliseconds)"
    )
    sport: str = Field(default="nfl", description="Sport type")
    season: str = Field(..., description="Season year")


class UserDraftsResponse(BaseModel):
    """Response containing a user's drafts."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "123456789",
                "sport": "nfl",
                "season": "2026",
                "total_drafts": 5,
                "active_drafts": 2,
                "drafts": [
                    {
                        "draft_id": "123456789",
                        "league_id": "987654321",
                        "status": "in_progress",
                        "settings": {
                            "teams": 12,
                            "rounds": 15,
                            "reversal_round": 1,
                            "type": "snake",
                        },
                        "metadata": {
                            "name": "My Fantasy League 2026",
                            "scoring_type": "ppr",
                        },
                        "start_time": 1735689600000,
                        "sport": "nfl",
                        "season": "2026",
                    }
                ],
            }
        }
    )

    user_id: str = Field(..., description="Sleeper user ID")
    sport: str = Field(..., description="Sport type")
    season: str = Field(..., description="Season year")
    total_drafts: int = Field(..., description="Total number of drafts found")
    active_drafts: int = Field(
        ..., description="Number of active/live drafts (in_progress + pre_draft)"
    )
    drafts: List[DraftSummary] = Field(..., description="List of draft summaries")


class ErrorResponse(BaseModel):
    """Standard error response format."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"detail": "No drafts found for user_id: 123456789 in nfl 2026"}
        }
    )

    detail: str = Field(..., description="Error message or detail")


class UserInfo(BaseModel):
    """User information from Sleeper."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "123456789",
                "username": "sleeperuser",
                "display_name": "Sleeper User",
                "avatar": "https://example.com/avatar.jpg",
                "verified": False,
            }
        }
    )

    user_id: str = Field(..., description="Sleeper user ID")
    username: str = Field(..., description="Sleeper username")
    display_name: Optional[str] = Field(None, description="User's display name")
    avatar: Optional[str] = Field(None, description="User's avatar URL")
    verified: Optional[bool] = Field(None, description="Whether user is verified")


class UserLookupResponse(BaseModel):
    """Response from user lookup endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "123456789",
                "username": "sleeperuser",
                "display_name": "Sleeper User",
                "avatar": "https://example.com/avatar.jpg",
                "verified": False,
            }
        }
    )

    user_id: str = Field(..., description="Sleeper user ID")
    username: str = Field(..., description="Sleeper username")
    display_name: Optional[str] = Field(None, description="User's display name")
    avatar: Optional[str] = Field(None, description="User's avatar URL")
    verified: Optional[bool] = Field(None, description="Whether user is verified")


class PickDetail(BaseModel):
    """Individual draft pick with player information."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "pick_no": 1,
                "round": 1,
                "roster_id": 1,
                "player_id": "2307",
                "player_name": "Christian McCaffrey",
                "position": "RB",
                "team": "SF",
                "timestamp": "2026-08-15T19:30:00",
            }
        }
    )

    pick_no: int = Field(..., description="Pick number in the draft (1-indexed)")
    round: int = Field(..., description="Round number")
    roster_id: int = Field(..., description="Roster ID of the team that made this pick")
    player_id: str = Field(..., description="Sleeper player ID")
    player_name: str = Field(..., description="Player full name")
    position: str = Field(..., description="Player position (RB, WR, QB, TE, etc.)")
    team: str = Field(..., description="NFL team abbreviation")
    timestamp: str = Field(..., description="When the pick was made (ISO format)")


class DraftPicksResponse(BaseModel):
    """Response containing all picks from a draft."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "draft_id": "789012345",
                "total_picks": 2,
                "picks": [
                    {
                        "pick_no": 1,
                        "round": 1,
                        "roster_id": 1,
                        "player_id": "2307",
                        "player_name": "Christian McCaffrey",
                        "position": "RB",
                        "team": "SF",
                        "timestamp": "2026-08-15T19:30:00",
                    }
                ],
            }
        }
    )

    draft_id: str = Field(..., description="The draft ID")
    total_picks: int = Field(..., description="Total number of picks made so far")
    picks: List[PickDetail] = Field(..., description="List of all picks in order")


class PlayerSummary(BaseModel):
    """Summary of a player for recommendations."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "player_id": "2307",
                "name": "Christian McCaffrey",
                "position": "RB",
                "team": "SF",
                "age": 27,
                "years_exp": 7,
            }
        }
    )

    player_id: str = Field(..., description="Sleeper player ID")
    name: str = Field(..., description="Player full name")
    position: str = Field(..., description="Player position")
    team: str = Field(..., description="NFL team abbreviation")
    age: Optional[int] = Field(None, description="Player age")
    years_exp: Optional[int] = Field(None, description="Years of NFL experience")


class AvailablePlayersResponse(BaseModel):
    """Response containing available (undrafted) players."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "draft_id": "789012345",
                "total_available": 450,
                "position_filter": "RB",
                "players": [
                    {
                        "player_id": "2307",
                        "name": "Christian McCaffrey",
                        "position": "RB",
                        "team": "SF",
                        "age": 27,
                        "years_exp": 7,
                    }
                ],
            }
        }
    )

    draft_id: str = Field(..., description="The draft ID")
    total_available: int = Field(..., description="Total number of available players matching filters")
    position_filter: Optional[str] = Field(None, description="Position filter applied (if any)")
    players: List[PlayerSummary] = Field(..., description="List of available players")
