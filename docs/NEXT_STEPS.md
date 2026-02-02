# First Sprint — Actionable Next Steps ✅

1. Integrate The Odds API (priority)
   - Register for API key (free tier) and set up env/SecretsManager
   - Map provider fields to our canonical model (event, teams, market, outcome, price, book)
   - Add ingestion retries, exponential backoff, and logging

2. Data pipeline infra
   - Deploy SAM stack: Lambda + EventBridge rule + S3 bucket
   - Configure CloudWatch log retention and alarms for Lambda failures
   - Add schema validation (JSON Schema) and data-quality checks

3. Sleeper API integration
   - Add a module to pull draft/roster data (read-only)
   - Create webhooks or periodic pulls for live draft events
   - Build a matching layer between Sleeper player IDs and our player names (fuzzy-match + canonical table)

4. Analytics & storage
   - Add DynamoDB table for "latest_by_player" and an S3 raw archive
   - Add simple Athena/Glue catalog for exploratory analytics (optional)

5. Product
   - Build a simple UI that shows latest lines and recent changes
   - Add user auth & plan gating (free vs paid)


> Tip: Start with API-based ingestion and a clear canonical schema. Add scraping only after evaluating coverage gaps.
