"""Copies the src/ modules the Airflow plugins import into include/vendored_src/.

The Airflow project builds from airflow/ as its Docker context, so it can't
COPY ../src directly. Run this before `astro dev start` / `astro deploy` to
refresh the vendored copies. Read-only against src/ — never writes there.

    python airflow/scripts/vendor_src.py
"""

import shutil
from pathlib import Path

AIRFLOW_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = AIRFLOW_DIR.parent
SRC_ROOT = REPO_ROOT / "src"
# Preserves the "src" package name (not flattened) so the vendored modules'
# own `from src.x.y import z` absolute imports work unmodified.
VENDOR_ROOT = AIRFLOW_DIR / "include" / "vendored_src"
VENDOR_SRC_PKG = VENDOR_ROOT / "src"

# Relative to src/. Keep in sync with the imports in plugins/adp_sources/
# and the transitive imports inside these modules themselves.
FILES_TO_VENDOR = [
    "__init__.py",
    "data_sources/__init__.py",
    "data_sources/fantasypros_client.py",
    "data_sources/sleeper_client.py",
    "analytics/__init__.py",
    "analytics/adp_service.py",
    "analytics/adp_analyzer.py",
]


def main() -> None:
    if VENDOR_ROOT.exists():
        shutil.rmtree(VENDOR_ROOT)
    VENDOR_SRC_PKG.mkdir(parents=True)

    for rel_path in FILES_TO_VENDOR:
        src_file = SRC_ROOT / rel_path
        dest_file = VENDOR_SRC_PKG / rel_path
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        if src_file.exists():
            shutil.copy2(src_file, dest_file)
        else:
            # __init__.py files may not exist in src/ if it relies on implicit
            # namespace packages — create an empty one so imports still work.
            dest_file.touch()
        print(f"vendored {rel_path}")


if __name__ == "__main__":
    main()
