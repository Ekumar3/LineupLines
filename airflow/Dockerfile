FROM quay.io/astronomer/astro-runtime:13.8.0

# OS-level Chromium + driver come from packages.txt (Selenium needs a real
# browser to render DraftSharks's JS-driven rankings pages — see
# plugins/adp_sources/draft_sharks.py). astro-runtime runs as a non-root
# "astro" user (uid=50000, gid=50000) by default; apt-get needs root.
USER root
COPY packages.txt requirements.txt ./
RUN apt-get update \
    && xargs -a packages.txt apt-get install -y --no-install-recommends \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY dags/ dags/
COPY plugins/ plugins/
COPY include/ include/
COPY scripts/start.sh scripts/start.sh
RUN chmod +x scripts/start.sh

# vendored_src/ holds read-only copies of the src/ modules this project
# imports from (see scripts/vendor_src.py) — populated on the CI runner
# BEFORE `docker build` (vendor_src.py copies from outside this build
# context), never edited in place here.
ENV PYTHONPATH="/usr/local/airflow/include/vendored_src:${PYTHONPATH}"

USER astro

# No ENTRYPOINT override — the base image's own entrypoint (tini + astro's
# /entrypoint, confirmed via `docker inspect`) correctly execs whatever CMD is
# passed, and handles signals/plugin init we don't want to lose. Only CMD is
# overridden, to run the one-time-safe DB migration before starting the
# scheduler (see scripts/start.sh).
CMD ["bash", "scripts/start.sh"]
