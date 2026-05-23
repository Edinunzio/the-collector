from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://collector:collector@localhost:5432/collector"
    redis_url: str = "redis://localhost:6379/0"

    db_pool_min_size: int = 2
    db_pool_max_size: int = 10

    crawl_workers: int = 5
    crawl_delay_seconds: float = 2.0
    crawl_depth_max: int = 3
    crawl_domain_page_cap: int = 500

    signal_threshold: int = 3

    response_size_limit_bytes: int = 5 * 1024 * 1024  # 5MB
    chardet_confidence_threshold: float = 0.7
    httpx_connect_timeout: float = 10.0
    httpx_read_timeout: float = 30.0
    page_process_timeout: float = 30.0


settings = Settings()
