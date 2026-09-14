"""Offline start/sit model research harness.

Phase 0: prove a start/sit projection model beats a naive baseline before any
API or UI work. Runs fully offline against cached nflverse data — no Sleeper
API calls, no network access to src/api or src/services at runtime. The only
thing imported from the main app is pure, side-effect-free logic in
src/analytics/ (e.g. scoring-format classification).
"""
