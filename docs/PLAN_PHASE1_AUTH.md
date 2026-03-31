# Phase 1 — Auth Infrastructure Implementation Plan

## Context
The fin-mcp server (PS1 Financial Research Copilot) requires OAuth 2.1 + PKCE authentication
with tiered access control (Free / Premium / Analyst). Keycloak is the auth server (separate
from the MCP resource server). This phase wires up Keycloak in Docker, builds the token
validation middleware, and exposes the Protected Resource Metadata endpoint (RFC 9728).

Branch: `auth-setup`
Existing files: `src/fin_mcp/server.py`, `src/fin_mcp/logging.py`, `pyproject.toml`

---

## New File Structure

```
fin-mcp/
├── docker-compose.yml               # Keycloak only for now (Redis + MCP server added later)
├── docker/
│   └── keycloak/
│       └── realm-export.json        # Importable Keycloak realm config
├── .env.example                     # Required env vars with instructions
└── src/fin_mcp/
    ├── config.py                    # Typed settings loaded from env (pydantic-settings)
    ├── auth/
    │   ├── __init__.py
    │   ├── validator.py             # JWT validation against Keycloak JWKS
    │   ├── middleware.py            # Starlette auth middleware (401/403)
    │   └── metadata.py             # /.well-known/oauth-protected-resource handler
    └── server.py                   # Updated: mount middleware + metadata route
```

---

## Steps

### Step 1 — Add dependencies
```
uv add "python-jose[cryptography]" httpx pydantic-settings
uv add --dev uvicorn
```

- `python-jose[cryptography]` — JWT decode + JWKS signature validation
- `httpx` — async HTTP client for fetching JWKS from Keycloak
- `pydantic-settings` — typed config loaded from `.env`
- `uvicorn` (dev) — run the ASGI app directly with full control

### Step 2 — `src/fin_mcp/config.py`
Typed settings class using `pydantic-settings`. Loaded once at startup.

Key fields:
- `keycloak_url: str` — base Keycloak URL (e.g. `http://localhost:8080`)
- `keycloak_realm: str` — realm name (e.g. `fin-mcp`)
- `resource_server_client_id: str` — audience to validate in tokens (e.g. `mcp-resource-server`)
- `mcp_server_url: str` — public URL of this server (used in metadata response)
- `log_level: str` — default `"INFO"`

JWKS URL derived from config: `{keycloak_url}/realms/{keycloak_realm}/protocol/openid-connect/certs`
Issuer derived from config: `{keycloak_url}/realms/{keycloak_realm}`

### Step 3 — `src/fin_mcp/auth/validator.py`
`TokenValidator` class:
- Fetches + caches JWKS from Keycloak (refreshed every 60s or on `kid` miss)
- `validate(token: str) -> TokenClaims` — raises typed exceptions on failure

`TokenClaims` typed dataclass:
```python
@dataclass
class TokenClaims:
    subject: str          # Keycloak user ID
    email: str
    scopes: frozenset[str]
    tier: str             # "free" | "premium" | "analyst"
    expires_at: datetime
```

Validation steps:
1. Decode header → extract `kid`
2. Fetch matching key from JWKS cache (refresh if `kid` not found)
3. Decode + verify signature via `python-jose`
4. Assert `iss` == `{keycloak_url}/realms/{keycloak_realm}`
5. Assert `aud` contains `resource_server_client_id` (RFC 8707)
6. Assert `exp` not passed
7. Extract `scope` claim → `frozenset[str]`
8. Extract tier from `realm_access.roles`
9. Return `TokenClaims`

Typed exceptions:
- `TokenMissingError` → 401
- `TokenExpiredError` → 401
- `TokenInvalidError` → 401

### Step 4 — `src/fin_mcp/auth/middleware.py`
`AuthMiddleware` — pure Starlette ASGI middleware:

- **Skip** validation for: `/.well-known/*`, `/health`
- Extract `Authorization: Bearer <token>` header
- Missing/invalid token → 401 with:
  ```
  WWW-Authenticate: Bearer realm="fin-mcp",
    resource_metadata="<mcp_server_url>/.well-known/oauth-protected-resource"
  ```
- Valid token → attach `TokenClaims` to `request.state.token_claims`

### Step 5 — `src/fin_mcp/auth/metadata.py`
Handler for `GET /.well-known/oauth-protected-resource` (RFC 9728):

```json
{
  "resource": "<mcp_server_url>",
  "authorization_servers": ["<keycloak_url>/realms/<realm>"],
  "scopes_supported": [
    "market:read", "fundamentals:read", "technicals:read",
    "mf:read", "news:read", "news:sentiment",
    "filings:read", "filings:deep",
    "macro:read", "macro:historical",
    "research:generate",
    "watchlist:read", "watchlist:write"
  ],
  "bearer_methods_supported": ["header"]
}
```

### Step 6 — Update `src/fin_mcp/server.py`
- Load config + configure logging at startup
- Get Starlette app from FastMCP: `mcp.streamable_http_app()`
- Mount `AuthMiddleware`
- Register `/.well-known/oauth-protected-resource` and `/health` routes
- Run via `uvicorn` directly

### Step 7 — Keycloak Docker setup
`docker-compose.yml` (Keycloak only for Phase 1):
```yaml
services:
  keycloak:
    image: quay.io/keycloak/keycloak:26.0
    command: start-dev --import-realm
    environment:
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: admin
    volumes:
      - ./docker/keycloak:/opt/keycloak/data/import
    ports:
      - "8080:8080"
```

`docker/keycloak/realm-export.json` configures:
- Realm: `fin-mcp`
- Client `mcp-resource-server` (bearer-only, token audience)
- Client `mcp-public-client` (public, PKCE, localhost redirect URIs)
- Realm roles: `free`, `premium`, `analyst`
- 13 client scopes, one per scope string
- Default role: `free` for new users

### Step 8 — `.env.example`
```
KEYCLOAK_URL=http://localhost:8080
KEYCLOAK_REALM=fin-mcp
RESOURCE_SERVER_CLIENT_ID=mcp-resource-server
MCP_SERVER_URL=http://localhost:3000
LOG_LEVEL=INFO
```

---

## Files Modified
- `src/fin_mcp/server.py`

## Files Created
- `src/fin_mcp/config.py`
- `src/fin_mcp/auth/__init__.py`
- `src/fin_mcp/auth/validator.py`
- `src/fin_mcp/auth/middleware.py`
- `src/fin_mcp/auth/metadata.py`
- `docker-compose.yml`
- `docker/keycloak/realm-export.json`
- `.env.example`

## Dependencies Added
- `python-jose[cryptography]`
- `httpx`
- `pydantic-settings`
- `uvicorn` (dev)

---

## Verification
1. `docker compose up` → Keycloak at `http://localhost:8080`
2. `uv run fin-mcp` → MCP server at `http://localhost:3000`
3. `curl http://localhost:3000/.well-known/oauth-protected-resource` → JSON metadata
4. `curl http://localhost:3000/` → 401 with `WWW-Authenticate` header
5. Valid Bearer token → 200; expired/tampered token → 401
6. `uv run mypy src/` → no errors
