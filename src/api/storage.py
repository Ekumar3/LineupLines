import os
import json
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

try:
    import boto3
except Exception:
    boto3 = None


def get_latest_lines():
    """Return the latest lines as a parsed dict.

    Priority: S3 (if S3_BUCKET set and boto3 available) -> local file `data/latest.json`.
    """
    s3_bucket = os.environ.get("S3_BUCKET")
    if s3_bucket and boto3:
        s3 = boto3.client("s3")
        # Try common key pattern; callers should ensure this key exists
        keys = ["vegas_lines/latest.json", "latest.json"]
        for key in keys:
            try:
                obj = s3.get_object(Bucket=s3_bucket, Key=key)
                body = obj["Body"].read()
                return json.loads(body)
            except Exception:
                logger.debug("S3 key %s not found or unreadable", key)
        logger.warning("S3 fetch failed; falling back to local file")

    local_path = os.path.join(os.getcwd(), "data", "latest.json")
    with open(local_path, "r", encoding="utf-8") as f:
        return json.load(f)
