# Phase 2 — Core Middleware Implementation Plan

## Context
Phase 1 delivered auth infrastructure (Keycloak, JWT validation, protected resource metadata).
Phase 2 adds the four cross-cutting concerns that every tool depends on before any financial
data tools are built in Phase 4: rate limiting, scope enforcement, Redis caching, and audit logging.

Branch: `core-middleware`

---

## New File Structure

```
fin-mcp/
├── src/fin_mcp/
│   ├── rate_limit.py        # Starlette middleware: per-user/tier Redis rate limiting
│   ├── cache.py             # Async Redis cache client with TTL helpers
│   ├── audit.py             # Structured audit log via structlog
│   └── dependencies.py      # check_access(): scope check + audit in one call
├── config.py                # Updated: add redis_url + upstream API key fields
├── server.py                # Updated: add RateLimitMiddleware + Redis lifespan
├── docker-compose.yml       # Updated: add Redis service
└── .env.example             # Updated: add REDIS_URL + API key placeholders
```

---

## Dependencies

```
uv add "redis[hiredis]"
```

`redis[hiredis]` — async Redis client with fast C-extension parser.

---

## Steps

### Step 1 — Update `src/fin_mcp/config.py`

Add fields:
- `redis_url: str = "redis://localhost:6379/0"`
- `alpha_vantage_api_key: str = ""`
- `finnhub_api_key: str = ""`
- `newsapi_api_key: str = ""`

### Step 2 — `src/fin_mcp/cache.py`

`CacheClient` wrapping `redis.asyncio.Redis`:
- `get(key: str) -> Any | None` — deserialise JSON from Redis, return None on miss
- `set(key: str, value: Any, ttl: int) -> None` — serialise to JSON, write with EXPIRE
- `delete(key: str) -> None`
- `set_client(client: Redis) -> None` — called from lifespan to inject the Redis connection
- Module-level singleton `cache` used across all tools

Predefined TTL constants:
```python
TTL_QUOTE      = 60         # 1 minute
TTL_NEWS       = 1_800      # 30 minutes
TTL_FINANCIALS = 86_400     # 24 hours
TTL_FILINGS    = 0          # permanent (no expiry)
```

### Step 3 — `src/fin_mcp/rate_limit.py`

`RateLimitMiddleware` — Starlette middleware:
- Applies to all `POST /mcp` requests (the single endpoint all MCP tool calls go through)
- Gets `token_claims` from `request.state` (already set by `AuthMiddleware`)
- **Fixed window algorithm:**
  - Key: `rate_limit:{user_id}:{hour_bucket}` where `hour_bucket = int(time.time() // 3600)`
  - INCR the key; on first write set EXPIRE to 3600s
  - If count > tier limit → return HTTP 429 with `Retry-After` header
- Tier limits:
  ```
  free     →  30 calls / hour
  premium  → 150 calls / hour
  analyst  → 500 calls / hour
  ```
- 429 response body:
  ```json
  {"error": "rate_limit_exceeded", "retry_after": <seconds_until_next_window>}
  ```
- Gets Redis client from `request.app.state.redis`

### Step 4 — `src/fin_mcp/audit.py`

Single function `log_tool_call`:
```python
def log_tool_call(
    subject: str,
    tier: str,
    tool_name: str,
    status: str,    # "ok" | "forbidden"
) -> None
```

Emits one structlog JSON line per tool invocation:
```json
{
  "event": "tool_call",
  "subject": "user-123",
  "tier": "free",
  "tool": "get_stock_quote",
  "status": "ok",
  "timestamp": "2026-04-01T10:00:00Z"
}
```

Stdout JSON is sufficient for the audit requirement — no Redis write needed.

### Step 5 — `src/fin_mcp/dependencies.py`

`check_access(ctx: Context, *required_scopes: str) -> TokenClaims`

Called at the top of every tool function. Performs in order:

1. **Extract claims** from `ctx.request_context.request.state.token_claims`
2. **Scope check** — if any required scope is missing from `claims.scopes`:
   - Audit log with `status="forbidden"`
   - Raise `McpError` with message `"insufficient_scope: <missing_scope>"`
3. **Audit log** — emit `status="ok"` line

Rate limiting is handled by `RateLimitMiddleware` at the HTTP layer before the tool runs,
so `check_access` does not duplicate it.

Returns `TokenClaims` so tools can use `subject` and `tier` if needed (e.g. watchlist scoping).

### Step 6 — Update `src/fin_mcp/server.py`

Two changes:

**1. Redis lifespan:**
```python
@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncGenerator[None, None]:
    redis_client = redis.asyncio.from_url(settings.redis_url)
    app.state.redis = redis_client    # for RateLimitMiddleware
    cache.set_client(redis_client)    # for CacheClient
    yield
    await redis_client.aclose()

mcp = FastMCP("fin-mcp", lifespan=lifespan)
```

**2. Add `RateLimitMiddleware` in `build_app()`:**
Middleware is LIFO — `AuthMiddleware` must run first so `token_claims` is available
when `RateLimitMiddleware` runs.
```python
mcp_app.add_middleware(RateLimitMiddleware)
mcp_app.add_middleware(AuthMiddleware)
```

### Step 7 — Update `docker-compose.yml`

Add Redis service:
```yaml
redis:
  image: redis:7-alpine
  ports:
    - "6379:6379"
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 5s
    timeout: 3s
    retries: 5
```

### Step 8 — Update `.env.example`

```
REDIS_URL=redis://localhost:6379/0

# Upstream API keys
ALPHA_VANTAGE_API_KEY=your_key_here   # https://www.alphavantage.co/support/#api-key
FINNHUB_API_KEY=your_key_here         # https://finnhub.io/register
NEWSAPI_API_KEY=your_key_here         # https://newsapi.org/register
```

---

## Files Modified
- `src/fin_mcp/config.py`
- `src/fin_mcp/server.py`
- `docker-compose.yml`
- `.env.example`

## Files Created
- `src/fin_mcp/cache.py`
- `src/fin_mcp/rate_limit.py`
- `src/fin_mcp/audit.py`
- `src/fin_mcp/dependencies.py`

## Dependency Added
- `redis[hiredis]`

---

## How Tools Use This in Phase 4

Every tool follows this pattern:
```python
@mcp.tool(description="Get live quote for a ticker")
async def get_stock_quote(ticker: str, ctx: Context) -> dict[str, Any]:
    claims = await check_access(ctx, "market:read")
    cached = await cache.get(f"quote:{ticker}")
    if cached:
        return cached
    data = await yfinance_client.get_quote(ticker)
    await cache.set(f"quote:{ticker}", data, TTL_QUOTE)
    return data
```

---

## Verification

1. `docker compose up` → Keycloak + Redis both running
2. `uv run fin-mcp` → server starts, Redis connection logged
3. `uv run mypy src/` → no errors
4. Rate limit: call `POST /mcp` 31 times as `free-user` → 31st returns 429 + `Retry-After`
5. Scope check: call a tool requiring `fundamentals:read` as `free-user` → McpError "insufficient_scope"
6. Audit: each tool call produces a JSON log line with `"event": "tool_call"`
7. Cache: second identical tool call returns faster (Redis hit)
