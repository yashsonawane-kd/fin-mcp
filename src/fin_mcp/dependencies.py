import functools
import inspect
from collections.abc import Callable, Coroutine
from typing import Any

from mcp.server.fastmcp import Context
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData, INVALID_REQUEST

from fin_mcp.audit import log_tool_call
from fin_mcp.auth.validator import TokenClaims


async def check_access(ctx: Context, *required_scopes: str) -> TokenClaims:
    """Validate scope access for a tool call and emit an audit log entry.

    Used internally by the @require_scopes decorator, but can also be called
    directly when dynamic scope checking is needed.

    Args:
        ctx:             FastMCP Context injected by the framework.
        required_scopes: One or more scope strings the caller must hold.

    Returns:
        TokenClaims — available to the tool for subject/tier-scoped logic.

    Raises:
        McpError: with message "insufficient_scope: <scope>" if any scope is missing.
    """
    request = ctx.request_context.request
    if request is None:
        raise McpError(ErrorData(code=INVALID_REQUEST, message="No request context available"))
    claims: TokenClaims = request.state.token_claims

    missing = [s for s in required_scopes if s not in claims.scopes]
    if missing:
        log_tool_call(
            subject=claims.subject,
            tier=claims.tier,
            tool_name=_tool_name(ctx),
            status="forbidden",
        )
        raise McpError(
            ErrorData(
                code=INVALID_REQUEST,
                message=f"insufficient_scope: {', '.join(missing)}",
            )
        )

    log_tool_call(
        subject=claims.subject,
        tier=claims.tier,
        tool_name=_tool_name(ctx),
        status="ok",
    )
    return claims


def require_scopes(
    *required_scopes: str,
) -> Callable[[Callable[..., Coroutine[Any, Any, Any]]], Callable[..., Coroutine[Any, Any, Any]]]:
    """Decorator that enforces scope access before a tool function runs.

    Usage:
        @mcp.tool()
        @require_scopes("market:read")
        async def get_stock_quote(ticker: str, ctx: Context) -> dict:
            ...

    FastMCP injects Context by inspecting the function signature. Because
    @functools.wraps preserves __wrapped__, FastMCP still sees the original
    signature and correctly injects the Context parameter.
    """
    def decorator(
        func: Callable[..., Coroutine[Any, Any, Any]],
    ) -> Callable[..., Coroutine[Any, Any, Any]]:
        # Locate the Context parameter once at decoration time
        sig = inspect.signature(func)
        ctx_param_name: str | None = None
        for name, param in sig.parameters.items():
            if param.annotation is Context:
                ctx_param_name = name
                break

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx: Context | None = None

            if ctx_param_name is not None:
                if ctx_param_name in kwargs:
                    ctx = kwargs[ctx_param_name]
                else:
                    param_names = list(sig.parameters.keys())
                    idx = param_names.index(ctx_param_name)
                    if idx < len(args):
                        ctx = args[idx]

            if ctx is not None:
                await check_access(ctx, *required_scopes)

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def _tool_name(ctx: Context) -> str:
    """Best-effort extraction of the tool name from the MCP request context."""
    try:
        request = ctx.request_context.request
        if request is None:
            return "unknown"
        return str(request.scope.get("path", "unknown"))
    except Exception:
        return "unknown"
