"""Snap-aware baseline experiment (offline, 2025 backtest).

Question: does using snap share to make the baseline role-aware improve
start/sit lineups over the production v2 model?

Production v2 builds a player's baseline as the plain average of their last 3
played games. That has two blind spots snaps can address:

  1. ROLE CHANGES. A player who was part-time and is now full-time (a rookie
     ramping up, a returning starter) has old low-snap games dragging the
     average down; the reverse for someone losing snaps.
  2. GAME SCRIPT. Big favorites tend to pull starters late, so a player on a
     heavy favorite plays fewer snaps than his recent average suggests.

The variants here split "how much does this player produce per snap" (a rate,
measured over a LONGER window so it is stable) from "how many snaps will he
play" (volume, from a SHORTER recent window so it tracks the current role):

    expected_line = per_snap_rate(rate window) x expected_snap_share

If both used the same window the snap terms would cancel and the result would
equal the plain average, so the two windows must differ for this to mean
anything.

Strategies compared on the SAME rosters/weeks/lineup solver as
research/backtest.py (same seed, so identical simulated rosters):

  naive              trailing 3-wk average, no adjustment (unchanged)
  v2                 production model: defense factors x Vegas (unchanged)
  snap_role          v2, but with the role-aware baseline (rate 6g, snaps 3g)
  snap_role_blowout  snap_role + expected snaps shifted by pregame spread
  snap_r4s2, snap_r8s3   robustness: other window choices (no blowout term)
  hindsight          assignment on actual points (the ceiling)

Variants only change the BASELINE. Defense factors and the Vegas environment
multiplier are applied identically, so differences isolate the snap idea.

Design choices were fixed BEFORE looking at 2025 results (windows 6/3, clamp,
the 40%-snap filter for the blowout fit). The blowout coefficients are fit on
2024 only and evaluated on 2025, so there is no in-sample fit on the test
season.

Usage:
    python -m research.snap_experiment

Writes research/results/snap_experiment.md. Does NOT touch backtest.md or the
prediction log.
"""

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import polars as pl
from scipy import stats

from research import backtest as bt
from research import defense, model
from research.assignment import LineupPlayer, apply_exclusions, assign_lineup, starting_slots
from research.scoring import STAT_COMPONENTS, score_stat_line

logger = logging.getLogger(__name__)

RESULTS_PATH = bt.RESULTS_DIR / "snap_experiment.md"
LOCAL_RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

POSITIONS = ("QB", "RB", "WR", "TE")

# Role-aware baseline knobs (fixed a priori).
SNAP_FLOOR = 0.05            # expected snap share never below 5%
SCALE_CLAMP = (0.5, 1.5)     # cap on expected_snap / rate-window mean snap
BLOWOUT_MIN_MEAN_SNAP = 0.40 # fit the spread effect on regulars, not fringe players
BLOWOUT_MIN_PRIOR = 3        # prior games needed for a fit observation
BLOWOUT_MIN_OBS = 30         # fewer observations -> coefficient defaults to 0

VARIANTS: Dict[str, Dict] = {
    "snap_role": {"rate": 6, "snap": 3, "blowout": False},
    "snap_role_blowout": {"rate": 6, "snap": 3, "blowout": True},
    "snap_r4s2": {"rate": 4, "snap": 2, "blowout": False},
    "snap_r8s3": {"rate": 8, "snap": 3, "blowout": False},
}
LABELS = {
    "naive": "naive (trailing 3-wk avg)",
    "v2": "v2 (production)",
    "snap_role": "snap_role (rate 6g x snaps 3g)",
    "snap_role_blowout": "snap_role + blowout adj",
    "snap_r4s2": "snap_r4s2 (rate 4g x snaps 2g)",
    "snap_r8s3": "snap_r8s3 (rate 8g x snaps 3g)",
    "hindsight": "hindsight-optimal",
}
MODEL_STRATEGIES = ("naive", "v2") + tuple(VARIANTS)
STRATEGIES = MODEL_STRATEGIES + ("hindsight",)


# ---------------------------------------------------------------------------
# Pregame spread -> "favorite margin" per (team, season, week)
# ---------------------------------------------------------------------------

def build_margin_table(schedules: pl.DataFrame) -> Dict[Tuple[str, int, int], float]:
    """(team, season, week) -> how many points that team is favored by (negative = underdog).

    nflverse spread_line is the HOME team's favorite margin (positive = home
    favored); the away team gets the negation.
    """
    table: Dict[Tuple[str, int, int], float] = {}
    for r in schedules.select("season", "week", "home_team", "away_team", "spread_line").to_dicts():
        spread = r["spread_line"]
        if spread is None:
            continue
        table[(r["home_team"], r["season"], r["week"])] = float(spread)
        table[(r["away_team"], r["season"], r["week"])] = -float(spread)
    return table


def fit_blowout_betas(
    player_index: Dict[str, List[dict]],
    margins: Dict[Tuple[str, int, int], float],
    fit_season: int,
) -> Dict[str, float]:
    """Per-position slope: change in snap share per point of extra favorite margin.

    For each player-game with >= 3 prior valid games that season:
        y = snap_share_now - mean(snap_share of prior 3 games)
        x = favorite_margin_now - mean(favorite_margin of those 3 games)
    and beta = OLS slope of y on x. Centering both on the prior games means
    beta measures "how much do snaps move when the game script is more lopsided
    than the games the recent average came from". Only players averaging at
    least BLOWOUT_MIN_MEAN_SNAP are used so fringe players' sporadic snaps
    don't dominate. Fit on ``fit_season`` only (prior to the test season).
    """
    xs: Dict[str, List[float]] = {p: [] for p in POSITIONS}
    ys: Dict[str, List[float]] = {p: [] for p in POSITIONS}

    for rows in player_index.values():
        pos = rows[0]["position"]
        if pos not in xs:
            continue
        season_rows = [r for r in rows if r["season"] == fit_season and r["offense_pct"] > 0.0]
        for i in range(BLOWOUT_MIN_PRIOR, len(season_rows)):
            prev = season_rows[i - BLOWOUT_MIN_PRIOR:i]
            cur = season_rows[i]
            prev_snap = sum(r["offense_pct"] for r in prev) / len(prev)
            if prev_snap < BLOWOUT_MIN_MEAN_SNAP:
                continue
            m_cur = margins.get((cur["team"], cur["season"], cur["week"]))
            m_prev = [margins.get((r["team"], r["season"], r["week"])) for r in prev]
            if m_cur is None or any(m is None for m in m_prev):
                continue
            xs[pos].append(m_cur - sum(m_prev) / len(m_prev))
            ys[pos].append(cur["offense_pct"] - prev_snap)

    betas = {}
    for pos in POSITIONS:
        if len(xs[pos]) >= BLOWOUT_MIN_OBS and np.var(xs[pos]) > 0:
            betas[pos] = float(np.polyfit(xs[pos], ys[pos], 1)[0])
        else:
            betas[pos] = 0.0
        logger.info("blowout beta %s = %+.5f snap-share per spread point (n=%d)", pos, betas[pos], len(xs[pos]))
    betas["_n"] = {pos: len(xs[pos]) for pos in POSITIONS}  # type: ignore[assignment]
    return betas


# ---------------------------------------------------------------------------
# Role-aware baseline
# ---------------------------------------------------------------------------

def snap_baseline(
    rows: List[dict],
    season: int,
    week: int,
    position: str,
    td_rates,
    rate_window: int,
    snap_window: int,
    margins: Optional[Dict[Tuple[str, int, int], float]] = None,
    beta: float = 0.0,
    target_margin: Optional[float] = None,
) -> Optional[Dict[str, float]]:
    """Role-aware baseline: per-snap rate (long window) x expected snap share (short window).

    Uses only rows strictly before (season, week). Falls back to the standard
    baseline whenever there is no in-season game with a valid snap share (so it
    can never exclude a player the production baseline would keep).

        line_c = mean_rate_window(c) * clamp(expected_snap / mean_rate_window(snap))

    which equals (per-snap rate of component c) x expected_snap. TD components
    are then shrunk toward the position mean exactly like the standard baseline.
    """
    def fallback():
        return model.baseline_stat_line(rows, season, week, position=position, position_td_rates=td_rates)

    prior = model._weeks_before(rows, season, week)
    # offense_pct == 0.0 means "no snap row matched" (build_feature_table fills nulls
    # with 0), not "played zero snaps" -- anyone with a stat line played.
    pool = [r for r in prior if r["season"] == season and r["offense_pct"] > 0.0]
    if not pool:
        return fallback()

    rate_rows = pool[-rate_window:]
    snap_rows = pool[-snap_window:]
    mean_snap_rate = sum(r["offense_pct"] for r in rate_rows) / len(rate_rows)
    mean_snap_recent = sum(r["offense_pct"] for r in snap_rows) / len(snap_rows)

    adj = 0.0
    if margins is not None and beta and target_margin is not None:
        past = [margins.get((r["team"], r["season"], r["week"])) for r in snap_rows]
        past = [m for m in past if m is not None]
        if past:
            adj = beta * (target_margin - sum(past) / len(past))

    expected_snap = min(1.0, max(SNAP_FLOOR, mean_snap_recent + adj))
    scale = min(SCALE_CLAMP[1], max(SCALE_CLAMP[0], expected_snap / mean_snap_rate))

    baseline = {c: sum(r[c] for r in rate_rows) / len(rate_rows) * scale for c in STAT_COMPONENTS}

    if td_rates is not None:
        position_mean = td_rates.get((position, season, week))
        if position_mean is not None:
            n = len(rate_rows)
            w = n / (n + model.TD_SHRINK_K)
            for comp in model.TD_COMPONENTS:
                prior_mean = position_mean.get(comp)
                if prior_mean is not None:
                    baseline[comp] = w * baseline[comp] + (1.0 - w) * prior_mean
    return baseline


def expected_with_baseline(
    baseline: Dict[str, float],
    team: str,
    opponent: Optional[str],
    implied: Optional[float],
    season: int,
    week: int,
    context: "model.DeltaContext",
) -> Dict[str, float]:
    """v2's defense-factor x Vegas stage, applied to an arbitrary baseline."""
    if opponent is None:
        pass_factor = rush_factor = 1.0
    else:
        pass_factor = defense.factor_for(context.defense_factors, opponent, season, week, "pass")
        rush_factor = defense.factor_for(context.defense_factors, opponent, season, week, "rush")
    delta_env = model.environment_delta(team, season, week, implied, context)
    env_mult = 1.0 + model.V2_ENVIRONMENT_WEIGHT * delta_env
    return model.expected_line_v2(baseline, pass_factor, rush_factor, env_mult)


# ---------------------------------------------------------------------------
# Simulation (mirrors research/backtest.simulate, minus logging side effects)
# ---------------------------------------------------------------------------

def simulate_experiment(
    train_seasons: Sequence[int] = bt.TRAIN_SEASONS,
    target_season: int = bt.TARGET_SEASON,
    n_rosters: int = bt.N_ROSTERS,
    seed: int = bt.RANDOM_SEED,
) -> Dict:
    logger.info("Loading data for seasons=%s ...", train_seasons)
    feature_table = model.build_feature_table(train_seasons)
    schedules = model.load_schedules(train_seasons)
    kicker_table = bt.build_kicker_table(train_seasons)
    def_table = bt.build_def_table(schedules)
    has_game = bt.team_has_game(schedules)
    logger.info("Building delta context ...")
    context = model.DeltaContext.build(feature_table, schedules)

    player_index = model.index_by_player(feature_table)
    margins = build_margin_table(schedules)
    betas = fit_blowout_betas(player_index, margins, fit_season=target_season - 1)

    kicker_index = bt._index_scalar_series(kicker_table.to_dicts(), "player_id", "fantasy_points")
    kicker_team = {r["player_id"]: r["team"] for r in kicker_table.sort(["season", "week"]).to_dicts()}
    def_index = bt._index_scalar_series(
        [{"team": t, "season": s, "week": w, "pts": pts} for (t, s, w), pts in def_table.items()],
        "team", "pts",
    )

    pools = bt._season_points_pools(feature_table, kicker_table, def_table, target_season)
    rosters = bt.build_rosters(pools, n_rosters, seed)
    weeks = bt._target_weeks(schedules, target_season)
    slots = starting_slots(bt.ROSTER_POSITIONS)
    ppr = bt.PPR

    # Rosters share players, so cache each (player, week) projection once.
    entry_cache: Dict[Tuple[str, str, int], dict] = {}
    check_state = {"n": 0, "max_err": 0.0}

    def player_entry(pid: str, pos: str, week: int) -> dict:
        key = (pid, pos, week)
        if key in entry_cache:
            return entry_cache[key]
        rows = player_index.get(pid, [])
        ctx = model.target_context(rows, target_season, week)
        if ctx:
            team, opponent, implied = ctx["team"], ctx["opponent_team"], ctx["implied_team_total"]
        else:
            team, opponent, implied = model.current_team(rows, target_season, week), None, None
        on_bye = team is not None and not has_game.get((team, target_season, week), False)

        td_rates = context.position_td_rate_trailing
        naive_bl = model.baseline_stat_line(
            rows, target_season, week, position=pos, position_td_rates=td_rates
        )
        actual = model.actual_stat_line(rows, target_season, week)
        pts: Dict[str, Optional[float]] = {
            "naive": score_stat_line(naive_bl, ppr) if naive_bl else None,
            "hindsight": score_stat_line(actual, ppr) if actual else 0.0,
        }

        proj_v2 = None
        if team is not None:
            proj_v2 = model.project_player_week_v2(
                rows, target_season, week, pos, team, opponent, implied, context
            )
        pts["v2"] = score_stat_line(proj_v2.expected, ppr) if proj_v2 else None

        # Sanity: our "v2 stage on a baseline" helper must reproduce v2 exactly.
        if proj_v2 is not None and naive_bl is not None and check_state["n"] < 500:
            ours = expected_with_baseline(naive_bl, team, opponent, implied, target_season, week, context)
            err = max(abs(ours[c] - proj_v2.expected[c]) for c in STAT_COMPONENTS)
            check_state["n"] += 1
            check_state["max_err"] = max(check_state["max_err"], err)

        target_margin = margins.get((team, target_season, week)) if team is not None else None
        for name, cfg in VARIANTS.items():
            pts[name] = None
            if team is None:
                continue
            bl = snap_baseline(
                rows, target_season, week, pos, td_rates,
                rate_window=cfg["rate"], snap_window=cfg["snap"],
                margins=margins if cfg["blowout"] else None,
                beta=betas[pos] if cfg["blowout"] else 0.0,
                target_margin=target_margin if cfg["blowout"] else None,
            )
            if bl is None:
                continue
            expected = expected_with_baseline(bl, team, opponent, implied, target_season, week, context)
            pts[name] = score_stat_line(expected, ppr)

        entry = {"player_id": pid, "position": pos, "on_bye": on_bye, "pts": pts, "has_actual": actual is not None}
        entry_cache[key] = entry
        return entry

    roster_week_totals: List[dict] = []
    mae_records: Dict[Tuple[str, str], List[Tuple[float, float]]] = {}

    for roster_i, roster in enumerate(rosters):
        if roster_i and roster_i % 100 == 0:
            logger.info("  roster %d/%d", roster_i, n_rosters)
        for week in weeks:
            players = []
            for pos in POSITIONS:
                for pid in roster[pos]:
                    e = player_entry(pid, pos, week)
                    players.append(e)
                    if e["has_actual"]:
                        for strat in MODEL_STRATEGIES:
                            if e["pts"][strat] is not None:
                                mae_records.setdefault((strat, pos), []).append((e["pts"][strat], e["pts"]["hindsight"]))

            for pid in roster["K"]:
                team = kicker_team.get(pid)
                base = bt._trailing_scalar(kicker_index, pid, target_season, week)
                on_bye = team is not None and not has_game.get((team, target_season, week), False)
                actual_pts = bt._scalar_at(kicker_index, pid, target_season, week) or 0.0
                players.append({
                    "player_id": pid, "position": "K", "on_bye": on_bye,
                    "pts": {**{s: base for s in MODEL_STRATEGIES}, "hindsight": actual_pts},
                })
            for team in roster["DEF"]:
                base = bt._trailing_scalar(def_index, team, target_season, week)
                on_bye = not has_game.get((team, target_season, week), False)
                actual_pts = bt._scalar_at(def_index, team, target_season, week) or 0.0
                players.append({
                    "player_id": team, "position": "DEF", "on_bye": on_bye,
                    "pts": {**{s: base for s in MODEL_STRATEGIES}, "hindsight": actual_pts},
                })

            actual_by_key = {(p["player_id"], p["position"]): p["pts"]["hindsight"] for p in players}

            def make_pool(strategy: str) -> List[LineupPlayer]:
                return [
                    LineupPlayer(p["player_id"], p["position"], p["pts"][strategy], on_bye=p["on_bye"])
                    for p in players if p["pts"][strategy] is not None
                ]

            totals = {"roster": roster_i, "week": week}
            for strat in STRATEGIES:
                lineup = assign_lineup(apply_exclusions(make_pool(strat)), bt.ROSTER_POSITIONS)
                totals[strat] = sum(
                    actual_by_key.get((p.player_id, p.position), 0.0) for p in lineup if p is not None
                )
            roster_week_totals.append(totals)

    logger.info(
        "Sanity check: max |helper - v2| stat-line error over %d player-weeks = %.2e",
        check_state["n"], check_state["max_err"],
    )
    return {
        "roster_week_totals": roster_week_totals,
        "mae_records": mae_records,
        "betas": betas,
        "n_rosters": n_rosters,
        "n_roster_weeks": len(roster_week_totals),
        "target_season": target_season,
        "check": check_state,
    }


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _paired(totals: List[dict], a: str, b: str) -> Dict[str, float]:
    """a - b: mean diff, roster-week t/p, and a week-clustered t/p.

    The roster-week test treats all 500 x 17 observations as independent, which
    overstates significance: rosters sample from the same players and a week's
    results are correlated across rosters. The week-clustered test averages
    within each week first (one number per week), which is the more honest unit.
    """
    diffs = np.array([t[a] - t[b] for t in totals])
    t_rw, p_rw = stats.ttest_1samp(diffs, 0.0)
    by_week: Dict[int, List[float]] = {}
    for t in totals:
        by_week.setdefault(t["week"], []).append(t[a] - t[b])
    week_means = np.array([np.mean(v) for v in by_week.values()])
    t_wk, p_wk = stats.ttest_1samp(week_means, 0.0)
    return {
        "mean": float(diffs.mean()),
        "t_rw": float(t_rw), "p_rw": float(p_rw),
        "t_wk": float(t_wk), "p_wk": float(p_wk),
        "weeks_better": int((week_means > 0).sum()), "n_weeks": int(len(week_means)),
    }


def _mae(pairs: List[Tuple[float, float]]) -> float:
    return sum(abs(e - a) for e, a in pairs) / len(pairs)


def _bias(pairs: List[Tuple[float, float]]) -> float:
    return sum(e - a for e, a in pairs) / len(pairs)


# ---------------------------------------------------------------------------
# Worked example on live 2026 data
# ---------------------------------------------------------------------------

def worked_example(
    betas: Dict[str, float],
    names: Sequence[str] = ("Parker Washington", "Germie Bernard"),
    season: int = 2026,
    week: int = 10,
) -> List[str]:
    """Project named players for a real upcoming week under each baseline.

    Loads last season from the research cache and the current season from the
    app's data/raw (via a temp dir, so nothing is cached into research/).
    Returns markdown lines; on any failure returns a short note instead.
    """
    try:
        src = model.RAW_DATA_DIR
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name in ("player_stats", "snap_counts", "schedules"):
                shutil.copy(src / f"{name}_{season - 1}.parquet", tmp_path)
                shutil.copy(LOCAL_RAW_DIR / f"{name}_{season}.parquet", tmp_path)
            original = model.RAW_DATA_DIR
            model.RAW_DATA_DIR = tmp_path
            try:
                ft = model.build_feature_table((season - 1, season))
                sched = model.load_schedules((season - 1, season))
            finally:
                model.RAW_DATA_DIR = original

        # Future 2026 games have no betting line yet and research.model's
        # team_environment_trailing can't sum a None implied total, so build
        # the context from games that have lines. (Opponent/margin lookups
        # below still use the full schedule.)
        sched_with_lines = sched.filter(
            pl.col("total_line").is_not_null() & pl.col("spread_line").is_not_null()
        )
        context = model.DeltaContext.build(ft, sched_with_lines)
        index = model.index_by_player(ft)
        margins = build_margin_table(sched)
        implied_tbl = model._implied_team_totals(sched).filter(
            (pl.col("season") == season) & (pl.col("week") == week)
        )
        implied_by_team = {r["team"]: r["implied_team_total"] for r in implied_tbl.to_dicts()}
        games = sched.filter((pl.col("season") == season) & (pl.col("week") == week)).to_dicts()
        opp_by_team = {}
        for g in games:
            opp_by_team[g["home_team"]] = g["away_team"]
            opp_by_team[g["away_team"]] = g["home_team"]
        td_rates = context.position_td_rate_trailing

        lines = [
            f"Live example: {season} week {week}, built from games strictly before week {week}.",
            "",
            "| Player | Team | Opp | Fav margin | naive | v2 | snap_role | snap_role + blowout |",
            "|---|---|---|---|---|---|---|---|",
        ]
        logs: List[str] = []
        for name in names:
            rows = next((r for r in index.values() if r and r[-1]["player_display_name"] == name), None)
            if rows is None:
                lines.append(f"| {name} | not found | | | | | | |")
                continue
            pos = rows[-1]["position"]
            team = model.current_team(rows, season, week)
            opp = opp_by_team.get(team)
            implied = implied_by_team.get(team)
            margin = margins.get((team, season, week))

            naive_bl = model.baseline_stat_line(rows, season, week, position=pos, position_td_rates=td_rates)
            v2_pts = naive_pts = None
            if naive_bl:
                naive_pts = score_stat_line(naive_bl, bt.PPR)
                v2_pts = score_stat_line(
                    expected_with_baseline(naive_bl, team, opp, implied, season, week, context), bt.PPR
                )
            res = {}
            for vname in ("snap_role", "snap_role_blowout"):
                cfg = VARIANTS[vname]
                bl = snap_baseline(
                    rows, season, week, pos, td_rates, cfg["rate"], cfg["snap"],
                    margins=margins if cfg["blowout"] else None,
                    beta=betas[pos] if cfg["blowout"] else 0.0,
                    target_margin=margin if cfg["blowout"] else None,
                )
                res[vname] = score_stat_line(
                    expected_with_baseline(bl, team, opp, implied, season, week, context), bt.PPR
                ) if bl else None

            def f(x):
                return f"{x:.1f}" if x is not None else "-"

            lines.append(
                f"| {name} | {team} | {opp} | {margin:+.1f} | {f(naive_pts)} | {f(v2_pts)} | "
                f"{f(res['snap_role'])} | {f(res['snap_role_blowout'])} |"
                if margin is not None else
                f"| {name} | {team} | {opp} | - | {f(naive_pts)} | {f(v2_pts)} | "
                f"{f(res['snap_role'])} | {f(res['snap_role_blowout'])} |"
            )
            played = [r for r in rows if r["season"] == season and r["week"] < week]
            log = ", ".join(
                f"wk{r['week']}: {r['offense_pct']*100:.0f}% snaps / "
                f"{score_stat_line({c: r[c] for c in STAT_COMPONENTS}, bt.PPR):.1f} pts"
                for r in played
            )
            logs.append(f"- {name} games used: {log}")
        lines += ["", *logs]
        return lines
    except Exception as e:  # pragma: no cover - illustrative section only
        logger.warning("Worked example skipped: %s", e)
        return [f"Worked example skipped: {e}"]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(results: Dict, example_lines: List[str], path: Path = RESULTS_PATH) -> Path:
    totals = results["roster_week_totals"]
    n_rw = results["n_roster_weeks"]
    means = {s: float(np.mean([t[s] for t in totals])) for s in STRATEGIES}
    hind = means["hindsight"]

    out: List[str] = []
    out.append("# Snap-aware baseline experiment")
    out.append("")
    out.append(
        f"Season {results['target_season']}, {results['n_rosters']} simulated rosters, "
        f"{n_rw} roster-weeks. Same rosters, weeks and lineup solver as `backtest.md` "
        f"(same seed). Variants change only the BASELINE; defense factors and the Vegas "
        f"environment multiplier are identical to production v2."
    )
    out.append("")
    out.append("## Points per roster-week")
    out.append("")
    out.append("| Strategy | pts/roster-week | % of hindsight | vs v2 | vs naive |")
    out.append("|---|---|---|---|---|")
    for s in STRATEGIES:
        vs_v2 = "" if s in ("v2", "hindsight") else f"{means[s] - means['v2']:+.2f}"
        vs_naive = "" if s in ("naive", "hindsight") else f"{means[s] - means['naive']:+.2f}"
        out.append(f"| {LABELS[s]} | {means[s]:.2f} | {means[s] / hind * 100:.2f}% | {vs_v2} | {vs_naive} |")
    out.append("")

    out.append("## Paired tests")
    out.append("")
    out.append(
        "`roster-week` treats every roster-week as independent (optimistic: rosters share players "
        "and a week's outcomes are correlated). `week-clustered` averages within each week first and "
        "tests the weekly means, the more conservative read. `weeks better` counts weeks where the "
        "first strategy beat the second."
    )
    out.append("")
    out.append("| Comparison | mean diff | t (roster-week) | p | t (week-clustered) | p | weeks better |")
    out.append("|---|---|---|---|---|---|---|")
    comparisons = [("v2", "naive")] + [(v, "v2") for v in VARIANTS] + [(v, "naive") for v in VARIANTS]
    for a, b in comparisons:
        r = _paired(totals, a, b)
        out.append(
            f"| {a} - {b} | {r['mean']:+.3f} | {r['t_rw']:.2f} | {r['p_rw']:.4f} | "
            f"{r['t_wk']:.2f} | {r['p_wk']:.4f} | {r['weeks_better']}/{r['n_weeks']} |"
        )
    out.append("")

    out.append("## MAE and bias by position (expected vs actual PPR points)")
    out.append("")
    out.append("bias = mean(expected - actual); positive = over-projecting.")
    out.append("")
    strats = list(MODEL_STRATEGIES)
    out.append("| Position | " + " | ".join(f"{s} MAE" for s in strats) + " | " + " | ".join(f"{s} bias" for s in strats) + " |")
    out.append("|---|" + "---|" * (2 * len(strats)))
    for pos in POSITIONS:
        maes = [f"{_mae(results['mae_records'][(s, pos)]):.2f}" for s in strats]
        biases = [f"{_bias(results['mae_records'][(s, pos)]):+.2f}" for s in strats]
        out.append(f"| {pos} | " + " | ".join(maes) + " | " + " | ".join(biases) + " |")
    out.append("")

    out.append("## Blowout coefficients (fit on 2024 only)")
    out.append("")
    out.append(
        "Change in a player's snap share per point of extra pregame favorite margin, relative to the "
        "games his recent snap average came from. Negative = plays fewer snaps when his team is more "
        "heavily favored."
    )
    out.append("")
    out.append("| Position | beta (snap share / spread pt) | effect of +10 pt spread | observations |")
    out.append("|---|---|---|---|")
    for pos in POSITIONS:
        b = results["betas"][pos]
        out.append(f"| {pos} | {b:+.5f} | {b * 10 * 100:+.2f} pct-pts of snaps | {results['betas']['_n'][pos]} |")
    out.append("")

    out.append("## Worked example")
    out.append("")
    out.extend(example_lines)
    out.append("")

    out.append("## Integrity checks")
    out.append("")
    out.append(
        f"- Helper that applies v2's defense x Vegas stage to a given baseline reproduced production v2 "
        f"to within {results['check']['max_err']:.2e} stat-line units over {results['check']['n']} player-weeks."
    )
    out.append(
        "- Blowout coefficients were fit on the season BEFORE the test season, so the test season is out-of-sample."
    )
    out.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    results = simulate_experiment()
    example = worked_example(results["betas"])
    path = write_report(results, example)
    logger.info("Wrote report to %s", path)


if __name__ == "__main__":
    main()
