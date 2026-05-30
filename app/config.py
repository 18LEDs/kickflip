from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Datadog
    dd_api_key: str = ""
    dd_app_key: str = ""
    dd_site: str = "datadoghq.com"
    # Comma-separated pipeline IDs that contain the debug drop filter
    dd_pipeline_ids: str = ""
    # The processor ID (within each pipeline) that holds the debug drop filter
    dd_filter_processor_id: str = "drop-debug"

    # ServiceNow
    sn_instance: str = ""       # e.g. mycompany.service-now.com
    sn_user: str = ""
    sn_pass: str = ""
    # Minimum severity to accept: 1=SEV1, 2=SEV2
    sn_min_severity: int = 2

    # App behaviour
    grant_duration_seconds: int = 600   # 10 minutes
    database_url: str = "sqlite+aiosqlite:///./grants.db"

    @property
    def pipeline_id_list(self) -> list[str]:
        return [p.strip() for p in self.dd_pipeline_ids.split(",") if p.strip()]

    @property
    def dd_base_url(self) -> str:
        return f"https://api.{self.dd_site}"


settings = Settings()
