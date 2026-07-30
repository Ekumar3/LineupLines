FROM quay.io/astronomer/astro-runtime:13.8.0

# OS-level Chromium + driver come from packages.txt (Selenium needs a real
# browser to render DraftSharks's JS-driven rankings pages — see
# plugins/adp_sources/draft_sharks.py).

# vendored_src/ holds read-only copies of the src/ modules this project
# imports from (see scripts/vendor_src.py) — never edited in place here.
ENV PYTHONPATH="/usr/local/airflow/include/vendored_src:${PYTHONPATH}"
