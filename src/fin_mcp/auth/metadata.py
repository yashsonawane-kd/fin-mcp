from starlette.requests import Request
from starlette.responses import JSONResponse

from fin_mcp.config import settings

SCOPES_SUPPORTED = [
    "market:read",
    "fundamentals:read",
    "technicals:read",
    "mf:read",
    "news:read",
    "news:sentiment",
    "filings:read",
    "filings:deep",
    "macro:read",
    "macro:historical",
    "research:generate",
    "watchlist:read",
    "watchlist:write",
]


async def oauth_protected_resource_handler(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "resource": settings.mcp_server_url,
            "authorization_servers": [settings.issuer],
            "scopes_supported": SCOPES_SUPPORTED,
            "bearer_methods_supported": ["header"],
        }
    )
