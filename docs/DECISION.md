# Odds API vs Web Scraping — Decision Notes ✅

## Quick recommendation
Use a stable odds API (e.g., The Odds API) for the core product data ingestion and reserve scraping only for specific edge cases where a required prop or book isn't available via APIs.

## Why an Odds API (pros)
- **Reliability & scale**: Aggregators provide normalized data across many bookmakers (80+ for The Odds API).
- **Speed to market**: Less engineering time than building and maintaining scrapers for every book.
- **Legal / TOS**: Many scrape targets explicitly prohibit scraping; API access mitigates legal risk and is usually documented.
- **Normalized formats**: Less parsing/transformation work; lower bug surface.
- **Rate-limited & predictable**: Clear limits and tiers — helps plan caching and ingestion frequency.

## When to consider scraping (cons)
- **Coverage gaps**: If an important prop or local bookmaker is not available via any API.
- **Cost**: High-volume API usage can become expensive; scraping may reduce costs if compliant.
- **Latency**: Some niche books might publish data faster on their site (rare).

## Hybrid approach (recommended)
- Primary ingestion: **Odds API** (The Odds API / OddsAPI / Pinnacle partners if needed)
- Fallback/augmentation: **Targeted scraping** (use headless browser, rotate IPs, respect robots.txt and TOS)
- Cache everything in S3/DynamoDB with versions and provenance metadata

## Compliance & operational notes
- Carefully read API provider TOS and site ToS for any scraping fallback.
- Track timestamps, source (bookmaker), and scraper/API version in metadata.
- Add automated tests and data-quality checks to detect provider format or content changes.
