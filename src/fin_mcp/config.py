from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    keycloak_url: str = "http://localhost:8080"
    keycloak_realm: str = "fin-mcp"
    resource_server_client_id: str = "mcp-resource-server"
    mcp_server_url: str = "http://localhost:3000"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 3000
    log_level: str = "INFO"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Rate limit: max calls per hour per tier
    rate_limit_free: int = 30
    rate_limit_premium: int = 150
    rate_limit_analyst: int = 500

    # Upstream API keys
    alpha_vantage_api_key: str = ""
    finnhub_api_key: str = ""
    newsapi_api_key: str = ""

    @property
    def jwks_url(self) -> str:
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}/protocol/openid-connect/certs"

    @property
    def issuer(self) -> str:
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"


settings = Settings()
