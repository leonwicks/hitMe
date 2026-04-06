"""Spotify HTTP client with automatic token refresh."""

import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from config import settings
from models.db_models import SpotifyAccount

logger = logging.getLogger(__name__)

SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"


class SpotifyAuthError(Exception):
    """Raised when authentication fails and cannot be recovered."""


class SpotifyClient:
    """
    Async HTTP client for the Spotify Web API.

    Wraps httpx.AsyncClient and injects the Bearer token on every call.
    Must be used as an async context manager so the underlying HTTP
    connection pool is properly opened and closed.
    """

    def __init__(self, access_token: str) -> None:
        self.access_token = access_token
        self._http: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "SpotifyClient":
        self._http = httpx.AsyncClient(timeout=15.0)
        return self

    async def __aexit__(self, *_) -> None:
        if self._http:
            await self._http.aclose()

    async def get(self, path: str, **params) -> dict:
        """GET /v1{path} with optional query parameters."""
        assert self._http is not None, "SpotifyClient must be used as an async context manager"
        filtered = {k: v for k, v in params.items() if v is not None}
        resp = await self._http.get(
            f"{SPOTIFY_API_BASE}{path}",
            params=filtered,
            headers={"Authorization": f"Bearer {self.access_token}"},
        )
        if resp.status_code == 401:
            raise SpotifyAuthError("Access token rejected (401).")
        if resp.status_code == 403:
            raise SpotifyAuthError("Access forbidden (403). Account may not be whitelisted.")
        resp.raise_for_status()
        return resp.json()


async def exchange_code(code: str) -> dict:
    """Exchange an OAuth authorization code for access + refresh tokens."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            SPOTIFY_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.spotify_redirect_uri,
            },
            auth=(settings.spotify_client_id, settings.spotify_client_secret),
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(refresh_token: str) -> dict:
    """Exchange a refresh token for a new access token."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            SPOTIFY_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            auth=(settings.spotify_client_id, settings.spotify_client_secret),
        )
        resp.raise_for_status()
        return resp.json()


async def get_valid_client(db: Session, user_id: int) -> SpotifyClient:
    """
    Return a SpotifyClient with a valid (non-expired) access token.

    Refreshes the token in the database if it has expired.
    Raises SpotifyAuthError if no account is found or refresh fails.
    """
    account: Optional[SpotifyAccount] = (
        db.query(SpotifyAccount).filter(SpotifyAccount.user_id == user_id).first()
    )
    if not account:
        raise SpotifyAuthError("No Spotify account linked for this user.")

    needs_refresh = account.expires_at and datetime.utcnow() >= account.expires_at
    if needs_refresh:
        if not account.refresh_token:
            raise SpotifyAuthError("Token expired and no refresh token available.")
        logger.info("Refreshing Spotify token for user_id=%s", user_id)
        try:
            new_tokens = await refresh_access_token(account.refresh_token)
        except httpx.HTTPError as exc:
            raise SpotifyAuthError(f"Token refresh HTTP error: {exc}") from exc

        account.access_token = new_tokens["access_token"]
        account.expires_at = datetime.utcnow() + timedelta(seconds=new_tokens.get("expires_in", 3600))
        db.commit()

    return SpotifyClient(account.access_token)
