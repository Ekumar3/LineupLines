# Implementation Plan: In-Season Matchup Recommendations

## Overview

This plan implements the In-Season Matchup Recommendations feature, which extends the LineupLines Fantasy Football API with weekly start/sit and waiver recommendations driven by OL/DL matchup analysis. The implementation builds a dbt-duckdb SQL transformation layer over free NFLVerse data (play-by-play, player stats, snap counts, schedules), layers Python prediction services (projections, matchup grading, lineup optimization, waiver analysis) on top, exposes everything under dedicated `/api/v1/in-season/` FastAPI endpoints, and automates daily refreshes via an Airflow DAG. All new functionality is kept separate from existing draft-only features.

The work proceeds incrementally: dbt intermediate models → grade/matchup/feature marts → storage and matchup services → Sleeper client extensions → roster/projection/lineup services and APIs → waiver and drop/add services and APIs → Airflow orchestration → comprehensive testing → documentation and deployment prep. Each step builds on prior steps and wires into the running API so there is no orphaned code.

## Tasks

- [x] 1. dbt Intermediate Models - Team Pass and Run Metrics
  - **Objective**: Create `int_team_pass_metrics` and `int_team_run_metrics` models in dbt-duckdb to compute trailing team-game metrics from play-by-play data.
  - **Prerequisites**: NFLVerse play-by-play data available in `stg_pbp`; dbt-duckdb project configured.
  - Create `models/intermediate/int_team_pass_metrics.sql` with SQL from design document
  - Create `models/intermediate/int_team_run_metrics.sql` with SQL from design document
  - Add schema tests to `models/intermediate/schema.yml`: `pressure_rate_trailing` between 0 and 1; `sack_rate_trailing` between 0 and 1; `pass_epa_per_dropback_trailing` between -3 and 3; `stuff_rate_trailing` between 0 and 1; `yards_per_carry_trailing` between -5 and 15; `run_epa_per_carry_trailing` between -3 and 3; no nulls on trailing averages
  - Add custom singular test for monotonic `(season, week)` ordering
  - Verify no-future-leak property: only rows with `(season', week') < (target)` contribute
  - **Acceptance Criteria**: `dbt run --select int_team_pass_metrics` succeeds; `dbt test --select int_team_pass_metrics` passes; `dbt run --select int_team_run_metrics` succeeds; `dbt test --select int_team_run_metrics` passes; property test confirms no future data used in trailing calculations
  - **Validation**: Run dbt commands and verify test results
  - _Requirements: 1.3, 1.4, 1.12_

- [x] 2. dbt Marts - OL and DL Grades
  - **Objective**: Create `mart_ol_grade` and `mart_dl_grade` models that compute composite 0-100 grades from percentile ranks.
  - **Prerequisites**: Task 1 completed (`int_team_pass_metrics`, `int_team_run_metrics`).
  - Create `models/marts/mart_ol_grade.sql` with percentile rank calculation for offensive side
  - Create `models/marts/mart_dl_grade.sql` with percentile rank calculation for defensive side
  - Add schema tests to `models/marts/schema.yml`: all grade columns bounded [0, 100]; `pass_protection_grade`, `run_blocking_grade`, `ol_grade` not null; `pass_rush_grade`, `run_defense_grade`, `dl_grade` not null
  - Add weight validation: pass protection 60%, run blocking 40% of OL grade
  - Add weight validation: pass rush 60%, run defense 40% of DL grade
  - **Acceptance Criteria**: `dbt run --select mart_ol_grade` succeeds; `dbt test --select mart_ol_grade` passes; `dbt run --select mart_dl_grade` succeeds; `dbt test --select mart_dl_grade` passes; property test confirms all grades between 0 and 100
  - **Validation**: Run dbt commands and verify grade bounds
  - _Requirements: 1.5, 1.6, 1.11_

- [x] 3. dbt Mart - Matchup Grade
  - **Objective**: Create `mart_matchup_grade` that joins OL grades with opponent DL grades for all scheduled games.
  - **Prerequisites**: Task 2 completed (`mart_ol_grade`, `mart_dl_grade`); `stg_schedules` available.
  - Create `models/marts/mart_matchup_grade.sql` with join logic from design document
  - Explode each scheduled game into two offensive perspectives (home vs away, away vs home)
  - Compute `pass_matchup`, `rush_matchup`, `overall_matchup` as OL grade - DL grade
  - Assign signals: favorable (>10), unfavorable (<-10), neutral (otherwise)
  - Add schema tests to `models/marts/schema.yml`: all matchup columns not null; signals match grade differences (custom test); every `(season, week, team)` in `stg_schedules` has a matchup row
  - Add relationships test with `stg_schedules`
  - **Acceptance Criteria**: `dbt run --select mart_matchup_grade` succeeds; `dbt test --select mart_matchup_grade` passes; property test confirms signal assignment matches threshold rules; property test confirms complete coverage of scheduled games
  - **Validation**: Verify all scheduled games have matchup rows, signals correct
  - _Requirements: 1.7, 3.8, 3.9, 3.10_

- [x] 4. dbt Feature Mart - Player Week Features
  - **Objective**: Create `mart_player_week_features` and `int_defense_factor_inputs` for Python projection service.
  - **Prerequisites**: `stg_player_stats`, `stg_snap_counts`, `stg_schedules` available.
  - Create `models/intermediate/int_defense_factor_inputs.sql` with team-game yardage aggregation
  - Create `models/marts/mart_player_week_features.sql` with feature construction from design document
  - Implement name normalization logic matching `research/model.py::_normalize_name`
  - Join snap counts on normalized name + team + week
  - Add implied team totals from schedules (total_line, spread_line)
  - Add schema tests to `models/marts/schema.yml`: `player_id` not null + unique with `(season, week)`; `offense_pct` in [0, 1]; `implied_team_total` in [0, 60]; no nulls on the 9 stat components; all 9 stat components present
  - Add primary key test for `(player_id, season, week)`
  - **Acceptance Criteria**: `dbt run --select int_defense_factor_inputs,mart_player_week_features` succeeds; `dbt test --select int_defense_factor_inputs,mart_player_week_features` passes; property test confirms feature table contains all required columns; property test confirms name normalization works correctly
  - **Validation**: Verify feature table structure and completeness
  - _Requirements: 1.8, 1.9_

- [x] 5. Projections Store and Matchup Grade Service
  - [x] 5.1 Implement projections store and matchup grade service
    - **Objective**: Implement `projections_store.py` and `matchup_grade.py` services.
    - **Prerequisites**: dbt marts built (Tasks 1-4); Python environment with polars, boto3 (optional).
    - Create `src/data_sources/projections_store.py`: `load_mart(name, season)` with S3/local fallback; `load_projections(season, week, scoring_format)`; `write_projections(df, season, week, scoring_format)`; graceful degradation where missing files return empty DataFrame
    - Create `src/services/matchup_grade.py`: `MatchupGrade` dataclass; `MatchupGradeService` with `grade_for()` method; lazy-load and cache `mart_matchup_grade`; neutral default when no matching row
    - **Acceptance Criteria**: Projections Store loads marts from local files; Matchup Grade Service returns correct grades for test data; neutral default returned for missing matchups
    - **Validation**: Run tests, verify file I/O works, test with sample data
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.11_

  - [x]* 5.2 Write unit tests for projections store and matchup grade service
    - Projections Store returns empty DataFrame for missing files
    - Matchup Grade Service returns neutral default for missing data
    - Signal assignment matches thresholds
    - _Requirements: 2.6, 2.8, 3.3_

  - [x]* 5.3 Write property tests for graceful degradation and signal consistency
    - **Property 10, 20: Graceful degradation**
    - **Property 13: Signal consistency**
    - _Requirements: 2.8, 3.11, 3.8, 3.9, 3.10_

- [x] 6. Sleeper Client Extensions
  - [x] 6.1 Extend SleeperClient with in-season API methods
    - **Objective**: Extend `SleeperClient` with in-season API methods.
    - **Prerequisites**: Existing `SleeperClient` in `src/data_sources/sleeper_client.py`.
    - Add `Roster` dataclass to sleeper_client.py
    - Add `get_league_rosters(league_id)` method: calls `/league/{league_id}/rosters`; normalizes all IDs to strings; returns `List[Roster]` or empty list on error; computes bench as `players - starters - reserve`
    - Add `get_nfl_state()` method: calls `/state/nfl`; returns `{week, season, season_type}` or None on error
    - Add `get_league_transactions(league_id, week)` method
    - Add `get_trending_players(type, lookback_hours, limit)` method
    - **Acceptance Criteria**: New methods integrate with existing rate limiting; all IDs normalized to strings; defensive error handling (never raises); bench computation matches design
    - **Validation**: Test with mock Sleeper API responses, verify error handling
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9_

  - [x]* 6.2 Write unit tests for Sleeper client extensions
    - ID normalization to strings
    - Error handling returns empty lists/None
    - Bench computation correct
    - _Requirements: 5.5, 5.6, 5.9_

  - [x]* 6.3 Write property tests for ID normalization and error resilience
    - **Property 11: ID normalization**
    - **Property 25: Error resilience**
    - _Requirements: 5.5, 5.6_

- [x] 7. Roster Management API Endpoints
  - [x] 7.1 Implement roster management endpoints
    - **Objective**: Implement `/in-season/{lid}/rosters` and `/in-season/{lid}/{uid}/roster` endpoints.
    - **Prerequisites**: Task 6 completed (Sleeper Client extensions); existing FastAPI app in `src/api/main.py`.
    - Add Pydantic models to `src/api/models.py`: `MatchupGradeResponse`, `RosterPlayer`, `RosterResponse`, `LeagueRostersResponse`
    - Add `GET /api/v1/in-season/{league_id}/rosters` endpoint: calls `sleeper_client.get_league_rosters()`; enriches with player names/positions/teams; adds projected points when available; adds matchup grades when available; returns `LeagueRostersResponse`
    - Add `GET /api/v1/in-season/{league_id}/{user_id}/roster` endpoint: filters league rosters for specific user; returns `RosterResponse` with starters/bench/reserve
    - **Acceptance Criteria**: Endpoints return HTTP 200 with correct structure; player enrichment works (names, positions, teams); starters/bench/reserve categorization correct; 404 returned for missing league/user
    - **Validation**: Test with sample league data, verify response format
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10_

  - [x]* 7.2 Write integration tests for roster endpoints
    - Mock Sleeper API responses
    - Verify response structure
    - Verify error handling (404 for missing league)
    - _Requirements: 7.1, 7.2, 7.9_

  - [x]* 7.3 Write property tests for roster responses
    - **Property 11: ID normalization in responses**
    - **Property 28: Roster categorization consistency**
    - _Requirements: 7.6, 7.8_

- [x] 8. Projection Service Implementation
  - [x] 8.1 Implement projection service refactored from research code
    - **Objective**: Implement `projection_service.py` refactored from research code.
    - **Prerequisites**: Task 4 completed (feature mart); Task 5 completed (projections store).
    - Create `src/services/projection_service.py`: `Projection` dataclass; `ProjectionService` class with `load_marts()`, `project_week()`, `write_output()`; port `research/model.py` v2.1.0 algorithm; port `research/defense.py` ridge regression
    - Implement no-future-leak guarantees: baseline uses only rows with `(season', week') < (target)`; defense factors use only prior games
    - Implement defense factor clamping [0.75, 1.25]
    - Implement prior-season weighting (0.3)
    - **Acceptance Criteria**: Service produces projections matching research model output; no future data leaks into calculations; defense factors clamped correctly; writes projections to storage via projections store
    - **Validation**: Compare with research model on test data, verify properties
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12_

  - [x]* 8.2 Write unit tests for projection service
    - Baseline calculation with trailing window
    - Defense factor computation
    - Scoring formula application
    - _Requirements: 4.3, 4.4, 4.6_

  - [x]* 8.3 Write property tests for projection service
    - **Property 1, 19: No future leak**
    - **Property 7: Defense factor bounds**
    - **Property 30: Prior-season weighting**
    - **Property 29: Baseline window**
    - **Property 18: Scoring correctness**
    - _Requirements: 4.11, 4.8, 4.9, 4.3, 4.6_

- [x] 9. Lineup Optimizer Implementation
  - [x] 9.1 Implement lineup optimizer refactored from research code
    - **Objective**: Implement `lineup_optimizer.py` refactored from research code.
    - **Prerequisites**: Task 8 completed (projection service).
    - Create `src/services/lineup_optimizer.py`: `OptimizerPlayer` dataclass; `apply_exclusions()` method; `assign_lineup()` method using `scipy.optimize.linear_sum_assignment`; `eligible_positions()` helper; `starting_slots()` helper
    - Implement exclusion logic: bye week players excluded; OUT/DOUBTFUL excluded; IR/TAXI excluded; QUESTIONABLE included at full value
    - Implement max-weight bipartite matching: build cost matrix with eligibility constraints; use Hungarian algorithm for optimal solution; dummy columns for benching players
    - **Acceptance Criteria**: Optimizer finds globally optimal lineups; exclusion logic matches design; position eligibility rules enforced; beats greedy algorithm on test cases
    - **Validation**: Test with sample rosters, compare to greedy algorithm
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10, 6.11, 6.12_

  - [x]* 9.2 Write unit tests for lineup optimizer
    - Exclusion logic filters correct players
    - Optimal assignment beats greedy
    - Position eligibility respected
    - _Requirements: 6.2, 6.7, 6.8_

  - [x]* 9.3 Write property tests for lineup optimizer
    - **Property 4: Lineup optimality**
    - **Property 5: Lineup eligibility**
    - **Property 6: Exclusion correctness**
    - Empty slot handling
    - _Requirements: 6.9, 6.10, 6.3, 6.4, 6.5, 6.11_

- [x] 10. Start/Sit Recommendations API Endpoint
  - [x] 10.1 Implement start/sit recommendations endpoint
    - **Objective**: Implement `/in-season/{lid}/{uid}/recommendations` endpoint.
    - **Prerequisites**: Tasks 7, 8, 9 completed (roster API, projection service, lineup optimizer).
    - Add Pydantic models to `src/api/models.py`: `StartSitRecommendation`, `RecommendationsResponse`
    - Add `GET /api/v1/in-season/{league_id}/{user_id}/recommendations` endpoint: fetch user roster (Task 7); get NFL state for current week; load projections for current week + league scoring; apply exclusions via lineup optimizer; compute optimal lineup assignment; enrich with matchup grades; return recommendations with START/SIT labels
    - Handle edge cases: projections not available → HTTP 503; empty roster → `optimal_lineup_set=false`; missing league/user → 404
    - **Acceptance Criteria**: Endpoint returns personalized start/sit recommendations; optimal lineup computed correctly; matchup grades included when available; appropriate HTTP codes for error cases
    - **Validation**: Test with sample league and user, verify recommendations make sense
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 8.12_

  - [x]* 10.2 Write integration tests for recommendations endpoint
    - Mock all dependencies
    - Verify recommendation logic
    - Test error cases
    - _Requirements: 8.7, 8.11, 8.12_

  - [x]* 10.3 Write property tests for recommendations endpoint
    - **Property 24: Optimal lineup flag accuracy**
    - **Property 17: Error response safety**
    - _Requirements: 8.10, 8.11_

- [x] 11. Waiver Service - Free Agent Ranking
  - [x] 11.1 Implement waiver service Phase 1 free agent ranking
    - **Objective**: Implement `waiver_service.py` Phase 1 (free agent ranking).
    - **Prerequisites**: Tasks 6, 8 completed (Sleeper client, projection service).
    - Create `src/services/waiver_service.py`: `WaiverRec` dataclass; `WaiverService` class with `free_agent_ranking()` method
    - Implement free agent pool calculation: get all rostered player IDs in league; filter projections to players not in rostered set
    - Implement ranking logic: sort by projected points descending; tiebreak by trending-add counts descending; apply position filter if provided; apply limit parameter
    - Add trending data augmentation: call `sleeper_client.get_trending_players('add')`; merge counts into results
    - **Acceptance Criteria**: Service ranks FAs by projected points; rostered players excluded from results; trending data merged when available; position filtering works; limit parameter respected
    - **Validation**: Test with sample league data, verify ranking logic
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 9.10, 9.11_

  - [x]* 11.2 Write unit tests for waiver free agent ranking
    - FA pool excludes rostered players
    - Ranking order correct
    - Position filtering works
    - Limit enforcement
    - _Requirements: 9.2, 9.4, 9.6, 9.9_

  - [x]* 11.3 Write property tests for waiver free agent ranking
    - **Property 8: Waiver pool correctness**
    - **Property 15: Ranking order**
    - **Property 22: Position filter**
    - **Property 23: Limit enforcement**
    - _Requirements: 9.2, 9.4, 9.6, 9.9, 9.10_

- [x] 12. Waiver Recommendations API Endpoint
  - [x] 12.1 Implement waiver recommendations endpoint Phase 1
    - **Objective**: Implement `/in-season/{lid}/waiver` endpoint (Phase 1).
    - **Prerequisites**: Task 11 completed (waiver service).
    - Add Pydantic models to `src/api/models.py`: `WaiverRecResponse`, `WaiverResponse`
    - Add `GET /api/v1/in-season/{league_id}/waiver` endpoint: call `waiver_service.free_agent_ranking()`; apply position query parameter filter; apply limit parameter (default 50); return ranked recommendations
    - Handle empty results case (HTTP 200 with empty list)
    - Add error handling: missing league → 404; missing projections → 503
    - **Acceptance Criteria**: Endpoint returns ranked free agents; position filtering works; limit parameter respected; empty results handled gracefully
    - **Validation**: Test with sample league, verify ranking makes sense
    - _Requirements: 9.1, 9.6, 9.9, 9.11_

  - [x]* 12.2 Write integration tests for waiver endpoint
    - Mock projections and Sleeper data
    - Verify ranking logic
    - Test position filtering
    - Test limit parameter
    - _Requirements: 9.4, 9.6, 9.9, 9.11_

- [x] 13. Airflow DAG for Daily Data Refresh
  - [x] 13.1 Create Airflow DAG for daily NFL season data pipeline
    - **Objective**: Create Airflow DAG that runs daily NFL season data pipeline.
    - **Prerequisites**: Airflow environment configured; dbt-duckdb project deployable; Python services importable.
    - Create `airflow/dags/in_season_pipeline.py`: daily schedule during NFL season (weeks 1-18); Task 1 ingest NFLVerse data via nflreadpy; Task 2 run dbt transformations; Task 3 generate projections via projection service; task dependencies ingest → dbt → projections
    - Configure error handling: retry policies (3 attempts with backoff); alerts on critical failures; skip on bye weeks (check `stg_schedules`)
    - Configure environment variables: `MART_S3_BUCKET` for production; local fallback for development
    - Add monitoring: success/failure notifications; duration tracking; data quality checks
    - **Acceptance Criteria**: DAG imports successfully; tasks execute in correct order; retry policies work; bye week skipping works; alerts configured
    - **Validation**: Test DAG in development, verify task execution
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.10_

  - [x]* 13.2 Write DAG structure tests
    - `test_dag_import.py` for importability
    - Task dependency validation
    - Schedule validation
    - _Requirements: 11.9_

- [x] 14. Waiver Service - Drop/Add Optimization
  - [x] 14.1 Implement waiver service Phase 2 drop/add optimization
    - **Objective**: Implement `waiver_service.py` Phase 2 (drop/add optimization).
    - **Prerequisites**: Tasks 11, 7 completed (FA ranking, roster API).
    - Extend `src/services/waiver_service.py`: `DropAddRec` dataclass; `drop_add_optimization()` method
    - Implement drop candidate identification: get user roster (starters + bench + reserve); drop candidates = bench players only
    - Implement add candidate identification: free agents (not rostered league-wide)
    - Compute net gain for all pairs: `net_gain = add_projected - drop_projected`; only include pairs with positive net gain
    - Implement ranking logic: sort by net gain descending; tiebreak prefer same-position swaps; apply limit parameter
    - **Acceptance Criteria**: Service identifies correct drop/add pairs; only positive net gain pairs included; ranking by net gain descending; same-position tiebreak works; limit parameter respected
    - **Validation**: Test with sample roster and FA pool, verify pairs make sense
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 10.10, 10.11, 10.12_

  - [x]* 14.2 Write unit tests for drop/add optimization
    - Drop candidates = bench only (not starters/reserve)
    - Add candidates = free agents only
    - Only positive net gain pairs included
    - Ranking order correct
    - _Requirements: 10.2, 10.3, 10.5, 10.6_

  - [x]* 14.3 Write property tests for drop/add optimization
    - **Property 9: Drop/add correctness**
    - **Property 16: Ranking order**
    - **Property 23: Limit enforcement**
    - _Requirements: 10.5, 10.6, 10.10, 10.11_

- [x] 15. Drop/Add Recommendations API Endpoint
  - [x] 15.1 Implement drop/add recommendations endpoint Phase 2
    - **Objective**: Implement `/in-season/{lid}/{uid}/drop-add` endpoint (Phase 2).
    - **Prerequisites**: Task 14 completed (drop/add optimization).
    - Add Pydantic models to `src/api/models.py`: `DropAddRecResponse`, `DropAddResponse`
    - Add `GET /api/v1/in-season/{league_id}/{user_id}/drop-add` endpoint: call `waiver_service.drop_add_optimization()`; apply limit parameter (default 20); return ranked drop/add pairs
    - Handle edge cases: no positive net gain pairs → empty list (HTTP 200); missing league/user → 404; missing projections → 503
    - Add validation: drop player is on user's bench; add player is a free agent; net gain positive
    - **Acceptance Criteria**: Endpoint returns ranked drop/add pairs; only positive net gain pairs included; limit parameter respected; empty results handled gracefully; validation ensures correctness properties
    - **Validation**: Test with sample user roster, verify recommendations make sense
    - _Requirements: 10.1, 10.8, 10.9, 10.10, 10.11, 10.12_

  - [x]* 15.2 Write integration tests for drop/add endpoint
    - Mock roster and projections
    - Verify drop/add logic
    - Test limit parameter
    - Test empty results case
    - _Requirements: 10.10, 10.11, 10.12_

- [x] 16. Comprehensive Testing Suite
  - [x]* 16.1 Build property test module and strategies
    - **Objective**: Create comprehensive test suite covering all correctness properties.
    - **Prerequisites**: All previous tasks completed; Hypothesis library installed for property testing.
    - Create property test module `tests/property_tests/`: `test_no_future_leak.py` (Property 1, 19); `test_grade_bounds.py` (Property 2); `test_lineup_optimality.py` (Property 4, 5, 6); `test_waiver_correctness.py` (Property 8, 9, 15, 16); `test_graceful_degradation.py` (Property 10, 20, 25); `test_signal_assignment.py` (Property 13); `test_id_normalization.py` (Property 11); `test_error_safety.py` (Property 17)
    - Implement hypothesis strategies: generate synthetic NFL data (games, players, stats); generate league configurations (roster positions, scoring); generate user rosters with various states
    - **Acceptance Criteria**: All property tests pass with 100+ iterations
    - _Requirements: 13.4, 13.8_

  - [x]* 16.2 Add integration coverage and configure CI/CD
    - Add integration test coverage: end-to-end API flows; error scenario simulations; performance benchmarks
    - Configure CI/CD pipeline: run all tests on every commit; enforce 80%+ coverage requirement; property tests with 100+ iterations each
    - Add test data management: isolated test databases/files; cleanup after test execution; deterministic test data generation
    - **Acceptance Criteria**: Unit test coverage > 80% for all service modules; integration tests cover all API endpoints; CI/CD pipeline runs all tests successfully; test data properly isolated and cleaned
    - **Validation**: Run full test suite, verify coverage, check CI pipeline
    - _Requirements: 13.1, 13.2, 13.3, 13.5, 13.6, 13.7, 13.9, 13.10, 13.11, 13.12_

- [x] 17. Documentation and Deployment Preparation
  - [x] 17.1 Write documentation and deployment guide
    - **Objective**: Create documentation and prepare for production deployment.
    - **Prerequisites**: All implementation tasks completed; all tests passing.
    - Update `docs/ARCHITECTURE.md`: add in-season feature architecture section; document data flow diagrams; explain separation from draft features
    - Update `docs/API.md`: document all `/in-season/` endpoints; provide request/response examples; document error codes and messages
    - Create deployment guide: environment variable configuration; S3 bucket setup for production; Airflow deployment instructions; monitoring and alerting setup
    - Update `AGENTS.md` project overview: add in-season feature description; update development commands; document new testing patterns
    - Perform final validation: verify all correctness properties hold; test with real Sleeper league (development); performance testing with sample data; security review (no secrets in code, input validation)
    - **Acceptance Criteria**: Documentation complete and accurate; deployment guide covers all scenarios; architecture clearly documented; API documentation with examples; final validation passes; ready for production deployment
    - **Validation**: Review documentation, test deployment steps, verify properties
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 14.8, 14.9, 14.10, 14.11, 14.12_

- [x] 18. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- The staging dbt models (`stg_pbp`, `stg_player_stats`, `stg_snap_counts`, `stg_schedules`) and base project scaffolding are already built; this plan starts from the intermediate/mart layer onward.
- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP, but are recommended for property and regression coverage.
- Each task references specific requirements for traceability.
- Property tests validate universal correctness properties defined in the design (no future leak, grade bounds, lineup optimality, waiver correctness, graceful degradation).
- The checkpoint ensures incremental validation before declaring the feature complete.
- All new code lives under `/api/v1/in-season/`, `src/services/`, and new dbt intermediate/mart models, keeping draft features untouched.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["3", "9.1", "11.1", "13.1", "5.2", "5.3", "6.2", "6.3", "7.2", "7.3", "8.2", "8.3"] },
    { "id": 1, "tasks": ["10.1", "12.1", "14.1", "9.2", "9.3", "11.2", "11.3", "13.2"] },
    { "id": 2, "tasks": ["15.1", "10.2", "10.3", "12.2", "14.2", "14.3"] },
    { "id": 3, "tasks": ["17.1", "15.2", "16.1"] },
    { "id": 4, "tasks": ["16.2"] }
  ]
}
```
