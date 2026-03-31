# fin-mcp: High-Level Build Plan

**Use Case:** PS2 — Portfolio Risk & Alert Monitor
**Stack:** Python + FastMCP + Keycloak + Redis + PostgreSQL + Docker Compose

---

## Phase 1 — Auth Infrastructure *(reuse from PS1)*

Identical to PS1. Keycloak OAuth 2.1 server, three tiers (Free, Premium, Analyst), token
validation middleware, `/.well-known/oauth-protected-resource`, 401/403 responses.

Additional scopes needed beyond PS1:
- `portfolio:read` / `portfolio:write` — holdings, summaries, risk tools
- `portfolio:alerts` — subscribe to alert notifications

---

## Phase 2 — Core Middleware *(reuse from PS1, with additions)*

Same rate limiting, scope enforcement, Redis cache, audit logging, and API key management
as PS1.

**Additions specific to PS2:**
- **Persistent data store (PostgreSQL)** — user portfolio holdings must survive restarts. Redis alone is insufficient; holdings are mutable user data, not a cache.
- **Alert state machine** — track active vs resolved alerts per user, with deduplication so the same signal doesn't fire repeatedly.
- **Subscription manager** — maintain a registry of active client subscriptions keyed by `user_id`, ready to push notifications when alerts fire.

---

## Phase 3 — Data Source Clients *(reuse from PS1)*

Same clients as PS1. PS2 relies on a subset:

| Client | Used For |
|--------|----------|
| yfinance | Live quotes, price history, sector mapping |
| MFapi.in | MF scheme data for overlap checks |
| Finnhub | News sentiment per holding |
| NewsAPI | Broader news for sentiment baseline |
| RBI DBIE | Macro indicators (rate sensitivity analysis) |
| Alpha Vantage | Technical data if needed for risk signals |

No BSE filings client needed for PS2.

---

## Phase 4 — MCP Tools (18 tools)

All tools enforce scope + rate limit + cache.

### Portfolio Management Tools (Free+)
- `add_to_portfolio` — add stock with quantity and avg buy price
- `remove_from_portfolio` — remove a holding
- `get_portfolio_summary` — current value, P&L, allocation breakdown by stock and sector

### Risk Detection Tools (Premium+)
- `portfolio_health_check` — concentration risk, sector exposure, top holdings as % of total
- `check_concentration_risk` — flag if any stock > 20% or sector > 40% of portfolio
- `check_mf_overlap` — compare user's holdings against top large-cap MF schemes; surface hidden double exposure
- `check_macro_sensitivity` — map each holding to macro factors (rate-sensitive, inflation-sensitive, forex-sensitive); flag adverse current conditions
- `detect_sentiment_shift` — compare 7-day news sentiment vs 30-day baseline per holding; flag significant shifts

### Market Data Tools (shared, Free+)
- `get_stock_quote` — live/latest quote
- `get_price_history` — historical OHLCV
- `get_index_data` — index values and composition
- `get_top_gainers_losers` — today's movers

### Supporting Tools
- `get_shareholding_pattern` — promoter, FII, DII holdings (Premium+)
- `get_company_news` — latest news per holding (Free+)
- `get_news_sentiment` — aggregated sentiment (Premium+)
- `get_rbi_rates` — current macro rates (Premium+)
- `get_inflation_data` — CPI/WPI (Premium+)
- `search_mutual_funds` / `get_fund_nav` — MF data for overlap (Free+)

### Tier Access

| Tool Category | Free | Premium | Analyst |
|---------------|------|---------|---------|
| Portfolio CRUD | ✅ | ✅ | ✅ |
| Portfolio health + concentration risk | ❌ | ✅ | ✅ |
| MF overlap, macro sensitivity, sentiment shift | ❌ | ✅ | ✅ |
| `portfolio_risk_report`, `what_if_analysis` | ❌ | ❌ | ✅ |
| Resource subscriptions on alerts | ❌ | ✅ | ✅ |
| Rate limit | 30/hr | 150/hr | 500/hr |

---

## Phase 5 — Cross-Source Tools (Analyst tier only)

- **`portfolio_risk_report`** — full cross-source analysis across the entire portfolio: current prices [NSE via yfinance], sector mapping [derived], macro indicators [RBI DBIE], news sentiment [NewsAPI/Finnhub], and MF overlap [MFapi]. Produces a structured risk report with per-source citations and explicit confirmation/contradiction flags.
- **`what_if_analysis`** — "What happens to my portfolio if RBI cuts rates 25bps?" Cross-references each holding's rate sensitivity with historical price reactions to past rate cut cycles. Combines macro data [RBI DBIE] + price history [yfinance] + sector classification.

---

## Phase 6 — MCP Resources, Subscriptions & Prompts

### Resources
- `portfolio://{user_id}/holdings` — user's current portfolio (persisted, auth-scoped)
- `portfolio://{user_id}/alerts` — active risk alerts
- `portfolio://{user_id}/risk_score` — overall risk score, updated on each health check
- `market://overview` — market summary (shared with PS1)
- `macro://snapshot` — latest macro indicators (shared with PS1)

### Resource Subscriptions *(key differentiator for PS2)*
Subscriptions allow MCP clients to receive push notifications when resources change.

- **`portfolio://{user_id}/alerts`** — notify client when a new risk signal fires (e.g. sentiment shift on a holding, concentration breach)
- **`market://overview`** — notify on significant market moves affecting portfolio holdings

**Implementation approach:** FastMCP supports SSE-based subscriptions. A background worker polls risk signals on a configurable interval and pushes to subscribed clients via the subscription manager built in Phase 2.

### Prompts
- `morning_risk_brief` — daily: portfolio value + overnight news per holding + new alerts + macro changes (Premium+)
- `rebalance_suggestions` — based on current risk flags, suggest trades to reduce concentration or sector tilt (Premium+)
- `earnings_exposure` — which holdings have upcoming earnings? what's the risk from each? (Premium+)

---

## Phase 7 — Docker Compose

One-command local deployment:

```
docker compose up
```

Services:
- `mcp-server` — FastMCP Python application (Streamable HTTP transport)
- `keycloak` — OAuth 2.1 auth server
- `redis` — cache + rate limit counters + subscription pub/sub
- `postgres` — persistent portfolio holdings and alert state
- `alert-worker` — background process polling risk signals and publishing to subscriptions

Deliverables:
- `docker-compose.yml`
- `.env.example` with all required API keys and sign-up links
- Health-check endpoint: upstream API status + remaining quotas
- `README.md` with setup instructions

---

## Build Order

```
Phase 1  →  Phase 2  →  Phase 3  →  Phase 4  →  Phase 5  →  Phase 6  →  Phase 7
  Auth     Core+DB+      API        18 Tools    2 Cross-    Resources    Docker
  Server   Alerts+Subs  Clients                  Source     Subscriptions Compose
                                                  Tools     & Prompts
```

---

## Key Differences vs PS1

| Concern | PS1 | PS2 |
|---------|-----|-----|
| State | Stateless (watchlist only) | Stateful — portfolio holdings + alert state in PostgreSQL |
| Subscriptions | Optional/bonus | Core requirement — alerts drive the product |
| Background work | None | Alert worker polling risk signals continuously |
| Data store | Redis only | Redis + PostgreSQL |
| Cross-source focus | Research synthesis | Risk aggregation across a live portfolio |
| Primary primitive | Tools | Resources + subscriptions |

---

## Scope Reference

| Scope | Grants Access To |
|-------|-----------------|
| `market:read` | Live quotes, price history, indices, movers |
| `fundamentals:read` | Financials, ratios, shareholding |
| `mf:read` | Mutual fund NAV, search, overlap checks |
| `news:read` | News articles |
| `news:sentiment` | Aggregated sentiment analysis |
| `macro:read` | RBI rates, inflation (current) |
| `macro:historical` | Full historical macro time series |
| `research:generate` | Cross-source risk tools |
| `portfolio:read` | View holdings, summary, risk score |
| `portfolio:write` | Add/remove holdings |
| `portfolio:alerts` | Subscribe to alert notifications |
