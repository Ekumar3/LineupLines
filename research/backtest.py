"""Backtest harness: simulate ~500 rosters across the 2025 season, compare
hindsight-optimal / v1 / v2 / naive lineups, and write research/results/backtest.md.

Strategies compared on identical rosters and weeks:
  hindsight  assignment on ACTUAL points (the ceiling)
  v1         four-delta scalar adjustment (research.model.project_player_week)
  v2         per-channel opponent-adjusted defense factors x Vegas level
             (research.model.project_player_week_v2 + research.defense)
  naive      trailing 3-week average, no adjustment

Also writes the per-player-week prediction log (see research/analysis.py) to
research/data/predictions/season={season}/week={week}/*.parquet — one row per
player-week per model version.

KNOWN v1/v2 LIMITATIONS (in addition to the v1 uniform-scaling limitation
documented in research/model.py):

  - No pregame injury/roster-status feed exists in this offline harness —
    nflverse doesn't carry one, and this harness deliberately never calls
    Sleeper. `injury_status`/`roster_status` are always null; the only real
    pregame exclusion applied is `on_bye` (the player's team has no game that
    week, per the schedule). A player who goes inactive without a bye is
    still projected normally and simply scores 0 actual points — that's a
    genuine, symmetric exposure for every strategy, not a bug.
  - K and DEF fall outside the 9-component stat-line model entirely. Every
    strategy uses the identical trailing-average estimate for K/DEF, so the
    model-vs-naive comparisons are driven entirely by QB/RB/WR/TE. DEF points
    are approximated from a points-allowed bucket derived from schedule final
    scores only — no sack/turnover/TD bonus (team-defense play-by-play isn't
    in this harness's data scope).
  - The prediction log only covers QB/RB/WR/TE, since K/DEF have no
    projected_*/actual_* 9-component stat line to log.
  - Both v1 and v2 share the same unshrunk trailing baseline, which
    over-projects rostered players by ~2 pts (survivorship — see the bias
    table in the report). That bias is common to v1, v2 AND naive, so it
    doesn't affect the relative comparison; fixing it is a separate change.
"""

import json
import logging
import math
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import polars as pl
from scipy import stats

from research import defense, model
from research.assignment import LineupPlayer, apply_exclusions, assign_lineup, starting_slots
from research.scoring import STAT_COMPONENTS, get_scoring_settings, score_stat_line

logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).resolve().parent / "results"
PREDICTIONS_DIR = Path(__file__).resolve().parent / "data" / "predictions"

TRAIN_SEASONS = (2024, 2025)  # 2024 supplies the prior-season fallback for week 1
TARGET_SEASON = 2025

N_ROSTERS = 500
RANDOM_SEED = 42

ROSTER_POSITIONS = [
    "QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "K", "DEF",
    "BN", "BN", "BN", "BN", "BN", "BN",
]
# How many of each position get sampled onto the 16-spot roster above
# (starters + bench combined; bench isn't slot-restricted by position).
ROSTER_COUNTS = {"QB": 2, "RB": 4, "WR": 5, "TE": 2, "K": 1, "DEF": 1}

MODEL_STRATEGIES = ("v1", "v2", "naive")
STRATEGIES = MODEL_STRATEGIES + ("hindsight",)
STRATEGY_LABELS = {
    "v1": "v1 (four-delta scalar)",
    "v2": "v2 (defense factors x Vegas)",
    "naive": "naive (trailing 3-wk avg)",
    "hindsight": "hindsight-optimal",
}

PPR = get_scoring_settings("ppr")


# ---------------------------------------------------------------------------
# K / DEF — outside the stat-line model; see module docstring limitations.
# ---------------------------------------------------------------------------

def def_points_allowed_bucket(points_allowed: int) -> float:
    """Standard points-allowed DEF score. No sack/turnover/TD bonus (out of data scope)."""
    if points_allowed == 0:
        return 10.0
    if points_allowed <= 6:
        return 7.0
    if points_allowed <= 13:
        return 4.0
    if points_allowed <= 20:
        return 1.0
    if points_allowed <= 27:
        return 0.0
    if points_allowed <= 34:
        return -1.0
    return -4.0


def build_def_table(schedules: pl.DataFrame) -> Dict[Tuple[str, int, int], float]:
    """(team, season, week) -> DEF fantasy score, from schedule final scores."""
    rows = schedules.select(
        "season", "week", "home_team", "away_team", "home_score", "away_score"
    ).to_dicts()
    table: Dict[Tuple[str, int, int], float] = {}
    for r in rows:
        if r["home_score"] is None or r["away_score"] is None:
            continue  # game not yet played
        table[(r["home_team"], r["season"], r["week"])] = def_points_allowed_bucket(r["away_score"])
        table[(r["away_team"], r["season"], r["week"])] = def_points_allowed_bucket(r["home_score"])
    return table


def kicker_fantasy_points(row: dict) -> float:
    """Standard kicker scoring from made/missed FGs by distance + PATs.

    nflverse's own `fantasy_points` column is computed purely from
    passing/rushing/receiving/fumbles categories (the same ones this
    harness's STAT_COMPONENTS models) and is ~0 for kickers — it does not
    cover field goals or PATs at all, so it can't be reused here.
    """
    pts = 3.0 * (row.get("fg_made_0_19", 0) + row.get("fg_made_20_29", 0) + row.get("fg_made_30_39", 0))
    pts += 4.0 * row.get("fg_made_40_49", 0)
    pts += 5.0 * (row.get("fg_made_50_59", 0) + row.get("fg_made_60_", 0))
    pts += 1.0 * row.get("pat_made", 0)
    pts -= 1.0 * row.get("fg_missed", 0)
    pts -= 1.0 * row.get("pat_missed", 0)
    return pts


_KICKER_RAW_COLUMNS = (
    "fg_made_0_19", "fg_made_20_29", "fg_made_30_39", "fg_made_40_49",
    "fg_made_50_59", "fg_made_60_", "fg_missed", "pat_made", "pat_missed",
)


def build_kicker_table(seasons: Sequence[int]) -> pl.DataFrame:
    """Raw weekly kicker rows, with fantasy_points recomputed from FG/PAT columns (see kicker_fantasy_points)."""
    stats_df = model.load_player_stats(seasons).filter(pl.col("position") == "K")
    stats_df = stats_df.with_columns(
        pl.struct(_KICKER_RAW_COLUMNS)
        .map_elements(lambda s: kicker_fantasy_points(dict(s)), return_dtype=pl.Float64)
        .alias("fantasy_points")
    )
    return stats_df.select("player_id", "player_display_name", "team", "season", "week", "fantasy_points")


def team_has_game(schedules: pl.DataFrame) -> Dict[Tuple[str, int, int], bool]:
    rows = schedules.select("season", "week", "home_team", "away_team").to_dicts()
    table: Dict[Tuple[str, int, int], bool] = {}
    for r in rows:
        table[(r["home_team"], r["season"], r["week"])] = True
        table[(r["away_team"], r["season"], r["week"])] = True
    return table


def _index_scalar_series(rows: List[dict], key_field: str, value_field: str) -> Dict[str, List[Tuple[int, int, float]]]:
    index: Dict[str, List[Tuple[int, int, float]]] = {}
    for r in rows:
        index.setdefault(r[key_field], []).append((r["season"], r["week"], r[value_field] or 0.0))
    for key in index:
        index[key].sort()
    return index


def _trailing_scalar(
    index: Dict[str, List[Tuple[int, int, float]]],
    key: str,
    season: int,
    week: int,
    window: int = model.BASELINE_WINDOW,
) -> Optional[float]:
    """Same trailing/prior-season-fallback rule as model.baseline_stat_line, for a scalar series."""
    entries = index.get(key, [])
    prior = [e for e in entries if (e[0], e[1]) < (season, week)]
    current = [e for e in prior if e[0] == season]
    recent = current[-window:] if current else [e for e in prior if e[0] == season - 1]
    if not recent:
        return None
    return sum(e[2] for e in recent) / len(recent)


def _scalar_at(index: Dict[str, List[Tuple[int, int, float]]], key: str, season: int, week: int) -> Optional[float]:
    for s, w, v in index.get(key, []):
        if s == season and w == week:
            return v
    return None


# ---------------------------------------------------------------------------
# Roster simulation
# ---------------------------------------------------------------------------

def _season_points_pools(
    feature_table: pl.DataFrame,
    kicker_table: pl.DataFrame,
    def_table: Dict[Tuple[str, int, int], float],
    season: int,
) -> Dict[str, List[Tuple[str, float]]]:
    """position -> [(player_id_or_team, total_actual_ppr_points_that_season), ...], sorted desc.

    Used only to weight synthetic roster construction toward plausible
    (highly-productive) players. Deliberately uses full-season totals —
    that's fine here since it never touches any projection model, only how
    believable the *simulated rosters* look.
    """
    pools: Dict[str, Dict[str, float]] = {"QB": {}, "RB": {}, "WR": {}, "TE": {}, "K": {}, "DEF": {}}

    for r in feature_table.filter(pl.col("season") == season).to_dicts():
        pools[r["position"]][r["player_id"]] = pools[r["position"]].get(r["player_id"], 0.0) + score_stat_line(r, PPR)

    for r in kicker_table.filter(pl.col("season") == season).to_dicts():
        pools["K"][r["player_id"]] = pools["K"].get(r["player_id"], 0.0) + (r["fantasy_points"] or 0.0)

    def_totals: Dict[str, float] = {}
    for (team, s, _w), pts in def_table.items():
        if s == season:
            def_totals[team] = def_totals.get(team, 0.0) + pts
    pools["DEF"] = def_totals

    return {pos: sorted(d.items(), key=lambda kv: kv[1], reverse=True) for pos, d in pools.items()}


def _weighted_sample_without_replacement(pool: List[Tuple[str, float]], k: int, rng: random.Random) -> List[str]:
    """Sample k ids without replacement, weighted toward higher season-long finish.

    Rank-based (0.9**rank) rather than raw-points-based, so a handful of
    elite outliers don't make every simulated roster identical.
    """
    ids = [p for p, _ in pool]
    weights = [0.9 ** rank for rank in range(len(ids))]
    chosen: List[str] = []
    for _ in range(min(k, len(ids))):
        idx = rng.choices(range(len(ids)), weights=weights, k=1)[0]
        chosen.append(ids.pop(idx))
        weights.pop(idx)
    return chosen


def build_rosters(
    position_pools: Dict[str, List[Tuple[str, float]]],
    n: int = N_ROSTERS,
    seed: int = RANDOM_SEED,
) -> List[Dict[str, List[str]]]:
    rng = random.Random(seed)
    return [
        {
            pos: _weighted_sample_without_replacement(position_pools[pos], count, rng)
            for pos, count in ROSTER_COUNTS.items()
        }
        for _ in range(n)
    ]


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _target_weeks(schedules: pl.DataFrame, season: int) -> List[int]:
    return sorted(schedules.filter(pl.col("season") == season).select("week").unique().to_series().to_list())


def _channel_points(stat_line: Dict[str, float], channel: str) -> float:
    """PPR points from only the components in one defense channel."""
    components = defense.CHANNELS[channel][1]
    return score_stat_line({c: stat_line.get(c, 0.0) for c in components}, PPR)


def simulate(
    train_seasons: Sequence[int] = TRAIN_SEASONS,
    target_season: int = TARGET_SEASON,
    n_rosters: int = N_ROSTERS,
    seed: int = RANDOM_SEED,
) -> Dict:
    """Run the full backtest. Returns the aggregates `write_report` formats.

    Also writes the prediction log as a side effect (see write_predictions).
    """
    logger.info("Loading nflverse data for seasons=%s ...", train_seasons)
    feature_table = model.build_feature_table(train_seasons)
    schedules = model.load_schedules(train_seasons)
    kicker_table = build_kicker_table(train_seasons)
    def_table = build_def_table(schedules)
    has_game = team_has_game(schedules)
    logger.info("Building delta context (incl. rolling defense factors) ...")
    context = model.DeltaContext.build(feature_table, schedules)

    player_index = model.index_by_player(feature_table)
    kicker_index = _index_scalar_series(kicker_table.to_dicts(), "player_id", "fantasy_points")
    kicker_team = {r["player_id"]: r["team"] for r in kicker_table.sort(["season", "week"]).to_dicts()}
    def_index = _index_scalar_series(
        [{"team": t, "season": s, "week": w, "pts": pts} for (t, s, w), pts in def_table.items()],
        "team", "pts",
    )

    pools = _season_points_pools(feature_table, kicker_table, def_table, target_season)
    rosters = build_rosters(pools, n_rosters, seed)
    weeks = _target_weeks(schedules, target_season)

    log_rows: List[dict] = []
    roster_week_totals: List[dict] = []
    slot_totals: Dict[str, Dict[str, float]] = {}
    # (strategy, position) -> [(expected, actual), ...]
    mae_records: Dict[Tuple[str, str], List[Tuple[float, float]]] = {}
    delta_error_records: List[Tuple[Dict[str, float], float]] = []
    # channel -> [(log factor, actual_channel_pts - baseline_channel_pts), ...]
    defense_diag: Dict[str, List[Tuple[float, float]]] = {"pass": [], "rush": []}

    generated_at = _now_iso()
    slots = starting_slots(ROSTER_POSITIONS)  # e.g. ["QB","RB","RB","WR","WR","WR","TE","FLEX","K","DEF"]

    for roster_i, roster in enumerate(rosters):
        if roster_i and roster_i % 100 == 0:
            logger.info("  roster %d/%d", roster_i, n_rosters)
        for week in weeks:
            skill_players = []
            for pos in ("QB", "RB", "WR", "TE"):
                for pid in roster[pos]:
                    rows = player_index.get(pid, [])
                    ctx = model.target_context(rows, target_season, week)
                    if ctx:
                        team, opponent, implied = ctx["team"], ctx["opponent_team"], ctx["implied_team_total"]
                    else:
                        team, opponent, implied = model.current_team(rows, target_season, week), None, None
                    on_bye = team is not None and not has_game.get((team, target_season, week), False)

                    proj_v1 = proj_v2 = None
                    if team is not None:
                        proj_v1 = model.project_player_week(rows, target_season, week, pos, team, opponent, implied, context)
                        proj_v2 = model.project_player_week_v2(rows, target_season, week, pos, team, opponent, implied, context)
                    baseline = model.baseline_stat_line(rows, target_season, week)
                    actual = model.actual_stat_line(rows, target_season, week)

                    pts = {
                        "v1": score_stat_line(proj_v1.expected, PPR) if proj_v1 else None,
                        "v2": score_stat_line(proj_v2.expected, PPR) if proj_v2 else None,
                        "naive": score_stat_line(baseline, PPR) if baseline else None,
                        "hindsight": score_stat_line(actual, PPR) if actual else 0.0,
                    }
                    skill_players.append({
                        "player_id": pid, "position": pos, "team": team, "opponent": opponent,
                        "on_bye": on_bye, "proj_v1": proj_v1, "proj_v2": proj_v2,
                        "baseline": baseline, "actual": actual, "pts": pts,
                    })

                    if actual:
                        for strat in MODEL_STRATEGIES:
                            if pts[strat] is not None:
                                mae_records.setdefault((strat, pos), []).append((pts[strat], pts["hindsight"]))
                        if proj_v1:
                            delta_error_records.append((proj_v1.deltas, pts["hindsight"] - pts["v1"]))
                        if proj_v2 and opponent is not None:
                            for channel, factor in (("pass", proj_v2.pass_factor), ("rush", proj_v2.rush_factor)):
                                residual = _channel_points(actual, channel) - _channel_points(baseline, channel)
                                defense_diag[channel].append((math.log(factor), residual))

            kicker_players = []
            for pid in roster["K"]:
                team = kicker_team.get(pid)
                base = _trailing_scalar(kicker_index, pid, target_season, week)
                on_bye = team is not None and not has_game.get((team, target_season, week), False)
                actual_pts = _scalar_at(kicker_index, pid, target_season, week) or 0.0
                kicker_players.append({
                    "player_id": pid, "position": "K", "on_bye": on_bye,
                    "pts": {"v1": base, "v2": base, "naive": base, "hindsight": actual_pts},
                })
                if base is not None:
                    for strat in MODEL_STRATEGIES:
                        mae_records.setdefault((strat, "K"), []).append((base, actual_pts))

            def_players = []
            for team in roster["DEF"]:
                base = _trailing_scalar(def_index, team, target_season, week)
                on_bye = not has_game.get((team, target_season, week), False)
                actual_pts = _scalar_at(def_index, team, target_season, week) or 0.0
                def_players.append({
                    "player_id": team, "position": "DEF", "on_bye": on_bye,
                    "pts": {"v1": base, "v2": base, "naive": base, "hindsight": actual_pts},
                })
                if base is not None:
                    for strat in MODEL_STRATEGIES:
                        mae_records.setdefault((strat, "DEF"), []).append((base, actual_pts))

            all_players = skill_players + kicker_players + def_players

            def make_pool(strategy: str) -> List[LineupPlayer]:
                return [
                    LineupPlayer(p["player_id"], p["position"], p["pts"][strategy], on_bye=p["on_bye"])
                    for p in all_players
                    if p["pts"][strategy] is not None
                ]

            lineups = {
                strat: assign_lineup(apply_exclusions(make_pool(strat)), ROSTER_POSITIONS)
                for strat in STRATEGIES
            }
            actual_by_key = {(p["player_id"], p["position"]): p["pts"]["hindsight"] for p in all_players}

            def slotted_actual(lineup) -> float:
                return sum(actual_by_key.get((p.player_id, p.position), 0.0) for p in lineup if p is not None)

            roster_week_totals.append({
                "roster": roster_i, "week": week,
                **{strat: slotted_actual(lineups[strat]) for strat in STRATEGIES},
            })

            for idx, slot_label in enumerate(slots):
                bucket = slot_totals.setdefault(slot_label, {strat: 0.0 for strat in STRATEGIES})
                for strat in STRATEGIES:
                    p = lineups[strat][idx]
                    bucket[strat] += actual_by_key.get((p.player_id, p.position), 0.0) if p else 0.0

            slot_of = {
                strat: {(p.player_id, p.position): slots[idx] for idx, p in enumerate(lineups[strat]) if p is not None}
                for strat in ("v1", "v2")
            }

            for p in skill_players:
                key = (p["player_id"], p["position"])
                actual = p["actual"]
                common = {
                    "season": target_season,
                    "week": week,
                    "player_id": p["player_id"],
                    "position": p["position"],
                    "team": p["team"],
                    "opponent": p["opponent"],
                    **{f"actual_{c}": (actual[c] if actual else None) for c in STAT_COMPONENTS},
                    "actual_points_ppr": p["pts"]["hindsight"],
                    "injury_status": None,  # no pregame injury feed offline — see module docstring
                    "on_bye": p["on_bye"],
                    "generated_at": generated_at,
                    "reconciled_at": generated_at,
                }
                v1 = p["proj_v1"]
                log_rows.append({
                    **common,
                    "model_version": model.MODEL_VERSION,
                    "model_weights": json.dumps(model.WEIGHTS),
                    "adjustment": v1.adjustment if v1 else None,
                    **{k: (v1.deltas[k] if v1 else None) for k in model.WEIGHTS},
                    "defense_pass_factor": None,
                    "defense_rush_factor": None,
                    **{f"projected_{c}": (v1.expected[c] if v1 else None) for c in STAT_COMPONENTS},
                    "expected_points_ppr": p["pts"]["v1"],
                    "was_recommended_start": key in slot_of["v1"],
                    "slot_assigned": slot_of["v1"].get(key),
                })
                v2 = p["proj_v2"]
                log_rows.append({
                    **common,
                    "model_version": model.MODEL_VERSION_V2,
                    "model_weights": json.dumps(model.V2_CONFIG),
                    "adjustment": (v2.environment_multiplier - 1.0) if v2 else None,
                    "delta_opportunity": None,
                    "delta_environment": v2.delta_environment if v2 else None,
                    "delta_efficiency": None,
                    "delta_matchup": None,
                    "defense_pass_factor": v2.pass_factor if v2 else None,
                    "defense_rush_factor": v2.rush_factor if v2 else None,
                    **{f"projected_{c}": (v2.expected[c] if v2 else None) for c in STAT_COMPONENTS},
                    "expected_points_ppr": p["pts"]["v2"],
                    "was_recommended_start": key in slot_of["v2"],
                    "slot_assigned": slot_of["v2"].get(key),
                })

    write_predictions(log_rows)

    return {
        "roster_week_totals": roster_week_totals,
        "slot_totals": slot_totals,
        "mae_records": mae_records,
        "delta_error_records": delta_error_records,
        "defense_diag": defense_diag,
        "n_rosters": n_rosters,
        "n_roster_weeks": len(roster_week_totals),
        "target_season": target_season,
    }


def write_predictions(rows: List[dict]) -> List[Path]:
    """Append prediction-log rows to partitioned parquet.

    research/data/predictions/season={season}/week={week}/part-<uuid>.parquet
    Never overwrites: every call writes new file(s) under a fresh random
    name, so regenerating a week's predictions appends rather than replacing
    history — exactly what "regeneration appends with a new generated_at"
    requires.
    """
    if not rows:
        return []
    df = pl.DataFrame(rows)
    written = []
    for season, week in df.select("season", "week").unique().rows():
        part_dir = PREDICTIONS_DIR / f"season={season}" / f"week={week}"
        part_dir.mkdir(parents=True, exist_ok=True)
        path = part_dir / f"part-{uuid.uuid4().hex}.parquet"
        df.filter((pl.col("season") == season) & (pl.col("week") == week)).write_parquet(path)
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _mae(pairs: List[Tuple[float, float]]) -> float:
    return sum(abs(a - b) for a, b in pairs) / len(pairs) if pairs else float("nan")


def _bias(pairs: List[Tuple[float, float]]) -> float:
    """mean(expected - actual): positive = over-projecting."""
    return sum(a - b for a, b in pairs) / len(pairs) if pairs else float("nan")


def _pearson(xs: List[float], ys: List[float]) -> float:
    if len(xs) >= 2 and len(set(xs)) > 1 and len(set(ys)) > 1:
        r, _p = stats.pearsonr(xs, ys)
        return float(r)
    return float("nan")


def _delta_error_correlations(records: List[Tuple[Dict[str, float], float]]) -> Dict[str, float]:
    ys = [err for _d, err in records]
    return {key: _pearson([d[key] for d, _err in records], ys) for key in model.WEIGHTS}


def _paired_test(totals: List[dict], a: str, b: str) -> Tuple[float, float, float]:
    """mean(a - b), paired t-statistic, p-value across roster-weeks."""
    a_vals = [t[a] for t in totals]
    b_vals = [t[b] for t in totals]
    diffs = [x - y for x, y in zip(a_vals, b_vals)]
    mean_diff = sum(diffs) / len(diffs) if diffs else float("nan")
    if len(diffs) >= 2 and len(set(diffs)) > 1:
        t_stat, p_value = stats.ttest_rel(a_vals, b_vals)
    else:
        t_stat, p_value = float("nan"), float("nan")
    return mean_diff, float(t_stat), float(p_value)


def _quintile_table(pairs: List[Tuple[float, float]]) -> List[Tuple[str, float, float, int]]:
    """Bin by x into quintiles; return (label, mean x as factor, mean y, n) per bin."""
    if len(pairs) < 5:
        return []
    ordered = sorted(pairs)
    n = len(ordered)
    out = []
    for q in range(5):
        chunk = ordered[q * n // 5:(q + 1) * n // 5]
        if not chunk:
            continue
        mean_factor = math.exp(sum(x for x, _ in chunk) / len(chunk))
        mean_resid = sum(y for _, y in chunk) / len(chunk)
        out.append((f"Q{q + 1}", mean_factor, mean_resid, len(chunk)))
    return out


def write_report(results: Dict, path: Path = RESULTS_DIR / "backtest.md") -> Path:
    totals = results["roster_week_totals"]
    slot_totals = results["slot_totals"]
    mae_records = results["mae_records"]
    delta_error_records = results["delta_error_records"]
    defense_diag = results["defense_diag"]

    hindsight_sum = sum(t["hindsight"] for t in totals) or 1.0
    captured = {strat: 100.0 * sum(t[strat] for t in totals) / hindsight_sum for strat in STRATEGIES}
    per_week = {strat: sum(t[strat] for t in totals) / max(len(totals), 1) for strat in STRATEGIES}

    tests = {
        ("v1", "naive"): _paired_test(totals, "v1", "naive"),
        ("v2", "naive"): _paired_test(totals, "v2", "naive"),
        ("v2", "v1"): _paired_test(totals, "v2", "v1"),
    }

    def verdict(a: str, b: str) -> str:
        mean_diff, t_stat, p_value = tests[(a, b)]
        if mean_diff > 0 and p_value < 0.05:
            return f"**{a} beats {b}**: {mean_diff:+.2f} pts/roster-week (t={t_stat:.2f}, p={p_value:.4f})"
        if mean_diff < 0 and p_value < 0.05:
            return f"**{a} LOSES to {b}**: {mean_diff:+.2f} pts/roster-week (t={t_stat:.2f}, p={p_value:.4f})"
        return f"**{a} vs {b}: no significant difference** ({mean_diff:+.2f} pts/roster-week, t={t_stat:.2f}, p={p_value:.4f})"

    L: List[str] = []
    L.append("# Backtest Results — Start/Sit Model, v1 vs v2")
    L.append("")
    L.append(f"Season: {results['target_season']}  ")
    L.append(f"Simulated rosters: {results['n_rosters']}  ")
    L.append(f"Roster-weeks evaluated: {results['n_roster_weeks']}  ")
    L.append(f"Hindsight-optimal average: {per_week['hindsight']:.1f} pts/roster-week")
    L.append("")
    L.append("| Strategy | What it is |")
    L.append("|---|---|")
    for strat in STRATEGIES:
        L.append(f"| {strat} | {STRATEGY_LABELS[strat]} |")
    L.append("")

    L.append("## Bottom line")
    L.append("")
    L.append(f"- {verdict('v1', 'naive')}")
    L.append(f"- {verdict('v2', 'naive')}")
    L.append(f"- {verdict('v2', 'v1')}")
    L.append("")
    gap = per_week["hindsight"] - per_week["naive"]
    L.append(
        f"Naive leaves {gap:.1f} pts/roster-week on the table vs. hindsight. "
        f"v1 recovers {per_week['v1'] - per_week['naive']:+.2f} of that, v2 recovers "
        f"{per_week['v2'] - per_week['naive']:+.2f}. Most of the remainder is TD variance "
        f"no pregame projection recovers."
    )
    L.append("")

    L.append("## % of hindsight-optimal points captured")
    L.append("")
    L.append("| Strategy | pts/roster-week | % of optimal |")
    L.append("|---|---|---|")
    for strat in ("v1", "v2", "naive", "hindsight"):
        L.append(f"| {strat} | {per_week[strat]:.2f} | {captured[strat]:.2f}% |")
    L.append("")

    L.append("### By starting slot")
    L.append("")
    L.append("| Slot | Hindsight pts | v1 % | v2 % | naive % | v2 − v1 (pts) |")
    L.append("|---|---|---|---|---|---|")
    for slot_label, bucket in slot_totals.items():
        h = bucket["hindsight"] or 1.0
        L.append(
            f"| {slot_label} | {bucket['hindsight']:.0f} | "
            f"{100.0 * bucket['v1'] / h:.1f}% | {100.0 * bucket['v2'] / h:.1f}% | "
            f"{100.0 * bucket['naive'] / h:.1f}% | {bucket['v2'] - bucket['v1']:+.0f} |"
        )
    L.append("")
    L.append("K and DEF are identical across v1/v2/naive by construction (see module docstring).")
    L.append("")

    L.append("## Paired tests across roster-weeks")
    L.append("")
    L.append("| Comparison | mean diff (pts) | t | p | n |")
    L.append("|---|---|---|---|---|")
    for (a, b), (mean_diff, t_stat, p_value) in tests.items():
        L.append(f"| {a} − {b} | {mean_diff:+.3f} | {t_stat:.3f} | {p_value:.4f} | {len(totals)} |")
    L.append("")

    L.append("## MAE and bias (expected vs. actual PPR points), by position")
    L.append("")
    L.append("bias = mean(expected − actual); positive = over-projecting.")
    L.append("")
    L.append("| Position | v1 MAE | v2 MAE | naive MAE | v1 bias | v2 bias | naive bias | n |")
    L.append("|---|---|---|---|---|---|---|---|")
    for position in ("QB", "RB", "WR", "TE", "K", "DEF"):
        rec = {strat: mae_records.get((strat, position), []) for strat in MODEL_STRATEGIES}
        L.append(
            f"| {position} | {_mae(rec['v1']):.2f} | {_mae(rec['v2']):.2f} | {_mae(rec['naive']):.2f} | "
            f"{_bias(rec['v1']):+.2f} | {_bias(rec['v2']):+.2f} | {_bias(rec['naive']):+.2f} | {len(rec['naive'])} |"
        )
    L.append("")
    L.append(
        "All three share the same unshrunk trailing baseline, so the ~2 pt over-projection "
        "is common to all of them and does not affect the relative comparison. "
        "K/DEF rows reflect the trailing-average-only estimate, not either model."
    )
    L.append("")

    L.append("## v2 diagnostic: does the defense factor predict the residual?")
    L.append("")
    L.append(
        "For each modeled player-week, residual = actual − baseline PPR points from that "
        "channel's components only. If the opponent-adjusted factor carries real signal, "
        "residual should rise with the factor (defenses that allow more → players beat "
        "their baseline more)."
    )
    L.append("")
    L.append("| Channel | Pearson r (log factor, residual) | n |")
    L.append("|---|---|---|")
    for channel, pairs in defense_diag.items():
        r = _pearson([x for x, _ in pairs], [y for _, y in pairs])
        L.append(f"| {channel} | {r:.3f} | {len(pairs)} |")
    L.append("")
    for channel, pairs in defense_diag.items():
        L.append(f"**{channel} channel, by factor quintile**")
        L.append("")
        L.append("| Quintile | mean factor | mean residual (pts) | n |")
        L.append("|---|---|---|---|")
        for label, mean_factor, mean_resid, n in _quintile_table(pairs):
            L.append(f"| {label} | {mean_factor:.3f} | {mean_resid:+.2f} | {n} |")
        L.append("")

    L.append("## v1 error attribution: correlation of each delta with prediction error")
    L.append("")
    L.append("error = actual_points_ppr − expected_points_ppr (QB/RB/WR/TE only)")
    L.append("")
    L.append("| Delta term | Pearson r vs. error | n |")
    L.append("|---|---|---|")
    for key, r in _delta_error_correlations(delta_error_records).items():
        L.append(f"| {key} | {r:.3f} | {len(delta_error_records)} |")
    L.append("")

    L.append("## Configuration")
    L.append("")
    L.append("v1 weights (untouched):")
    L.append("")
    L.append(f"```json\n{json.dumps(model.WEIGHTS, indent=2)}\n```")
    L.append("")
    L.append("v2 config:")
    L.append("")
    L.append(f"```json\n{json.dumps(model.V2_CONFIG, indent=2)}\n```")
    L.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")
    return path
