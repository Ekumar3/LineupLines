# In-season property tests

Hypothesis-based property tests for the **in-season-matchup-recommendations**
feature. Each test validates a universal correctness property defined in
`.kiro/specs/in-season-matchup-recommendations/design.md` (Properties 1–30).

## Running

```bash
# Full suite (defaults to the "ci" profile: >= 100 examples per property)
C:/Python310/python.exe -m pytest tests/property_tests/ -q

# Fast local iteration (25 examples per property)
HYPOTHESIS_PROFILE=dev C:/Python310/python.exe -m pytest tests/property_tests/ -q
```

The Hypothesis profiles (`ci`, `dev`) are registered in
[`conftest.py`](./conftest.py). The `ci` profile is the default and guarantees
every property runs at the design's 100-iteration floor; a per-test
`@settings(max_examples=...)` that asks for more (200/300) still wins.

## Shared strategies

[`strategies.py`](./strategies.py) factors out the common Hypothesis generators
each test file otherwise redefines:

| Generator | Produces |
| --- | --- |
| `feature_row` / `features_frame` / `player_feature_history` | `mart_player_week_features`-shaped projection inputs |
| `stat_line` | a bounded 9-component stat line |
| `defense_input_rows` | `int_defense_factor_inputs`-shaped round-robin schedule |
| `scoring_settings` / `unit_scoring` | league scoring dicts over the 9 stat components |
| `projections_frame` | a waiver/recommendations projections polars frame |
| `league_roster` / `league_rosters` | Sleeper `Roster` objects (shared id space) |
| `roster_positions` | a league `roster_positions` slot config |
| `trending_payload` | a Sleeper trending-add payload |

> **Note on existing files.** The property-test files predate `strategies.py`
> and each carry their own inline composites. They are intentionally left
> unchanged — refactoring a green test to import from the shared module would
> risk regressing it for no behavioural gain. `strategies.py` is the canonical
> source for **new** property tests; the existing inline generators are the
> templates it was distilled from.

## Property → test coverage matrix

Each design property maps to the test (or dbt artifact) that validates it.
Python property tests live in this directory; data-layer properties are
enforced by dbt schema/singular tests and are **not** re-implemented in Python.

| # | Property | Validated by |
| --- | --- | --- |
| 1 | No future leak (projections) | `test_projection_service_properties.py::test_projection_invariant_to_future_rows` |
| 2 | Grade bounds (0 ≤ grade ≤ 100) | **dbt** — `dbt_utils.accepted_range` (min 0 / max 100) on `ol_grade`, `dl_grade` and sub-grades in `dbt/models/marts/schema.yml`. No Python grade-bounds property. |
| 3 | Matchup coverage | **dbt** — `dbt/tests/assert_matchup_covers_all_scheduled_games.sql` |
| 4 | Lineup optimality | `test_lineup_optimizer_properties.py::test_assignment_never_worse_than_greedy` |
| 5 | Lineup eligibility | `test_lineup_optimizer_properties.py::test_assignment_respects_eligibility_and_uniqueness` |
| 6 | Exclusion correctness | `test_lineup_optimizer_properties.py::test_exclusions_drop_exactly_the_ineligible` |
| 7 | Defense factor bounds | `test_projection_service_properties.py::test_defense_factors_within_clamp` |
| 8 | Waiver pool correctness | `test_waiver_service_properties.py::test_waiver_pool_excludes_all_rostered_players` |
| 9 | Drop/add correctness | `test_waiver_drop_add_properties.py::test_drop_add_correctness` |
| 10 | Graceful degradation | `test_graceful_degradation.py::test_grade_for_never_raises_and_returns_valid_signals` |
| 11 | ID normalization | `test_sleeper_client_properties.py::TestProperty11IdNormalization` + `test_roster_response_properties.py::TestProperty11IdNormalizationInResponses` |
| 12 | Draft features untouched | Structural (no `/api/v1/in-season/` endpoint touches `/drafts/` or `/users/`). Not a Python property test; guarded by route isolation. |
| 13 | Signal assignment consistency | `test_signal_assignment.py::test_signal_assignment_consistency` (+ **dbt** `assert_matchup_signal_thresholds.sql` for the authoritative threshold derivation) |
| 14 | Bench computation correctness | `test_roster_response_properties.py::TestProperty28RosterCategorizationConsistency` (bench = players − starters − reserve) and `test_sleeper_client_properties.py::test_bench_is_subset_of_normalized_players` |
| 15 | Free agent ranking order | `test_waiver_service_properties.py::test_ranking_is_sorted_and_ranks_are_contiguous` |
| 16 | Drop/add ranking order | `test_waiver_drop_add_properties.py::test_ranking_order_and_contiguous_ranks` |
| 17 | Error response safety | `test_recommendations_properties.py::TestProperty17ErrorResponseSafety` |
| 18 | Projection scoring correctness | `test_projection_service_properties.py::test_scoring_is_dot_product_of_line_and_settings` |
| 19 | No-future-leak in defense factors | `test_projection_service_properties.py::test_projection_invariant_to_future_rows` (+ **dbt** `assert_pass_metrics_no_future_leak.sql`) |
| 20 | Graceful file handling | `test_graceful_degradation.py::test_load_mart_never_raises_and_empty_when_missing`, `::test_load_projections_never_raises_and_empty_when_missing` |
| 21 | Season filtering correctness | **Not yet covered by a dedicated Python property** (candidate for a future `load_mart(name, season)` season-filter property using `strategies`). |
| 22 | Position filter correctness | `test_waiver_service_properties.py::test_position_filter_applied` |
| 23 | Limit parameter enforcement | `test_waiver_service_properties.py::test_limit_enforced` + `test_waiver_drop_add_properties.py::test_limit_enforced` |
| 24 | Optimal lineup flag accuracy | `test_recommendations_properties.py::TestProperty24OptimalLineupFlagAccuracy` |
| 25 | Sleeper API error resilience | `test_sleeper_client_properties.py::TestProperty25ErrorResilience` |
| 26 | Data validation test execution | **dbt** — pipeline runs `dbt test`; failures stop the Airflow task. Not a Python property test. |
| 27 | Environment fallback correctness | `test_graceful_degradation.py` (runs with `MART_S3_BUCKET` unset, exercising the local-filesystem fallback path) |
| 28 | Roster categorization consistency | `test_roster_response_properties.py::TestProperty28RosterCategorizationConsistency` |
| 29 | Baseline calculation window | `test_projection_service_properties.py::test_baseline_window_and_fallback` |
| 30 | Prior-season weighting | `test_projection_service_properties.py::test_prior_season_contributes_at_reduced_weight` |

### Coverage notes

- **Data-layer properties (2, 3, 26)** are enforced in the dbt layer and are
  deliberately **not** re-implemented in Python. Property 2 (grade bounds) in
  particular is covered by `dbt_utils.accepted_range` accepted-range tests on
  the mart grade columns plus the singular tests under `dbt/tests/*.sql`.
- **Property 13** has a Python passthrough test *and* an authoritative dbt
  singular test — the threshold derivation itself lives in the mart model.
- **Properties 12 and 21** have no dedicated Python property yet; 12 is a
  structural guarantee and 21 is a good candidate for a future test built on
  the shared `strategies` module.
