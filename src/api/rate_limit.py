"""IP-based rate limiting via slowapi.

The Limiter is defined here (not in main.py) so individual routers/endpoints
can import it without creating a circular dependency with the FastAPI app.

Behind CloudFront + ALB, the real client IP arrives in the X-Forwarded-For
header; `request.client.host` would be the ALB's private IP. The custom
key_func reads the leftmost XFF entry (the original client) when present,
falling back to the direct connection IP for local/test traffic.

Default limit: 60 requests/minute per client IP, applied globally via
SlowAPIMiddleware in main.py. Individual endpoints can override (e.g.
the feedback endpoint uses 5/minute).
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _client_ip(request: Request) -> str:
    """Resolve the real client IP, accounting for CloudFront + ALB hops."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        # Leftmost entry is the original client; subsequent entries are proxies.
        first = xff.split(",")[0].strip()
        if first:
            return first
    return get_remote_address(request)


limiter = Limiter(
    key_func=_client_ip,
    default_limits=["60/minute"],
)
