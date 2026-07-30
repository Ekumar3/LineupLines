"""Registry of ADP scraping sources the DAG iterates over.

To add a new source:
  1. Write a class in this package implementing BaseADPScraper (see draft_sharks.py).
  2. Import it below and append an instance to REGISTERED_SOURCES.
  3. Add its name to src/services/adp_sources.py's EXTERNAL_SOURCES so the app
     will read the snapshot it produces.
No DAG changes are required — adp_scrape_dag.py iterates REGISTERED_SOURCES.
"""

from adp_sources.draft_sharks import DraftSharksSource

REGISTERED_SOURCES = [DraftSharksSource()]