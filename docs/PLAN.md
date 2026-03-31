# fin-mcp: High-Level Build Plan

**Use Case:** PS1 — Financial Research Copilot
**Stack:** Python + FastMCP + Keycloak + Redis + Docker Compose

---

## Phase 1 — Auth Infrastructure

Set up Keycloak as a standalone OAuth 2.1 server in Docker. Configure realms, clients, and the three user tiers (Free, Premium, Analyst) as roles mapped to scopes. Build the MCP server's auth middleware: token validation (signature, expiry, audience, scopes), the `/.well-known/oauth-protected-resource` metadata endpoint, and proper 401/403 responses.

---

## Phase 2 — Core Middleware

Build the cross-cutting concerns that every tool depends on:

- **Rate limiting** — per-user, per-tier (30/150/500 calls/hour) with Redis counters and 429 + `Retry-After`
- **Scope enforcement** — decorator that checks required scopes before any tool runs
- **Redis cache** — TTL-based cache layer wrapping all upstream API calls (60s quotes, 30min news, 24h financials, permanent filings)
- **Audit logging** — every tool invocation logged: user identity, tier, tool name, timestamp
- **Upstream API key management** — all keys loaded from server config, never exposed to clients

---

## Phase 3 — Data Source Clients

Thin, typed Python clients for each upstream API:

| Client | Data | Auth |
|--------|------|------|
| yfinance | Market data, OHLCV, financials, balance sheet, cash flow | Free, no key |
| MFapi.in | NAV history, scheme search | Free, no key |
| Alpha Vantage | Technical indicators (SMA, RSI, MACD, Bollinger) | Free API key |
| Finnhub | Company news, earnings, recommendations | Free API key |
| BSE India | Corporate filings and announcements | Free, no key |
| RBI DBIE | Repo rate, CPI, GDP, forex | Free |
| NewsAPI | Market and company news | Free API key |

---

## Phase 4 — MCP Tools (20 tools)

All tools enforce scope + rate limit + cache.

**Market (5):** `get_stock_quote`, `get_price_history`, `get_index_data`, `get_top_gainers_losers`, `get_technical_indicators`

**Fundamental (4):** `get_financial_statements`, `get_key_ratios`, `get_shareholding_pattern`, `get_quarterly_results`

**Mutual Funds (3):** `search_mutual_funds`, `get_fund_nav`, `compare_funds`

**News & Sentiment (3):** `get_company_news`, `get_news_sentiment`, `get_market_news`

**Macro & Filings (2):** `get_rbi_rates`, `get_inflation_data`, `get_corporate_filings`

### Tier Access

| Tool Category | Free | Premium | Analyst |
|---------------|------|---------|---------|
| Market data | ✅ | ✅ | ✅ |
| Fundamentals | ❌ | ✅ | ✅ |
| Technicals | ❌ | ✅ | ✅ |
| Mutual Funds | ✅ | ✅ | ✅ |
| News | ✅ | ✅ | ✅ |
| News sentiment | ❌ | ✅ | ✅ |
| Filings list | ❌ | ❌ | ✅ |
| Macro current | ❌ | ✅ | ✅ |
| Macro historical | ❌ | ❌ | ✅ |
| Rate limit | 30/hr | 150/hr | 500/hr |

---

## Phase 5 — Cross-Source Tools (Analyst tier only)

The differentiators — call multiple APIs, reconcile signals, cite sources explicitly.

- **`cross_reference_signals`** — combines price, filings, shareholding, news sentiment; flags what confirms vs contradicts across sources
- **`generate_research_brief`** — full structured note synthesised from 5+ sources with per-source citations
- **`compare_companies`** — side-by-side across price performance, fundamentals, MF exposure, news, shareholding

---

## Phase 6 — Resources & Prompts

**Resources:**
- `watchlist://{user_id}/stocks` — user's personal watchlist (auth-scoped)
- `research://{ticker}/latest` — most recent cached research brief
- `market://overview` — Nifty, Sensex, Bank Nifty, top gainers/losers, FII/DII summary
- `macro://snapshot` — latest repo rate, CPI, GDP growth, forex reserves, USD-INR

**Prompts:**
- `quick_analysis` — fast overview: quote + key ratios + recent news
- `deep_dive` — comprehensive: all data, cross-referenced, full research brief
- `sector_scan` — compare top companies in a Nifty sector across fundamentals and sentiment
- `morning_brief` — daily summary: market overview + watchlist + macro + key news

**Capability negotiation:** Free users discover fewer tools than Analysts at connection time.

---

## Phase 7 — Docker Compose

One-command local deployment:

```
docker compose up
```

Services:
- `mcp-server` — FastMCP Python application (Streamable HTTP transport)
- `keycloak` — OAuth 2.1 auth server
- `redis` — cache + rate limit counters

Deliverables:
- `docker-compose.yml`
- `.env.example` with all required API keys and sign-up links
- Health-check endpoint: upstream API status + remaining quotas
- `README.md` with setup instructions

---

## Build Order

```
Phase 1  →  Phase 2  →  Phase 3  →  Phase 4  →  Phase 5  →  Phase 6  →  Phase 7
  Auth       Core         API        20 Tools    3 Cross-    Resources    Docker
  Server    Middleware   Clients                  Source      & Prompts   Compose
                                                  Tools
```

Each phase is independently testable. Phases 1–3 are infrastructure; Phases 4–6 are product; Phase 7 is deployment.

---

## Scope Reference

| Scope | Grants Access To |
|-------|-----------------|
| `market:read` | Live quotes, price history, indices, movers |
| `fundamentals:read` | Financial statements, ratios, shareholding, results |
| `technicals:read` | Technical indicators |
| `mf:read` | Mutual fund NAV, search, comparison |
| `news:read` | News articles |
| `news:sentiment` | Aggregated sentiment analysis |
| `filings:read` | List filings |
| `filings:deep` | Retrieve full filing documents |
| `macro:read` | RBI rates, inflation, forex (current) |
| `macro:historical` | Full historical macro time series |
| `research:generate` | Cross-source reasoning tools |
| `watchlist:read` / `watchlist:write` | Personal watchlist |
