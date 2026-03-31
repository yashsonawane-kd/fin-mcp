import json

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from fin_mcp.auth.validator import (
    TokenExpiredError,
    TokenInvalidError,
    TokenMissingError,
    validator,
)
from fin_mcp.config import settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_SKIP_PATHS = ("/.well-known/", "/health")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if any(request.url.path.startswith(p) for p in _SKIP_PATHS):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            return _unauthorized_response()

        token = auth_header[len("Bearer "):]

        try:
            claims = await validator.validate(token)
        except (TokenMissingError, TokenExpiredError, TokenInvalidError) as exc:
            logger.info("Auth rejected", reason=str(exc), path=request.url.path)
            return _unauthorized_response()

        request.state.token_claims = claims
        return await call_next(request)


def _unauthorized_response() -> Response:
    metadata_url = (
        f"{settings.mcp_server_url}/.well-known/oauth-protected-resource"
    )
    www_authenticate = (
        f'Bearer realm="fin-mcp", '
        f'resource_metadata="{metadata_url}"'
    )
    body = json.dumps({"error": "unauthorized", "error_description": "Bearer token required"})
    return Response(
        content=body,
        status_code=401,
        headers={
            "WWW-Authenticate": www_authenticate,
            "Content-Type": "application/json",
        },
    )
