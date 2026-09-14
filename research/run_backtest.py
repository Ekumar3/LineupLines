"""Entrypoint: run the Phase 0 backtest end to end.

    python -m research.run_backtest

Pulls (and caches) nflverse data, simulates rosters, computes the three
lineups per roster-week, writes the prediction log, and writes
research/results/backtest.md.
"""

import logging

from research.backtest import RESULTS_DIR, simulate, write_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    results = simulate()
    report_path = write_report(results, RESULTS_DIR / "backtest.md")
    logger.info("Wrote report to %s", report_path)


if __name__ == "__main__":
    main()
