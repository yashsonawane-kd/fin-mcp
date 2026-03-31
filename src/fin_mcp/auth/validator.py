import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError

from fin_mcp.config import settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class TokenMissingError(Exception):
    pass


class TokenExpiredError(Exception):
    pass


class TokenInvalidError(Exception):
    pass


@dataclass(frozen=True)
class TokenClaims:
    subject: str
    email: str
    scopes: frozenset[str]
    tier: str
    expires_at: datetime


class TokenValidator:
    _jwks_cache: dict[str, Any] = {}
    _jwks_fetched_at: float = 0.0
    _jwks_ttl: float = 60.0

    async def _get_jwks(self) -> dict[str, Any]:
        now = time.monotonic()
        if not self._jwks_cache or (now - self._jwks_fetched_at) > self._jwks_ttl:
            async with httpx.AsyncClient() as client:
                response = await client.get(settings.jwks_url, timeout=10.0)
                response.raise_for_status()
                self._jwks_cache = response.json()
                self._jwks_fetched_at = now
                logger.debug("JWKS refreshed", url=settings.jwks_url)
        return self._jwks_cache

    async def validate(self, token: str) -> TokenClaims:
        if not token:
            raise TokenMissingError("No token provided")

        jwks = await self._get_jwks()

        try:
            unverified_header = jwt.get_unverified_header(token)
        except JWTError as exc:
            raise TokenInvalidError(f"Cannot decode token header: {exc}") from exc

        kid = unverified_header.get("kid")

        # If kid not found in cache, refresh once and retry
        key_found = any(k.get("kid") == kid for k in jwks.get("keys", []))
        if not key_found:
            self._jwks_fetched_at = 0.0
            jwks = await self._get_jwks()

        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                jwks,
                algorithms=["RS256"],
                audience=settings.resource_server_client_id,
                issuer=settings.issuer,
                options={"verify_exp": True},
            )
        except ExpiredSignatureError as exc:
            raise TokenExpiredError("Token has expired") from exc
        except JWTError as exc:
            raise TokenInvalidError(f"Token validation failed: {exc}") from exc

        subject: str = payload.get("sub", "")
        email: str = payload.get("email", "")

        raw_scope: str = payload.get("scope", "")
        scopes: frozenset[str] = frozenset(raw_scope.split()) if raw_scope else frozenset()

        realm_roles: list[str] = payload.get("realm_access", {}).get("roles", [])
        tier = _extract_tier(realm_roles)

        exp_timestamp: int = payload.get("exp", 0)
        expires_at = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)

        logger.debug(
            "Token validated",
            subject=subject,
            tier=tier,
            scopes=list(scopes),
        )

        return TokenClaims(
            subject=subject,
            email=email,
            scopes=scopes,
            tier=tier,
            expires_at=expires_at,
        )


def _extract_tier(roles: list[str]) -> str:
    if "analyst" in roles:
        return "analyst"
    if "premium" in roles:
        return "premium"
    return "free"


validator = TokenValidator()
