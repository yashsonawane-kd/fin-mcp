import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def log_tool_call(
    subject: str,
    tier: str,
    tool_name: str,
    status: str,
) -> None:
    """Emit a structured audit log line for every tool invocation.

    Args:
        subject:   Keycloak user ID (from TokenClaims.subject)
        tier:      User tier — "free" | "premium" | "analyst"
        tool_name: Name of the MCP tool being called
        status:    Outcome — "ok" | "forbidden"
    """
    logger.info(
        "tool_call",
        subject=subject,
        tier=tier,
        tool=tool_name,
        status=status,
    )
