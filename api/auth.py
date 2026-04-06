"""
Spotify OAuth routes.

GET  /login           → redirect user to Spotify auth page
GET  /auth/callback   → exchange code for tokens, upsert user, set session
GET  /logout          → clear session
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from config import settings
from db import get_db
import repositories.users as user_repo
from services.spotify_client import exchange_code

logger = logging.getLogger(__name__)

router = APIRouter()

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_API_ME = "https://api.spotify.com/v1/me"

SCOPES = " ".join([
    "user-top-read",
    "user-library-read",
    "user-read-recently-played",
])


@router.get("/login")
async def login():
    """Redirect the user to the Spotify authorization page."""
    params = {
        "client_id": settings.spotify_client_id,
        "response_type": "code",
        "redirect_uri": settings.spotify_redirect_uri,
        "scope": SCOPES,
        "show_dialog": "false",
    }
    return RedirectResponse(f"{SPOTIFY_AUTH_URL}?{urlencode(params)}")


@router.get("/auth/spotify/callback")
async def auth_callback(
    request: Request,
    code: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Handle the OAuth callback from Spotify."""
    if error or not code:
        logger.warning("Spotify auth error: %s", error)
        return RedirectResponse("/?error=access_denied")

    # Exchange code for tokens
    try:
        token_data = await exchange_code(code)
    except httpx.HTTPStatusError as exc:
        logger.error("Token exchange failed: %s", exc)
        if exc.response.status_code == 400:
            return RedirectResponse("/?error=token_exchange")
        return RedirectResponse("/?error=spotify_error")

    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)
    scopes = token_data.get("scope", "")

    if not access_token:
        return RedirectResponse("/?error=no_token")

    # Fetch the user's Spotify profile
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            profile_resp = await client.get(
                SPOTIFY_API_ME,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if profile_resp.status_code == 403:
                return RedirectResponse("/?error=forbidden")
            profile_resp.raise_for_status()
            profile = profile_resp.json()
    except httpx.HTTPError as exc:
        logger.error("Profile fetch failed: %s", exc)
        return RedirectResponse("/?error=profile_error")

    spotify_user_id = profile.get("id")
    display_name = profile.get("display_name") or profile.get("id", "Spotify User")

    if not spotify_user_id:
        return RedirectResponse("/?error=no_user_id")

    # Upsert user + account in the database
    user = user_repo.upsert(db, spotify_user_id, display_name)
    user_repo.upsert_spotify_account(
        db,
        user_id=user.id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=datetime.utcnow() + timedelta(seconds=expires_in),
        scopes=scopes,
    )
    db.commit()

    request.session["user_id"] = user.id
    logger.info("User %s (%s) logged in.", display_name, spotify_user_id)
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    """Clear the session and redirect to the home page."""
    request.session.clear()
    return RedirectResponse("/")
