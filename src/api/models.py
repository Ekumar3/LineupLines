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
    adp_ppr: Optional[float] = Field(None, description="Player's ADP in PPR format from DraftSharks (e.g., 8.1)")
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
    """Individual available player with projection and ADP data."""

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
                "projected_pts": 245.6,
                "avg_ppg": 14.5,
                "tier": 1,
                "positional_tier": 1,
                "environment_rank": 3,
                "environment_score": 1.58
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
    projected_pts: Optional[float] = Field(None, description="Season-total projected fantasy points")
    avg_ppg: Optional[float] = Field(None, description="Projected average fantasy points per game")
    tier: Optional[int] = Field(None, description="Overall tier for this player based on ADP and projections")
    positional_tier: Optional[int] = Field(None, description="Tier for this player within their position group based on ADP and projections")
    environment_rank: Optional[int] = Field(None, description="Player's NFL team's offensive scoring-environment rank (1=best), based on Vegas implied team totals")
    environment_score: Optional[float] = Field(None, description="Continuous scoring-environment score used to break ties within a tier; higher is better")


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
                "adp_source": "sleeper",
                "adp_source_available": True,
                "ranking_key": None,
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
    adp_source: str = Field(..., description="Requested ADP source: sleeper or draftsharks")
    adp_source_available: bool = Field(
        ...,
        description="False if the requested non-Sleeper source had no fresh (<48h) snapshot and the response fell back to Sleeper ADP",
    )
    ranking_key: Optional[str] = Field(
        None,
        description="The DraftSharks S3 ranking key actually used (e.g. 'dynasty_ppr_superflex'), "
        "chosen from the league's type/superflex/TE-premium settings. None when adp_source is 'sleeper'.",
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
    league_name: Optional[str] = Field(None, description="The league/draft's display name, as set on Sleeper")
    roster_by_position: Dict[str, List[PickDetail]] = Field(
        ..., description="User's picks grouped by position"
    )
    position_summary: Dict[str, PositionNeed] = Field(
        ..., description="Summary of position needs and priorities"
    )
"""VOR Response Models - Add these to src/api/models.py"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, List


class VORPlayerDetail(BaseModel):
    """VOR analysis for a single player."""
    player_id: str = Field(..., description="Player ID")
    player_name: str = Field(..., description="Player name")
    position: str = Field(..., description="Player position (QB, RB, WR, TE)")
    adp_overall: float = Field(..., description="Player's ADP (lower is better)")
    replacement_level_adp: float = Field(..., description="Next player's ADP or projected pts (replacement baseline)")
    vor_score: float = Field(..., description="Value Over Replacement score (higher = more elite)")
    interpretation: str = Field(..., description="Human-readable VOR interpretation")
    projected_points: Optional[float] = Field(None, description="Projected avg points per game (if available)")
    season_pts: Optional[float] = Field(None, description="Projected season-total fantasy points")
    vor_basis: str = Field("adp", description="Metric used for VOR: 'projection' or 'adp'")


class VORDraftRecommendation(BaseModel):
    """VOR recommendation for a player in context of draft state."""
    league_id: str = Field(..., description="League ID")
    draft_id: str = Field(..., description="Draft ID")
    player_id: str = Field(..., description="Player ID")
    player_name: str = Field(..., description="Player name")
    position: str = Field(..., description="Player position")
    adp_overall: float = Field(..., description="Player's ADP")
    replacement_level_adp: float = Field(..., description="Next player's ADP or projected pts (replacement baseline)")
    vor_score: float = Field(..., description="VOR score (higher = better value)")
    interpretation: str = Field(..., description="Value interpretation (Elite, Strong, Moderate, etc)")
    draft_position: Optional[int] = Field(None, description="What pick # this player would be")
    picks_remaining: int = Field(..., description="Total undrafted players remaining")
    projected_points: Optional[float] = Field(None, description="Projected avg points per game (if available)")
    season_pts: Optional[float] = Field(None, description="Projected season-total fantasy points")
    vor_basis: str = Field("adp", description="Metric used for VOR: 'projection' or 'adp'")
    replacement_player_id: Optional[str] = Field(None, description="Player ID of the replacement-level player for this position")
    replacement_player_name: Optional[str] = Field(None, description="Name of the replacement-level player for this position")
    replacement_player_team: Optional[str] = Field(None, description="Team of the replacement-level player for this position")
    replacement_player_points: Optional[float] = Field(None, description="Projected points of the replacement-level player for this position")


class VORAnalysisResponse(BaseModel):
    """Complete VOR analysis response for a draft."""
    league_id: str = Field(..., description="League ID")
    draft_id: str = Field(..., description="Draft ID")
    recommendations: List[VORDraftRecommendation] = Field(
        ...,
        description="Top VOR recommendations ranked by value (highest first)"
    )
    top_value_pick: VORDraftRecommendation = Field(
        ...,
        description="Single best value recommendation right now"
    )
    replacement_level_by_position: Dict[str, float] = Field(
        ...,
        description="Replacement baseline per position (projected pts if projections loaded, else median ADP)"
    )
    projections_loaded: bool = Field(
        False,
        description="Whether projection-based VOR is active for this response"
    )


# ---------------------------------------------------------------------------
# In-Season Matchup Recommendations models
#
# Response models for the /api/v1/in-season/ endpoints. These follow the same
# conventions as the draft models above: BaseModel with ConfigDict examples,
# Field(..., description=...), and all IDs normalized to strings.
# ---------------------------------------------------------------------------


class MatchupGradeResponse(BaseModel):
    """OL/DL matchup grade for a team vs opponent."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "team": "SF",
                "opponent": "SEA",
                "season": 2025,
                "week": 8,
                "pass_matchup": 15.2,
                "rush_matchup": -3.1,
                "overall_matchup": 8.4,
                "pass_signal": "favorable",
                "rush_signal": "neutral",
                "overall_signal": "favorable",
                "ol_grade": 78.5,
                "dl_grade": 60.1,
            }
        }
    )

    team: str = Field(..., description="Offense team abbreviation")
    opponent: str = Field(..., description="Defense team abbreviation")
    season: int = Field(..., description="NFL season year")
    week: int = Field(..., description="NFL week")
    pass_matchup: Optional[float] = Field(
        None, description="OL pass grade - DL pass grade; positive = offense favored"
    )
    rush_matchup: Optional[float] = Field(
        None, description="OL run grade - DL run grade"
    )
    overall_matchup: Optional[float] = Field(
        None, description="OL grade - DL grade; positive = offense favored"
    )
    pass_signal: str = Field("neutral", description="favorable | neutral | unfavorable")
    rush_signal: str = Field("neutral", description="favorable | neutral | unfavorable")
    overall_signal: str = Field(
        "neutral", description="favorable | neutral | unfavorable"
    )
    ol_grade: Optional[float] = Field(
        None, description="Offense OL composite grade 0-100"
    )
    dl_grade: Optional[float] = Field(
        None, description="Defense DL composite grade 0-100"
    )


class RosterPlayer(BaseModel):
    """A player on a roster with slot assignment."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "player_id": "4046",
                "player_name": "Patrick Mahomes",
                "position": "QB",
                "team": "KC",
                "slot": "QB",
                "projected_points": 24.3,
                "matchup_grade": None,
                "on_bye": False,
                "injury_status": None,
            }
        }
    )

    player_id: str = Field(..., description="Sleeper player ID")
    player_name: str = Field(..., description="Player full name")
    position: str = Field(..., description="Player position (QB, RB, WR, TE, etc.)")
    team: str = Field(..., description="NFL team abbreviation or 'FA'")
    slot: str = Field(..., description="Assigned slot or 'BENCH'/'RESERVE'")
    projected_points: Optional[float] = Field(
        None, description="Projected fantasy points for the week, when available"
    )
    matchup_grade: Optional[MatchupGradeResponse] = Field(
        None, description="OL/DL matchup grade for this player's team, when available"
    )
    on_bye: bool = Field(False, description="Whether the player is on a bye this week")
    injury_status: Optional[str] = Field(
        None, description="Injury status (e.g., Questionable, Out, IR)"
    )


class RosterResponse(BaseModel):
    """A user's roster with starters and bench."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "league_id": "987654321",
                "user_id": "123456789",
                "roster_id": "3",
                "week": 8,
                "season": 2025,
                "starters": [],
                "bench": [],
                "reserve": [],
            }
        }
    )

    league_id: str = Field(..., description="Sleeper league ID")
    user_id: str = Field(..., description="Sleeper user ID (roster owner)")
    roster_id: str = Field(..., description="Sleeper roster ID")
    week: int = Field(..., description="NFL week")
    season: int = Field(..., description="NFL season year")
    starters: List[RosterPlayer] = Field(
        ..., description="Players in starting slots (ordered)"
    )
    bench: List[RosterPlayer] = Field(
        default_factory=list, description="Bench players (players - starters - reserve)"
    )
    reserve: List[RosterPlayer] = Field(
        default_factory=list, description="Players on reserve/IR"
    )


class LeagueRostersResponse(BaseModel):
    """All rosters in a league."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "league_id": "987654321",
                "week": 8,
                "season": 2025,
                "rosters": [],
            }
        }
    )

    league_id: str = Field(..., description="Sleeper league ID")
    week: int = Field(..., description="NFL week")
    season: int = Field(..., description="NFL season year")
    rosters: List[RosterResponse] = Field(
        ..., description="All rosters in the league, enriched with player data"
    )


class StartSitRecommendation(BaseModel):
    """Start/sit recommendation for one player on a user's roster."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "player_id": "4046",
                "player_name": "Patrick Mahomes",
                "position": "QB",
                "team": "KC",
                "projected_points": 24.3,
                "recommendation": "START",
                "slot": "QB",
                "matchup_grade": None,
                "on_bye": False,
                "injury_status": None,
            }
        }
    )

    player_id: str = Field(..., description="Sleeper player ID")
    player_name: str = Field(..., description="Player full name")
    position: str = Field(..., description="Player position (QB, RB, WR, TE, etc.)")
    team: str = Field(..., description="NFL team abbreviation or 'FA'")
    projected_points: Optional[float] = Field(
        None, description="Projected fantasy points for the week, when available"
    )
    recommendation: str = Field(
        ..., description="START | SIT | SIT (BYE) | SIT (INJURY)"
    )
    slot: Optional[str] = Field(
        None, description="Assigned starting slot when recommendation is START, else None"
    )
    matchup_grade: Optional[MatchupGradeResponse] = Field(
        None, description="OL/DL matchup grade for this player's team, when available"
    )
    on_bye: bool = Field(False, description="Whether the player is on a bye this week")
    injury_status: Optional[str] = Field(
        None, description="Injury status (e.g., Questionable, Out, IR)"
    )


class RecommendationsResponse(BaseModel):
    """Start/sit recommendations for a user's roster."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "league_id": "987654321",
                "user_id": "123456789",
                "week": 8,
                "season": 2025,
                "scoring_format": "ppr",
                "recommendations": [],
                "optimal_lineup_set": True,
            }
        }
    )

    league_id: str = Field(..., description="Sleeper league ID")
    user_id: str = Field(..., description="Sleeper user ID (roster owner)")
    week: int = Field(..., description="NFL week")
    season: int = Field(..., description="NFL season year")
    scoring_format: str = Field(
        ..., description="League scoring format (ppr, half_ppr, standard)"
    )
    recommendations: List[StartSitRecommendation] = Field(
        ..., description="Per-player START/SIT recommendations"
    )
    optimal_lineup_set: bool = Field(
        ..., description="Whether a full optimal lineup was found via assignment"
    )


class WaiverRecResponse(BaseModel):
    """A single waiver-wire free-agent recommendation (Phase 1)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "player_id": "4046",
                "player_name": "Jaylen Warren",
                "position": "RB",
                "team": "PIT",
                "projected_points": 11.4,
                "trending_add_count": 15230,
                "rank": 1,
            }
        }
    )

    player_id: str = Field(..., description="Sleeper player ID")
    player_name: str = Field(..., description="Player full name")
    position: str = Field(..., description="Player position (QB, RB, WR, TE, etc.)")
    team: str = Field(..., description="NFL team abbreviation or 'FA'")
    projected_points: Optional[float] = Field(
        None, description="Projected fantasy points for the week, when available"
    )
    trending_add_count: Optional[int] = Field(
        None, description="Sleeper trending-add count, when available"
    )
    rank: int = Field(..., description="1-indexed rank by projected points")


class WaiverResponse(BaseModel):
    """Phase 1 waiver recommendations: top free agents by projected points."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "league_id": "987654321",
                "week": 8,
                "season": 2025,
                "position": "RB",
                "recommendations": [],
            }
        }
    )

    league_id: str = Field(..., description="Sleeper league ID")
    week: int = Field(..., description="NFL week")
    season: int = Field(..., description="NFL season year")
    position: Optional[str] = Field(
        None, description="Position filter echoed back (None = all positions)"
    )
    recommendations: List[WaiverRecResponse] = Field(
        ..., description="Ranked free-agent recommendations"
    )


class DropAddRecResponse(BaseModel):
    """A single drop/add pair: swap a bench player for a free agent (Phase 2)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "drop_player_id": "1234",
                "drop_player_name": "Zach Charbonnet",
                "drop_projected_points": 6.2,
                "add_player_id": "4046",
                "add_player_name": "Jaylen Warren",
                "add_projected_points": 11.4,
                "position": "RB",
                "net_gain": 5.2,
                "rank": 1,
            }
        }
    )

    drop_player_id: str = Field(..., description="Sleeper player ID to drop")
    drop_player_name: str = Field(..., description="Name of the player to drop")
    drop_projected_points: float = Field(
        ..., description="Projected fantasy points for the drop player"
    )
    add_player_id: str = Field(..., description="Sleeper player ID to add")
    add_player_name: str = Field(..., description="Name of the player to add")
    add_projected_points: float = Field(
        ..., description="Projected fantasy points for the add player"
    )
    position: str = Field(..., description="Position of the slot being upgraded")
    net_gain: float = Field(
        ..., description="Net projected points gained (add - drop); always > 0"
    )
    rank: int = Field(..., description="1-indexed rank by net gain")


class DropAddResponse(BaseModel):
    """Phase 2 drop/add recommendations: ranked upgrade swaps for a user."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "league_id": "987654321",
                "user_id": "123456789",
                "week": 8,
                "season": 2025,
                "recommendations": [],
            }
        }
    )

    league_id: str = Field(..., description="Sleeper league ID")
    user_id: str = Field(..., description="Sleeper user ID / roster owner")
    week: int = Field(..., description="NFL week")
    season: int = Field(..., description="NFL season year")
    recommendations: List[DropAddRecResponse] = Field(
        ..., description="Ranked drop/add pairs (positive net gain only)"
    )
