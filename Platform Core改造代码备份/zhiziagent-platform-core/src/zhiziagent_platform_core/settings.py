from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ZAP_", extra="ignore")

    app_name: str = "ZhiziAgent Platform Core"
    app_env: str = "development"
    database_url: str = "sqlite:///./zhiziagent_platform_core.db"
    jwt_secret: str = Field(default="dev-only-change-me")
    jwt_expires_minutes: int = 60 * 24 * 7
    cors_origins: str = "*"
    auto_create_schema: bool = True
    agentctl_base_url: str = "http://agentctl:8765"
    agentctl_admin_token: str = ""
    agentctl_timeout_seconds: int = 30
    parsecore_base_url: str = "http://parsecore-api:8090"
    parsecore_api_key: str = ""
    parsecore_timeout_seconds: int = 60
    studio_app_proxy_base_url: str = "http://zhiziagent-studio"
    studio_app_proxy_timeout_seconds: int = 10
    studio_auto_provision_agentctl_connection: bool = True
    bootstrap_admin_token: str = ""
    payment_gateway_webhook_secrets: str = ""
    payment_gateway_webhook_tolerance_seconds: int = 300
    stripe_webhook_secret: str = ""
    platform_tool_context_secret: str = ""
    platform_tool_context_ttl_seconds: int = 600
    toolkit_artifact_inline_max_bytes: int = 25 * 1024 * 1024

    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
