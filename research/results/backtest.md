# Backtest Results — Start/Sit Model, v1 vs v2

Season: 2025  
Simulated rosters: 500  
Roster-weeks evaluated: 9000  
Hindsight-optimal average: 165.2 pts/roster-week

| Strategy | What it is |
|---|---|
| v1 | v1 (four-delta scalar) |
| v2 | v2 (defense factors x Vegas) |
| naive | naive (trailing 3-wk avg) |
| hindsight | hindsight-optimal |

## Bottom line

- **v1 beats naive**: +0.35 pts/roster-week (t=2.83, p=0.0046)
- **v2 LOSES to naive**: -0.41 pts/roster-week (t=-3.32, p=0.0009)
- **v2 LOSES to v1**: -0.76 pts/roster-week (t=-6.69, p=0.0000)

Naive leaves 24.5 pts/roster-week on the table vs. hindsight. v1 recovers +0.35 of that, v2 recovers -0.41. Most of the remainder is TD variance no pregame projection recovers.

## % of hindsight-optimal points captured

| Strategy | pts/roster-week | % of optimal |
|---|---|---|
| v1 | 141.11 | 85.41% |
| v2 | 140.35 | 84.95% |
| naive | 140.76 | 85.20% |
| hindsight | 165.22 | 100.00% |

### By starting slot

| Slot | Hindsight pts | v1 % | v2 % | naive % | v2 − v1 (pts) |
|---|---|---|---|---|---|
| QB | 191455 | 86.2% | 85.2% | 83.9% | -1765 |
| RB | 377539 | 85.9% | 86.9% | 86.7% | +3444 |
| WR | 519376 | 84.6% | 83.2% | 83.7% | -7024 |
| TE | 125460 | 82.0% | 81.6% | 82.8% | -492 |
| FLEX | 182614 | 83.7% | 83.2% | 84.7% | -1004 |
| K | 76964 | 99.5% | 99.5% | 99.5% | +0 |
| DEF | 13582 | 66.5% | 66.5% | 66.5% | +0 |

K and DEF are identical across v1/v2/naive by construction (see module docstring).

## Paired tests across roster-weeks

| Comparison | mean diff (pts) | t | p | n |
|---|---|---|---|---|
| v1 − naive | +0.351 | 2.832 | 0.0046 | 9000 |
| v2 − naive | -0.409 | -3.324 | 0.0009 | 9000 |
| v2 − v1 | -0.760 | -6.685 | 0.0000 | 9000 |

## MAE and bias (expected vs. actual PPR points), by position

bias = mean(expected − actual); positive = over-projecting.

| Position | v1 MAE | v2 MAE | naive MAE | v1 bias | v2 bias | naive bias | n |
|---|---|---|---|---|---|---|---|
| QB | 7.41 | 7.72 | 7.24 | +0.27 | +0.75 | -0.01 | 15555 |
| RB | 8.40 | 8.23 | 8.10 | +0.32 | +0.43 | +0.05 | 32894 |
| WR | 8.07 | 8.54 | 7.86 | +0.12 | +0.65 | -0.23 | 40295 |
| TE | 6.26 | 6.31 | 6.10 | -0.27 | -0.07 | -0.07 | 15466 |
| K | 4.85 | 4.85 | 4.85 | +0.78 | +0.78 | +0.78 | 8918 |
| DEF | 2.36 | 2.36 | 2.36 | -0.06 | -0.06 | -0.06 | 9000 |

All three share the same unshrunk trailing baseline, so the ~2 pt over-projection is common to all of them and does not affect the relative comparison. K/DEF rows reflect the trailing-average-only estimate, not either model.

## v2 diagnostic: does the defense factor predict the residual?

For each modeled player-week, residual = actual − baseline PPR points from that channel's components only. If the opponent-adjusted factor carries real signal, residual should rise with the factor (defenses that allow more → players beat their baseline more).

| Channel | Pearson r (log factor, residual) | n |
|---|---|---|
| pass | 0.073 | 104210 |
| rush | 0.062 | 104210 |

**pass channel, by factor quintile**

| Quintile | mean factor | mean residual (pts) | n |
|---|---|---|---|
| Q1 | 0.905 | -1.12 | 20842 |
| Q2 | 0.957 | +0.45 | 20842 |
| Q3 | 1.001 | +0.25 | 20842 |
| Q4 | 1.036 | -0.22 | 20842 |
| Q5 | 1.108 | +1.11 | 20842 |

**rush channel, by factor quintile**

| Quintile | mean factor | mean residual (pts) | n |
|---|---|---|---|
| Q1 | 0.873 | -0.48 | 20842 |
| Q2 | 0.945 | -0.42 | 20842 |
| Q3 | 0.997 | -0.12 | 20842 |
| Q4 | 1.059 | +0.29 | 20842 |
| Q5 | 1.146 | +0.69 | 20842 |

## v1 error attribution: correlation of each delta with prediction error

error = actual_points_ppr − expected_points_ppr (QB/RB/WR/TE only)

| Delta term | Pearson r vs. error | n |
|---|---|---|
| delta_opportunity | -0.144 | 104210 |
| delta_environment | -0.172 | 104210 |
| delta_efficiency | -0.031 | 104210 |
| delta_matchup | -0.037 | 104210 |

## Configuration

v1 weights (untouched):

```json
{
  "delta_opportunity": 0.45,
  "delta_environment": 0.25,
  "delta_efficiency": 0.2,
  "delta_matchup": 0.1
}
```

v2 config:

```json
{
  "environment_weight": 0.25,
  "ridge_lambda": 4.0,
  "prior_season_weight": 0.3,
  "factor_clamp": [
    0.75,
    1.25
  ]
}
```
