# Requirements Document

## Introduction

The In-Season Matchup Recommendations feature extends the LineupLines Fantasy Football draft helper API to provide weekly start/sit and waiver recommendations based on OL/DL matchup analysis. The feature uses free nflverse data (play-by-play, player stats, snap counts, schedules) transformed through a dbt-duckdb SQL layer, processed by Python prediction models, and integrated with Sleeper API for real league data. All new functionality is separated from existing draft-only features under dedicated `/api/v1/in-season/` endpoints.

## Glossary

- **System**: The LineupLines in-season matchup recommendation system comprising data ingestion, SQL transformations, prediction services, and API endpoints
- **NFLVerse**: Free NFL play-by-play, player statistics, snap counts, and schedule data available via nflreadpy
- **Sleeper**: Fantasy football platform providing league rosters, player universe, and user data via public API
- **OL (Offensive Line)**: Composite grade representing a team's pass protection and run blocking capability
- **DL (Defensive Line)**: Composite grade representing a team's pass rush and run defense capability
- **Matchup Grade**: Numerical comparison of OL vs DL for a specific team vs opponent pairing
- **Projection Service**: Python service that generates expected stat lines and fantasy points for players
- **Lineup Optimizer**: Algorithm that assigns rostered players to starting slots to maximize projected points
- **Waiver Service**: Service providing free agent rankings and drop/add optimization recommendations
- **dbt**: Data build tool for SQL transformation pipelines (dbt-duckdb variant)
- **Airflow**: Workflow orchestration system for daily data refreshes
- **Player Universe**: Complete set of NFL players available in Sleeper's database
- **Scoring Format**: Fantasy scoring configuration (PPR, half-PPR, standard)
- **FA (Free Agent)**: NFL player not currently rostered in a specific league
- **VOR (Value Over Replacement)**: Metric comparing player value to readily available alternatives
- **Roster Positions**: League-specific lineup configuration (e.g., ["QB","RB","RB","WR","WR","TE","FLEX","BN","BN"])

## Requirements

### Requirement 1: Data Ingestion and Transformation

**User Story:** As a data engineer, I want to ingest free NFLVerse data and transform it through a dbt-duckdb SQL pipeline, so that we have clean, tested data marts for prediction modeling.

#### Acceptance Criteria

1. WHEN NFLVerse parquet files are available via nflreadpy, THE Data Ingestion Service SHALL download them to the local `data/raw/` directory
2. THE dbt-duckdb Transform Layer SHALL create staging tables (`stg_pbp`, `stg_player_stats`, `stg_snap_counts`, `stg_schedules`) from raw parquet files
3. THE dbt-duckdb Transform Layer SHALL compute intermediate team pass metrics (`int_team_pass_metrics`) with offensive and defensive perspectives
4. THE dbt-duckdb Transform Layer SHALL compute intermediate team run metrics (`int_team_run_metrics`) with offensive and defensive perspectives
5. THE dbt-duckdb Transform Layer SHALL compute OL grades (`mart_ol_grade`) as 0-100 composite scores from pass protection and run blocking percentiles
6. THE dbt-duckdb Transform Layer SHALL compute DL grades (`mart_dl_grade`) as 0-100 composite scores from pass rush and run defense percentiles
7. THE dbt-duckdb Transform Layer SHALL compute matchup grades (`mart_matchup_grade`) joining OL grades with opponent DL grades for all scheduled games
8. THE dbt-duckdb Transform Layer SHALL compute defense factor inputs (`int_defense_factor_inputs`) with team-game yardage by channel
9. THE dbt-duckdb Transform Layer SHALL compute player week features (`mart_player_week_features`) with all 9 stat components plus contextual metrics
10. WHERE data validation tests are defined in dbt, THE dbt-duckdb Transform Layer SHALL execute them and fail the pipeline on validation failure
11. FOR ALL OL and DL grade columns, THE dbt-duckdb Transform Layer SHALL ensure values are bounded between 0 and 100
12. FOR ALL trailing metric calculations, THE dbt-duckdb Transform Layer SHALL use only rows strictly before the target (season, week) to prevent future leaks

### Requirement 2: Projection Storage and Retrieval

**User Story:** As a developer, I want a unified storage abstraction for dbt marts and projection outputs, so that services can read data seamlessly from S3 (production) or local files (development).

#### Acceptance Criteria

1. THE Projections Store SHALL provide a `load_mart(name, season)` function that returns a Polars DataFrame
2. THE Projections Store SHALL provide a `load_projections(season, week, scoring_format)` function that returns projection output
3. THE Projections Store SHALL provide a `write_projections(df, season, week, scoring_format)` function that persists projection data
4. WHEN environment variable `MART_S3_BUCKET` is set, THE Projections Store SHALL read/write from S3
5. WHEN environment variable `MART_S3_BUCKET` is not set, THE Projections Store SHALL read/write from local `data/` directory
6. IF a requested mart or projection file is missing, THE Projections Store SHALL return an empty DataFrame without raising exceptions
7. FOR ALL read operations, THE Projections Store SHALL filter by season parameter when provided
8. THE Projections Store SHALL implement graceful degradation: missing files result in empty returns, never runtime errors

### Requirement 3: Matchup Grade Service

**User Story:** As a fantasy manager, I want to see OL/DL matchup grades for specific team vs opponent pairings, so that I can evaluate player matchups for start/sit decisions.

#### Acceptance Criteria

1. THE Matchup Grade Service SHALL provide a `grade_for(team, opponent, season, week)` method returning a `MatchupGrade` object
2. WHEN a matching row exists in `mart_matchup_grade`, THE Matchup Grade Service SHALL return the computed grades and signals
3. WHEN no matching row exists or the mart is empty, THE Matchup Grade Service SHALL return a neutral default with all signals "neutral" and grades 0.0
4. THE Matchup Grade Service SHALL lazy-load and cache the `mart_matchup_grade` DataFrame on first use
5. THE Matchup Grade Response SHALL include `pass_matchup`, `rush_matchup`, and `overall_matchup` numerical differences
6. THE Matchup Grade Response SHALL include `pass_signal`, `rush_signal`, and `overall_signal` as "favorable", "neutral", or "unfavorable"
7. THE Matchup Grade Response SHALL include `ol_grade` and `dl_grade` when available
8. WHERE `pass_matchup > 10`, THE Matchup Grade Response SHALL set `pass_signal` to "favorable"
9. WHERE `pass_matchup < -10`, THE Matchup Grade Response SHALL set `pass_signal` to "unfavorable"
10. OTHERWISE, THE Matchup Grade Response SHALL set `pass_signal` to "neutral" (same for rush and overall signals)
11. THE Matchup Grade Service SHALL never raise exceptions for missing data, always returning graceful defaults

### Requirement 4: Projection Service

**User Story:** As a fantasy manager, I want accurate weekly player projections based on historical performance, team matchups, and defensive factors, so that I can make informed start/sit decisions.

#### Acceptance Criteria

1. THE Projection Service SHALL provide a `project_week(season, week, scoring_settings)` method returning a list of `Projection` objects
2. THE Projection Service SHALL load `mart_player_week_features` and `int_defense_factor_inputs` via the Projections Store
3. FOR EACH player, THE Projection Service SHALL compute a baseline stat line as trailing 3-week average with prior-season fallback
4. THE Projection Service SHALL compute defense factors via ridge regression on team-game yardage data
5. THE Projection Service SHALL apply defense factors to baseline stat lines to generate expected stat lines
6. THE Projection Service SHALL score expected stat lines using provided `scoring_settings` to compute projected fantasy points
7. THE Projection Service SHALL implement the v2.1.0-prod algorithm (refactored from research/model.py) with no future leaks
8. FOR ALL defense factors, THE Projection Service SHALL clamp values between 0.75 and 1.25
9. THE Projection Service SHALL weight prior-season data at 0.3 when fitting defense factors
10. THE Projection Service SHALL write projection outputs to persistent storage via `write_projections`
11. FOR ALL calculations, THE Projection Service SHALL use only rows with `(season', week') < (target_season, target_week)` to prevent future leaks
12. WHERE insufficient data exists (< MIN_GAMES_TO_FIT), THE Projection Service SHALL default defense factors to 1.0 (league average)

### Requirement 5: Sleeper Client Extensions

**User Story:** As an integration developer, I need additional Sleeper API methods for in-season features, so that we can access league rosters, NFL state, and trending player data.

#### Acceptance Criteria

1. THE Sleeper Client SHALL provide a `get_league_rosters(league_id)` method returning a list of `Roster` objects
2. THE Sleeper Client SHALL provide a `get_nfl_state()` method returning current NFL season, week, and season type
3. THE Sleeper Client SHALL provide a `get_league_transactions(league_id, week)` method returning weekly transactions
4. THE Sleeper Client SHALL provide a `get_trending_players(type, lookback_hours, limit)` method returning trending add/drop data
5. FOR ALL returned IDs (player_id, user_id, league_id, roster_id), THE Sleeper Client SHALL normalize them to strings
6. WHEN API calls fail, THE Sleeper Client SHALL return empty lists or None (defensive programming, never raises)
7. THE Sleeper Client SHALL maintain the existing 0.1s rate limit between requests
8. THE `Roster` object SHALL contain `roster_id`, `owner_id`, `starters`, `players`, and `reserve` lists
9. THE Sleeper Client SHALL handle roster bench computation as `players - starters - reserve`

### Requirement 6: Lineup Optimization

**User Story:** As a fantasy manager, I want optimal start/sit recommendations based on projected points and roster constraints, so that I maximize my weekly scoring potential.

#### Acceptance Criteria

1. THE Lineup Optimizer SHALL provide an `assign_lineup(players, roster_positions)` method returning slot assignments
2. THE Lineup Optimizer SHALL provide an `apply_exclusions(players)` method filtering out ineligible players
3. WHEN a player is on bye, THE Lineup Optimizer SHALL exclude them from starting consideration
4. WHEN a player has injury status "OUT" or "DOUBTFUL", THE Lineup Optimizer SHALL exclude them from starting consideration
5. WHEN a player has roster status "IR" or "TAXI", THE Lineup Optimizer SHALL exclude them from starting consideration
6. WHEN a player has injury status "QUESTIONABLE", THE Lineup Optimizer SHALL include them at full projected value
7. THE Lineup Optimizer SHALL use max-weight bipartite matching (`scipy.optimize.linear_sum_assignment`) for optimal assignments
8. THE Lineup Optimizer SHALL respect position eligibility rules (e.g., FLEX accepts RB/WR/TE)
9. THE Lineup Optimizer SHALL return the globally optimal assignment (not greedy by projected points)
10. FOR ALL assigned players, THE Lineup Optimizer SHALL ensure position eligibility for their assigned slot
11. WHERE no eligible player exists for a slot, THE Lineup Optimizer SHALL assign None (empty slot)
12. THE Lineup Optimizer SHALL define flex eligibility as: FLEX={RB,WR,TE}, SUPER_FLEX={QB,RB,WR,TE}, REC_FLEX={WR,TE}, WRRB_FLEX={WR,RB}

### Requirement 7: Roster Management API

**User Story:** As a fantasy manager, I want to view my roster and league rosters enriched with player data and matchup grades, so that I can assess my team's weekly outlook.

#### Acceptance Criteria

1. THE FastAPI SHALL provide a `GET /api/v1/in-season/{league_id}/rosters` endpoint returning all league rosters
2. THE FastAPI SHALL provide a `GET /api/v1/in-season/{league_id}/{user_id}/roster` endpoint returning a specific user's roster
3. WHEN fetching rosters, THE API SHALL enrich player data with names, positions, and teams from Sleeper player universe
4. WHEN fetching rosters, THE API SHALL include projected points from the Projection Service when available
5. WHEN fetching rosters, THE API SHALL include matchup grades from the Matchup Grade Service when available
6. THE Roster Response SHALL categorize players as starters, bench, or reserve based on Sleeper slot assignments
7. THE Roster Response SHALL include injury status and bye week information for each player
8. ALL roster endpoint responses SHALL normalize IDs to strings for consistency
9. WHEN a league or user cannot be found, THE API SHALL return HTTP 404 with descriptive error message
10. THE API SHALL maintain separation from existing draft-only endpoints under the `/in-season/` path prefix

### Requirement 8: Start/Sit Recommendations API

**User Story:** As a fantasy manager, I want personalized start/sit recommendations for my roster each week, so that I can set my optimal lineup.

#### Acceptance Criteria

1. THE FastAPI SHALL provide a `GET /api/v1/in-season/{league_id}/{user_id}/recommendations` endpoint returning start/sit advice
2. WHEN generating recommendations, THE API SHALL fetch the user's roster from Sleeper
3. WHEN generating recommendations, THE API SHALL fetch current NFL week and season from `get_nfl_state()`
4. WHEN generating recommendations, THE API SHALL load projections for the current week and league scoring format
5. WHEN generating recommendations, THE API SHALL apply exclusions (bye, injuries, IR/TAXI) via Lineup Optimizer
6. WHEN generating recommendations, THE API SHALL compute optimal lineup assignment via `assign_lineup`
7. THE Recommendations Response SHALL include each player with `recommendation` as "START", "SIT", "SIT (BYE)", or "SIT (INJURY)"
8. THE Recommendations Response SHALL include assigned slot for START recommendations
9. THE Recommendations Response SHALL include matchup grade for each player when available
10. THE Recommendations Response SHALL include a boolean `optimal_lineup_set` indicating if a full optimal lineup was found
11. WHEN projections are not yet available for the current week, THE API SHALL return HTTP 503 with clear message
12. THE API SHALL handle empty rosters by returning `optimal_lineup_set=false` with empty recommendations list

### Requirement 9: Free Agent Waiver Recommendations (Phase 1)

**User Story:** As a fantasy manager, I want to see ranked free agents by position and projected value, so that I can identify potential waiver pickups.

#### Acceptance Criteria

1. THE FastAPI SHALL provide a `GET /api/v1/in-season/{league_id}/waiver` endpoint returning free agent rankings
2. WHEN generating waiver rankings, THE Waiver Service SHALL compute free agent pool as: all NFL players - all rostered players in league
3. WHEN generating waiver rankings, THE Waiver Service SHALL augment with Sleeper trending-add counts when available
4. THE Waiver Service SHALL rank free agents by projected points descending
5. WHERE projected points are equal, THE Waiver Service SHALL use trending-add counts as tiebreaker (descending)
6. WHEN a `position` filter is provided, THE Waiver Service SHALL filter results to that position only
7. THE Waiver Response SHALL include `player_id`, `player_name`, `position`, `team`, `projected_points`, and `trending_add_count`
8. THE Waiver Response SHALL include a 1-indexed `rank` for each recommendation
9. THE Waiver Service SHALL respect the `limit` parameter to control result count (default 50)
10. FOR ALL waiver recommendations, THE Waiver Service SHALL ensure no rostered player appears in results
11. WHEN no free agents match criteria, THE API SHALL return empty recommendations list with HTTP 200

### Requirement 10: Drop/Add Optimization (Phase 2)

**User Story:** As a fantasy manager, I want drop/add pair recommendations that maximize my roster's projected points, so that I can make strategic waiver wire moves.

#### Acceptance Criteria

1. THE FastAPI SHALL provide a `GET /api/v1/in-season/{league_id}/{user_id}/drop-add` endpoint returning drop/add pair rankings
2. WHEN generating drop/add recommendations, THE Waiver Service SHALL identify drop candidates as user's bench players (not starters, not reserve)
3. WHEN generating drop/add recommendations, THE Waiver Service SHALL identify add candidates as free agents (not rostered league-wide)
4. THE Waiver Service SHALL compute net gain as: `add_projected_points - drop_projected_points`
5. THE Waiver Service SHALL only include pairs with positive net gain (strict upgrades)
6. THE Waiver Service SHALL rank drop/add pairs by net gain descending
7. WHERE net gains are equal, THE Waiver Service SHALL prefer same-position swaps as tiebreaker
8. THE Drop/Add Response SHALL include `drop_player_id`, `drop_player_name`, `drop_projected_points`, `add_player_id`, `add_player_name`, `add_projected_points`, `position`, and `net_gain`
9. THE Drop/Add Response SHALL include a 1-indexed `rank` for each recommendation
10. THE Waiver Service SHALL respect the `limit` parameter to control result count (default 20)
11. FOR ALL drop/add recommendations, THE Waiver Service SHALL ensure add player is a free agent and drop player is on user's bench
12. WHEN no positive net gain pairs exist, THE API SHALL return empty recommendations list with HTTP 200

### Requirement 11: Daily Data Refresh Pipeline

**User Story:** As a system operator, I want automated daily data refreshes via Airflow DAGs, so that matchup grades and projections stay current throughout the NFL season.

#### Acceptance Criteria

1. THE Airflow DAG SHALL run daily during the NFL season (approximately weeks 1-18)
2. THE Airflow DAG SHALL ingest new NFLVerse data via nflreadpy to `data/raw/`
3. THE Airflow DAG SHALL execute dbt-duckdb transformations to rebuild all marts
4. THE Airflow DAG SHALL execute the Projection Service to generate new weekly projections
5. THE Airflow DAG SHALL handle dependencies: data ingestion → dbt transform → projection generation
6. WHEN any step fails, THE Airflow DAG SHALL retry according to configured retry policies
7. THE Airflow DAG SHALL send alerts on critical failures via configured notification channels
8. THE Airflow DAG SHALL respect NFL bye weeks and schedule changes (using `stg_schedules` as source of truth)
9. THE Airflow DAG SHALL be tested via DAG import tests and task structure validation
10. THE Airflow DAG SHALL be deployable to both development and production environments

### Requirement 12: Error Handling and Graceful Degradation

**User Story:** As a user, I want the system to handle errors gracefully and provide helpful feedback, so that I can use the feature even when some components are temporarily unavailable.

#### Acceptance Criteria

1. WHEN `mart_matchup_grade` is missing or empty, THE Matchup Grade Service SHALL return neutral defaults instead of raising exceptions
2. WHEN projection files are not yet generated for a week, THE API SHALL return HTTP 503 with clear "projections pending" message
3. WHEN Sleeper API calls fail, THE Sleeper Client SHALL return empty lists/None instead of raising exceptions
4. WHEN dbt transformations fail, THE Airflow DAG SHALL alert operators and stop subsequent tasks
5. FOR ALL API endpoints, THE System SHALL return appropriate HTTP status codes (200, 404, 503) with descriptive messages
6. WHEN a user requests recommendations for a deleted league, THE API SHALL return HTTP 404 "league not found"
7. WHEN environment variable `MART_S3_BUCKET` is not set, THE Projections Store SHALL fall back to local files without error
8. THE System SHALL log all errors with sufficient context for debugging
9. THE System SHALL never expose internal implementation details in error responses
10. WHERE possible, THE System SHALL continue operating with degraded functionality rather than complete failure

### Requirement 13: Testing and Validation

**User Story:** As a quality engineer, I want comprehensive testing at all layers, so that we maintain correctness and prevent regressions.

#### Acceptance Criteria

1. THE dbt models SHALL have schema tests defined in `schema.yml` files for data validation
2. THE dbt models SHALL have relationships tests ensuring referential integrity between tables
3. THE Python services SHALL have unit tests mocking external dependencies (Sleeper API, file I/O)
4. THE Python services SHALL have property-based tests for core algorithms (no future leak, grade bounds, optimality)
5. THE API endpoints SHALL have integration tests using `TestClient` with mocked dependencies
6. THE Airflow DAG SHALL have DAG structure tests validating task dependencies and importability
7. ALL tests SHALL run in CI/CD pipeline on every commit
8. Property tests SHALL verify: no future leak in projections, grade bounds 0-100, lineup optimality beats greedy
9. Unit tests SHALL verify: graceful degradation returns defaults, exclusion logic filters correct players
10. Integration tests SHALL verify: end-to-end flow from API request to enriched response
11. Test coverage SHALL exceed 80% for all Python service modules
12. Test data SHALL be isolated from production data and cleaned up after test execution

### Requirement 14: System Integration and Separation

**User Story:** As a system architect, I want clear separation between in-season features and existing draft features, so that both can evolve independently without conflicts.

#### Acceptance Criteria

1. ALL new in-season endpoints SHALL be under the `/api/v1/in-season/` path prefix
2. NO existing draft endpoints under `/api/v1/drafts/` or `/api/v1/users/` SHALL be modified
3. THE in-season feature SHALL reuse the existing `SleeperClient` singleton for API calls
4. THE in-season feature SHALL follow existing ID normalization convention (all IDs as strings)
5. THE in-season feature SHALL follow existing error handling patterns (defensive programming, graceful defaults)
6. THE dbt-duckdb transform layer SHALL be a new subdirectory within the existing dbt project
7. THE Python services SHALL be in new `src/services/` directory, separate from existing `src/data_sources/`
8. THE Projections Store SHALL follow the same S3-fallback pattern as existing `adp_sources.py`
9. API response models SHALL extend the existing `models.py` with new Pydantic models
10. THE System SHALL maintain backward compatibility: draft features continue working unchanged
11. Code organization SHALL make dependencies clear: dbt transforms → Python services → API endpoints
12. Documentation SHALL clearly distinguish in-season features from draft features