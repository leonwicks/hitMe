"""
HTML page routes.

GET /           → home / login page
GET /dashboard  → user dashboard with latest recommendation
GET /history    → recommendation history
"""

from __future__ import annotations

import logging

import copy
import itertools

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from db import get_db
import repositories.users as user_repo
import repositories.recommendations as rec_repo
from models.schemas import QuestionnaireResponse
import services.spotify_sync as spotify_sync
import services.candidate_generator as candidate_gen
import services.mood_scorer as mood_scorer
import services.ranker as ranker
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
    "no_candidates": (
        "We couldn't find enough album data from your Spotify account to make a recommendation."
    ),
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


@router.get("/debug/algorithm", response_class=HTMLResponse)
async def debug_algorithm(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/")

    user = user_repo.get_by_id(db, user_id)
    if not user:
        request.session.clear()
        return RedirectResponse("/")

    # Load all listening data from DB — no API calls
    listening_data = spotify_sync.load_from_db(db, user_id)
    base_candidates = candidate_gen.generate(listening_data)

    if not base_candidates:
        return render(
            "debug_algorithm.html", user=user, rows=[],
            error="No candidate data in DB. Make one recommendation first to populate the database.",
        )

    # Pre-fetch all artist tags once for the whole candidate pool
    tags_by_artist = mood_scorer.fetch_tags(db, base_candidates)

    # Load history for cooldown checks (omit if ignore_history flag set)
    ignore_history = request.query_params.get("ignore_history") == "1"
    rec_history = [] if ignore_history else rec_repo.get_recent(db, user_id, days=30)

    VIBES        = ["melancholy", "energised", "warm", "unsettled", "focused"]
    MODES        = ["immersive", "background", "unwind"]
    FAMILIARITIES = ["familiar", "rediscovery", "new", "balanced"]
    NOSTALGIAS   = [0, 1, 2, 4, 5]

    ERA_LABELS = {
        0: "Any",
        1: "Right now (2015+)",
        2: "Recent past (2005–14)",
        4: "Pre-internet (1980–95)",
        5: "Way back (pre-1980)",
    }

    rows = []
    combos = itertools.product(VIBES, MODES, FAMILIARITIES, NOSTALGIAS)
    for vibe, mode, familiarity, nostalgia in combos:
        q = QuestionnaireResponse(
            vibe=vibe, listening_mode=mode,
            familiarity=familiarity, nostalgia=nostalgia,
        )

        # Deep copy so ranker modifications don't bleed between combinations
        candidates = copy.deepcopy(base_candidates)

        # Score mood using pre-fetched tags
        mood_scorer.score_candidates_with_tags(candidates, q, tags_by_artist)

        ranked = ranker.rank(candidates, listening_data, rec_history, questionnaire=q)

        top3 = [
            {
                "album":       c.album_name,
                "artist":      c.artist_name,
                "bucket":      c.bucket,
                "score":       c.album_score,
                "release":     c.release_date[:4] if c.release_date else "?",
                "vibe_score":  c.vibe_score,
                "mode_score":  c.mode_score,
                "weight_score": c.weight_score,
            }
            for c in ranked[:3]
        ]

        rows.append({
            "vibe": vibe,
            "mode": mode,
            "familiarity": familiarity,
            "nostalgia": nostalgia,
            "era_label": ERA_LABELS[nostalgia],
            "top3": top3,
        })

    return render("debug_algorithm.html", user=user, rows=rows, error=None,
                  vibes=VIBES, modes=MODES, familiarities=FAMILIARITIES,
                  nostalgias=NOSTALGIAS, era_labels=ERA_LABELS,
                  ignore_history=ignore_history)


@router.get("/questionnaire", response_class=HTMLResponse)
async def questionnaire(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/")
    user = user_repo.get_by_id(db, user_id)
    if not user:
        request.session.clear()
        return RedirectResponse("/")
    return render("questionnaire.html", user=user)


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
