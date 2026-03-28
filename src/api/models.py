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
    slots_qb: Optional[int] = Field(None, description="Number of QB slots")
    slots_super_flex: Optional[int] = Field(None, description="Number of Superflex slots")


class DraftMetadata(BaseModel):
    """Draft metadata like league name and scoring format."""

    name: Optional[str] = Field(None, description="League or draft name")
    scoring_type: Optional[str] = Field(
        None, description="Scoring format (ppr, half_ppr, standard)"
    )
    league_type: Optional[str] = Field(
        "0", description="League type: 0=Redraft, 1=Keeper, 2=Dynasty"
    )
    te_premium: Optional[float] = Field(
        None, description="TE Premium bonus points per reception"
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
                "user_id": "942348475046494208",
                "player_id": "2307",
                "player_name": "Christian McCaffrey",
                "position": "RB",
                "team": "SF",
                "timestamp": "2026-08-15T19:30:00",
                "adp_ppr": 8.1,
                "adp_delta": 7.1,
            }
        }
    )

    pick_no: int = Field(..., description="Pick number in the draft (1-indexed)")
    round: int = Field(..., description="Round number")
    user_id: str = Field(..., description="Sleeper user ID of the user who made this pick")
    player_id: str = Field(..., description="Sleeper player ID")
    player_name: str = Field(..., description="Player full name")
    position: str = Field(..., description="Player position (RB, WR, QB, TE, etc.)")
    team: str = Field(..., description="NFL team abbreviation")
    timestamp: str = Field(..., description="When the pick was made (ISO format)")
    adp_ppr: Optional[float] = Field(None, description="Player's ADP in PPR format from FantasyPros (e.g., 8.1)")
    adp_delta: Optional[float] = Field(None, description="Delta between pick and ADP (positive=value/picked later than ADP, negative=reach/picked earlier). Calculated as: pick_no - adp_ppr")


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
                        "user_id": "942348475046494208",
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


class AvailablePlayerDetail(BaseModel):
    """Individual available player with ADP data."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "player_id": "2307",
                "player_name": "Christian McCaffrey",
                "position": "RB",
                "team": "SF",
                "age": 27,
                "years_exp": 7,
                "adp_ppr": 35.2,
                "adp_delta": 10.2,
            }
        }
    )

    player_id: str = Field(..., description="Sleeper player ID")
    player_name: str = Field(..., description="Player full name")
    position: str = Field(..., description="Position (QB, RB, WR, TE, K, DEF)")
    team: str = Field(..., description="NFL team abbreviation or FA")
    age: Optional[int] = Field(None, description="Player age")
    years_exp: Optional[int] = Field(None, description="Years of NFL experience")
    adp_ppr: Optional[float] = Field(None, description="Player's ADP in scoring format")
    adp_delta: Optional[float] = Field(
        None,
        description="Delta: adp_ppr - current_overall_pick. Positive = player expected later (value), Negative = player expected earlier (reaching)",
    )


class AvailableByPositionResponse(BaseModel):
    """Response containing available players grouped by position with ADP analysis."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "draft_id": "789012345",
                "current_overall_pick": 25,
                "current_round": 3,
                "scoring_format": "ppr",
                "limit": 20,
                "players_by_position": {
                    "QB": [],
                    "RB": [],
                    "WR": [],
                    "TE": [],
                    "K": [],
                    "DEF": [],
                },
            }
        }
    )

    draft_id: str = Field(..., description="Draft ID")
    current_overall_pick: int = Field(
        ..., description="Current pick number (picks made + 1)"
    )
    current_round: int = Field(..., description="Current round number")
    scoring_format: str = Field(
        ..., description="Scoring format (ppr, half_ppr, standard)"
    )
    limit: int = Field(..., description="Max players returned per position")
    players_by_position: Dict[str, List[AvailablePlayerDetail]] = Field(
        ..., description="Available players by position, sorted by ADP delta descending"
    )


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


class RosterMapping(BaseModel):
    """Mapping of user IDs to roster positions."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id_1": 1,
                "user_id_2": 2,
                "user_id_3": 3,
            }
        }
    )

    root: Dict[str, int] = Field(..., description="Maps user_id to roster_id (draft position)")

    def __iter__(self):
        return iter(self.root)

    def __getitem__(self, key):
        return self.root[key]


class DraftDetails(BaseModel):
    """Complete draft information including roster mapping for tracking user picks.

    All IDs are normalized to strings for consistency across the API.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "draft_id": "789012345",
                "league_id": "456789012",
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
                "draft_order": ["942348475046494208", "765432109876543210", "123456789012345678", None],
                "roster_to_user": {
                    "1": "942348475046494208",
                    "2": "765432109876543210",
                    "3": "123456789012345678",
                    "4": "876543210123456789",
                },
            }
        }
    )

    draft_id: str = Field(..., description="The draft ID")
    league_id: str = Field(..., description="The league ID")
    status: str = Field(..., description="Draft status (pre_draft, in_progress, complete)")
    settings: DraftSettings = Field(..., description="Draft settings")
    metadata: DraftMetadata = Field(..., description="League metadata")
    draft_order: List[Optional[str]] = Field(
        ..., description="Array indexed by slot position, containing user_id (string) or None for unpicked slots"
    )
    roster_to_user: Dict[str, str] = Field(
        ..., description="Maps roster_id (string) to user_id (string) for identifying user picks"
    )


class LeagueSettings(BaseModel):
    """League scoring and roster settings."""

    league_id: str = Field(..., description="League ID")
    scoring_format: str = Field(..., description="Scoring format: ppr, half_ppr, or standard")
    roster_positions: Optional[List[str]] = Field(None, description="Required roster positions")
    total_rosters: int = Field(..., description="Number of teams in league")


class LeagueSettingsResponse(BaseModel):
    """Response containing league settings for a draft."""

    draft_id: str = Field(..., description="Draft ID")
    league_id: str = Field(..., description="League ID")
    settings: LeagueSettings = Field(..., description="League settings")


class PositionNeed(BaseModel):
    """Position strength analysis for a roster."""

    count: int = Field(..., description="Number of players at this position")
    needs_more: bool = Field(..., description="Whether more players are needed at this position")
    priority: str = Field(..., description="Priority to draft this position: high, medium, or low")


class UserRosterResponse(BaseModel):
    """Complete roster information for a user grouped by position."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
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
                            "timestamp": "2026-08-15T19:30:00",
                        }
                    ],
                    "WR": [],
                    "TE": [],
                    "K": [],
                    "DEF": [],
                },
                "position_summary": {
                    "QB": {"count": 0, "needs_more": True, "priority": "high"},
                    "RB": {"count": 1, "needs_more": True, "priority": "medium"},
                    "WR": {"count": 0, "needs_more": True, "priority": "medium"},
                    "TE": {"count": 0, "needs_more": True, "priority": "high"},
                    "K": {"count": 0, "needs_more": False, "priority": "low"},
                    "DEF": {"count": 0, "needs_more": False, "priority": "low"},
                },
            }
        }
    )

    draft_id: str = Field(..., description="The draft ID")
    user_id: str = Field(..., description="The user ID")
    draft_slot: int = Field(..., description="User's draft slot position (1-based, 0 if not found)")
    total_picks: int = Field(..., description="Total number of picks made by this user")
    roster_by_position: Dict[str, List[PickDetail]] = Field(
        ..., description="User's picks grouped by position"
    )
    position_summary: Dict[str, PositionNeed] = Field(
        ..., description="Summary of position needs and priorities"
    )
