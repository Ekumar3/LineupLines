# LineupLines — Plan & Progress ✅

## TL;DR
- Target: Build a freemium fantasy football product that aggregates Vegas lines and provides contextual draft/start-sit advice. 
- Strategy: Start with a robust API-based ingestion (The Odds API) + canonical schema, add targeted scraping only for coverage gaps, integrate Sleeper for live drafts, and ship iteratively using short sprints.

---

## What I implemented so far (progress) 🔍
- Prototype code and tests (all passing locally):
  - `src/vegas_pipeline/handler.py` — Lambda fetcher that stores payload to S3 (or `data/latest.json` locally)
  - `src/vegas_pipeline/fetchers/the_odds_api.py` — minimal The Odds API wrapper (returns sample data when no key)
  - `infra/template.yaml` — SAM template: Lambda + EventBridge schedule + S3
  - `scripts/run_local.py` and `scripts/run_api.py` — local fetch runner and FastAPI runner
  - `src/api/main.py` + `src/api/storage.py` — minimal API with `/health` and `/lines/latest`
  - `public/index.html` — tiny demo frontend calling the API
  - Tests: `tests/test_fetcher.py`, `tests/test_api.py` (5 tests, all passing)
  - Docs: `docs/DECISION.md`, `docs/README_PROTOTYPE.md`, `docs/NEXT_STEPS.md`

---

## Recommended roadmap & milestones (12-week plan; adapt as needed) 🗺️
- Sprint 0 (1–2 weeks): Finalize data model & provider onboarding
  - Choose primary odds provider(s) and sign up for API keys.
  - Define canonical schema for odds & props (JSON Schema).
  - Add CI checks and test matrix.

- Sprint 1 (2 weeks): Reliable ingestion + storage (MVP)
  - Implement robust `fetcher` with retries, backoff, and metrics.
  - Persist raw payloads in S3 and build `latest_by_player` DynamoDB table.
  - Add provenance metadata (timestamp, provider, fetcher version).
  - Acceptance: Weekly scheduled runs succeed; `latest` queries return up-to-date data.

- Sprint 2 (2 weeks): Data quality & mapping
  - Implement schema validation and data-quality checks (bad/invalid events alert).
  - Build player normalization & mapping service (to match Sleeper/ESPN IDs).
  - Acceptance: Tests for schema validity and mapping coverage.

- Sprint 3 (2 weeks): Sleeper integration & live draft features
  - Integrate Sleeper read-only endpoints and draft events.
  - Add draft-time real-time recommendations (simple heuristics first).
  - Acceptance: Demo live draft flow works with sample leagues.

- Sprint 4 (2 weeks): Product & gating
  - Build web UI to show lines, diffs, and recommendations.
  - Add auth & paid-tier gating (JWT/API keys + minimal billing integration).
  - Acceptance: Gate one advanced endpoint behind a paid flag.

- Sprint 5 (2–4 weeks): Hardening & launch prep
  - Add logging, monitoring, SLOs, autoscaling config, and cost estimates.
  - Run load tests and fix scaling bottlenecks.
  - Beta launch: onboard small user groups, gather feedback and metrics.

- Add draft grades

---

## Key architecture choices & rationale 💡
- Data ingestion: prefer an Odds API (The Odds API) for coverage, reliability, and normalized fields; fallback to targeted scraping only when necessary (see `docs/DECISION.md`).
- Storage: Raw S3 archive + DynamoDB `latest_by_player` for low-latency reads.
- Compute: AWS Lambda scheduled by EventBridge for periodic fetches; consider Step Functions for complex workflows.
- API: FastAPI for rapid iteration and local dev.
- Realtime draft: Integrate Sleeper webhooks/polling and route events to Lambda/WS for real-time recommendations.

---

## Risks & mitigations ⚠️
- Provider limits/costs: start with free tiers, add caching and backoff; monitor usage and adapt frequency.
- Data schema drift: implement JSON Schema checks and automated alerts on unexpected changes.
- Player matching (name mismatches): build a canonical ID table and fuzzy match with manual review for edge cases.

---

## Minimum viable product (MVP) acceptance criteria ✅
- Fetch and store Vegas lines for NFL (scheduled, visible in S3).
- API exposes `/lines/latest` with canonical fields and provenance.
- Demo UI shows latest lines and basic start/sit guidance.
- Sleeper integration can read a sample league and produce team-context recommendations.

---

## Immediate next tasks (pick 1–2 to start) ▶️
1. Wire Lambda to write raw payloads to S3 and write canonical rows to DynamoDB + add unit tests.  
2. Implement JSON Schema validation + data-quality checks and CloudWatch alarms.  
3. Add Sleeper integration module and a basic draft recommendation engine (heuristic-based).

---

## Notes on timelines & costs 💰
- Small-scale prototype (development + small beta) should fit within modest AWS costs (S3 storage, DynamoDB on-demand, Lambda invocations, small API Gateway/ALB costs). API provider costs depend on request volumes — estimate after a 1-week sample run.

---

If you want, I can now implement the S3 + DynamoDB writes and tests (task 1) and add schema validation (task 2) in the same sprint. Which should I prioritize next?