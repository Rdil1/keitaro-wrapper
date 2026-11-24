from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    keitaro_url: str = "https://keitaro-for-tests.etolegko.com"
    keitaro_api_key: str = ""
    keitaro_timeout: float = 15.0

    database_url: str = "sqlite:///./app.db"

    campaign_prefix: str = "test_ivanov_"
    default_domain_id: int | None = 1813
    default_group_id: int | None = 10332
    default_traffic_source_id: int | None = 836
    geo_redirect_url: str = "https://google.com"

    @property
    def api_base(self) -> str:
        return self.keitaro_url.rstrip("/") + "/admin_api/v1"

    def admin_campaign_url(self, campaign_id: int) -> str:
        return f"{self.keitaro_url.rstrip('/')}/admin/#!/campaign.editor/{campaign_id}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
