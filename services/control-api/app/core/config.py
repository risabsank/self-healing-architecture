import os

from pydantic_settings import BaseSettings, SettingsConfigDict


def load_file_secrets() -> None:
    """Support Docker/Kubernetes-style *_FILE secrets without extra dependencies."""
    for key, path in list(os.environ.items()):
        if not key.endswith("_FILE"):
            continue
        target_key = key.removesuffix("_FILE")
        if target_key in os.environ:
            continue
        with open(path, encoding="utf-8") as secret_file:
            os.environ[target_key] = secret_file.read().strip()


class Settings(BaseSettings):
    database_url: str
    target_api_base_url: str = "http://target-api:8001"
    monitor_interval_seconds: int = 10
    run_monitor_in_api: bool = True
    default_sandbox_id: str = "local-docker"
    repair_repo_root: str = "/workspace"
    repair_approved_paths: str = "target-app/api/tests/,target-app/api/main.py,target-app/api/requirements.txt,infra/docker-compose.yml"
    auth_enabled: bool = False
    api_keys: str = ""
    log_level: str = "INFO"
    service_name: str = "self-healing-control-api"
    firecracker_api_url: str = ""
    firecracker_timeout_seconds: int = 10

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


load_file_secrets()
settings = Settings()
