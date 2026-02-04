"""Storage layer for draft helper API.

Provides abstraction for reading/writing data from S3, DynamoDB, and local files.
Will be populated with Sleeper draft data functions in Phase 1.
"""

import os
import json
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

try:
    import boto3
except Exception:
    boto3 = None


# Storage functions will be added in Phase 1:
# - get_round_patterns()
# - get_value_rounds()
# - get_archetypes()
# - get_player_universe()
# - etc.
