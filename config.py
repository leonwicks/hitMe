"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str = "http://localhost:8000/auth/callback"
    secret_key: str = "change-me-in-production"
    database_url: str = "sqlite:///./hitme.db"

    # Email notifications (for access requests)
    notification_email: str = ""   # your personal email — receives access requests
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""            # Gmail address used to send
    smtp_password: str = ""        # Gmail app password (not account password)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
