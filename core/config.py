from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str

    # Redis
    redis_url: str

    # Nebius Token Factory — NVIDIA open-weight models
    nebius_api_key: str = ""
    nebius_base_url: str
    nano_model_id: str
    ultra_model_id: str

    # Nebius Object Storage — S3-compatible, uses boto3 pointed at Nebius endpoint
    object_storage_bucket: str
    object_storage_endpoint: str = ""
    nebius_storage_access_key_id: str = ""
    nebius_storage_secret_key: str = ""

    # Tavily
    tavily_api_key: str = ""

    # Demo
    demo_api_key: str

    # Stream Processor tuning
    error_spike_threshold: int = 10
    error_spike_window_seconds: int = 60
    stream_discovery_interval_seconds: int = 30
    trigger_debounce_seconds: int = 120

    # Stage-1 / Stage-2 tuning
    time_window_seconds: int = 30
    nano_batch_size: int = 20
    nano_parallel_calls: int = 10
    qa_max_turns: int = 20

    # Ingest
    ingest_max_events_per_call: int = 500
    ingest_stream_maxlen: int = 50_000

    # Upload limits
    upload_max_files: int = 50
    upload_max_file_mb: int = 50
    upload_max_total_mb: int = 200


@lru_cache
def get_settings() -> Settings:
    return Settings()
