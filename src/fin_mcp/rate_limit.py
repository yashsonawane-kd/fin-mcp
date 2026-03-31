import json
import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from fin_mcp.auth.validator import TokenClaims
from fin_mcp.cache import get_cache
from fin_mcp.config import settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _tier_limits() -> dict[str, int]:
    return {
        "free": settings.rate_limit_free,
        "premium": settings.rate_limit_premium,
        "analyst": settings.rate_limit_analyst,
    }


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Only rate limit MCP tool calls
        if request.method != "POST" or request.url.path != "/mcp":
            return await call_next(request)

        claims: TokenClaims = request.state.token_claims
        limit = _tier_limits().get(claims.tier, settings.rate_limit_free)
        hour_bucket = int(time.time() // 3600)
        key = f"rate_limit:{claims.subject}:{hour_bucket}"

        redis = get_cache()._require_client()
        count: int = await redis.incr(key)
        if count == 1:
            # First call in this window — set expiry
            await redis.expire(key, 3600)

        if count > limit:
            seconds_remaining = 3600 - (int(time.time()) % 3600)
            logger.info(
                "Rate limit exceeded",
                subject=claims.subject,
                tier=claims.tier,
                count=count,
                limit=limit,
            )
            body = json.dumps({
                "error": "rate_limit_exceeded",
                "retry_after": seconds_remaining,
            })
            return Response(
                content=body,
                status_code=429,
                headers={
                    "Retry-After": str(seconds_remaining),
                    "Content-Type": "application/json",
                },
            )

        logger.debug(
            "Rate limit check passed",
            subject=claims.subject,
            tier=claims.tier,
            count=count,
            limit=limit,
        )
        return await call_next(request)
