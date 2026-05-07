from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    target_api_base_url: str = "http://target-api:8001"
    monitor_interval_seconds: int = 10
    default_sandbox_id: str = "local-docker"
    repair_repo_root: str = "/workspace"
    repair_approved_paths: str = "target-app/api/tests/,target-app/api/main.py,target-app/api/requirements.txt,infra/docker-compose.yml"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
