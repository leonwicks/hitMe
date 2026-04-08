"""
HTML page routes.

GET /           → home / login page
GET /dashboard  → user dashboard with latest recommendation
GET /history    → recommendation history
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from db import get_db
import repositories.users as user_repo
import repositories.recommendations as rec_repo
from api._templates import render

logger = logging.getLogger(__name__)

router = APIRouter()

_ERROR_MESSAGES = {
    "access_denied": "Spotify access was denied. Please try again.",
    "token_exchange": "Failed to exchange the authorisation code. Please try again.",
    "spotify_error": "An error occurred with Spotify. Please try again.",
    "no_token": "No access token received from Spotify.",
    "forbidden": (
        "Your Spotify account hasn't been approved yet. "
        "Fill out the form below to request access."
    ),
    "profile_error": "Could not fetch your Spotify profile. Please try again.",
    "no_user_id": "Spotify did not return a user ID.",
    "recommend_failed": "Could not generate a recommendation right now. Please try again.",
    "no_candidates": "We couldn't find enough album data from your Spotify account to make a recommendation.",
    "request_failed": "Could not send your access request. Please try again.",
}


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user_id = request.session.get("user_id")
    if user_id:
        return RedirectResponse("/dashboard")
    error_key = request.query_params.get("error")
    error_msg = _ERROR_MESSAGES.get(error_key) if error_key else None
    access_requested = request.query_params.get("access_requested") == "1"
    show_request_modal = error_key == "forbidden"
    return render(
        "index.html",
        error=error_msg,
        show_request_modal=show_request_modal,
        access_requested=access_requested,
    )


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/")

    user = user_repo.get_by_id(db, user_id)
    if not user:
        request.session.clear()
        return RedirectResponse("/")

    latest_rec = rec_repo.get_latest(db, user_id)
    error_key = request.query_params.get("error")
    error_msg = _ERROR_MESSAGES.get(error_key) if error_key else None

    return render(
        "dashboard.html",
        user=user,
        recommendation=latest_rec,
        error=error_msg,
    )


@router.get("/history", response_class=HTMLResponse)
async def history(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/")

    user = user_repo.get_by_id(db, user_id)
    if not user:
        request.session.clear()
        return RedirectResponse("/")

    recs = rec_repo.get_history(db, user_id)
    return render("history.html", user=user, recommendations=recs)
