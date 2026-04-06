"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str = "http://localhost:8000/auth/callback"
    secret_key: str = "change-me-in-production"
    database_url: str = "sqlite:///./hitme.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
