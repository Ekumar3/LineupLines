"""Pytest / Hypothesis configuration for the in-season property-test suite.

Registers Hypothesis settings profiles shared by every property test in this
package and loads one by default so the design's "100+ iterations" bar is met
when the suite runs under CI.

Profiles
--------
``ci``   — ``max_examples=100`` with no deadline. The design requires every
           property to run at >= 100 iterations; this guarantees that floor
           even for files that do not set ``@settings(max_examples=...)``
           explicitly. (Files that opt into a higher count — e.g. 200/300 —
           keep their own setting; a per-test ``@settings`` always wins over
           the active profile.)
``dev``  — ``max_examples=25``, deadline disabled. A fast local profile for
           iterating on a single property without waiting on the full budget.

Selection
---------
The active profile is chosen from the ``HYPOTHESIS_PROFILE`` environment
variable, defaulting to ``ci`` so an un-configured ``pytest`` run still honours
the 100-iteration requirement.

This module also makes ``tests/property_tests`` a proper pytest rootdir anchor:
the shared ``strategies`` module is importable as
``tests.property_tests.strategies`` because of the package ``__init__.py``.
"""

import os

from hypothesis import HealthCheck, settings

# A floor profile: every property runs at least 100 examples under CI.
settings.register_profile(
    "ci",
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# A fast profile for local iteration.
settings.register_profile(
    "dev",
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))
