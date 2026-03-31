import structlog
from mcp.server.fastmcp import FastMCP

from fin_mcp.logging import configure_logging

configure_logging()

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

mcp: FastMCP = FastMCP("fin-mcp")


def main() -> None:
    logger.info("Starting fin-mcp server")
    mcp.run()


if __name__ == "__main__":
    main()
