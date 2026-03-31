from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as aioredis
import structlog
import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp

from fin_mcp.auth.metadata import oauth_protected_resource_handler
from fin_mcp.auth.middleware import AuthMiddleware
from fin_mcp.cache import get_cache
from fin_mcp.config import settings
from fin_mcp.logging import configure_logging
from fin_mcp.rate_limit import RateLimitMiddleware

configure_logging(settings.log_level)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

mcp: FastMCP = FastMCP("fin-mcp")


async def health_handler(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "fin-mcp"})


def build_app() -> Starlette:
    mcp_app = mcp.streamable_http_app()

    # Wrap the existing MCP lifespan to also initialise Redis
    original_lifespan = mcp_app.router.lifespan_context

    @asynccontextmanager
    async def combined_lifespan(app: ASGIApp) -> AsyncGenerator[Any, None]:
        redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        get_cache().set_client(redis_client)
        logger.info("Redis connected", url=settings.redis_url)
        try:
            async with original_lifespan(app):
                yield
        finally:
            await redis_client.aclose()
            logger.info("Redis connection closed")

    mcp_app.router.lifespan_context = combined_lifespan

    # Prepend our routes so they match before MCP routes
    mcp_app.router.routes.insert(
        0, Route("/.well-known/oauth-protected-resource", oauth_protected_resource_handler)
    )
    mcp_app.router.routes.insert(1, Route("/health", health_handler))

    # Middleware is LIFO: AuthMiddleware runs first, then RateLimitMiddleware
    mcp_app.add_middleware(RateLimitMiddleware)
    mcp_app.add_middleware(AuthMiddleware)
    return mcp_app


def main() -> None:
    logger.info(
        "Starting fin-mcp server",
        host=settings.mcp_host,
        port=settings.mcp_port,
        keycloak_url=settings.keycloak_url,
        realm=settings.keycloak_realm,
    )
    uvicorn.run(build_app(), host=settings.mcp_host, port=settings.mcp_port)


if __name__ == "__main__":
    main()
