"""
Recommendation route.

POST /recommend  → run the full pipeline and redirect to /dashboard
"""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from db import get_db
import repositories.recommendations as rec_repo
from services.spotify_client import get_valid_client, SpotifyAuthError
import services.spotify_fetcher as fetcher
import services.candidate_generator as candidate_gen
import services.ranker as ranker
import services.explainer as explainer

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/recommend")
async def recommend(request: Request, db: Session = Depends(get_db)):
    """
    Run the two-stage recommendation pipeline:
      1. Fetch live listening data from Spotify.
      2. Generate album candidates.
      3. Rank candidates.
      4. Explain top pick.
      5. Persist to recommendation history.
      6. Redirect to dashboard.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/", status_code=303)

    # --- Get a valid Spotify client (refreshes token if needed) ---
    try:
        client = await get_valid_client(db, user_id)
    except SpotifyAuthError:
        logger.warning("SpotifyAuthError for user_id=%s — clearing session", user_id)
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    # --- Fetch live data, generate candidates, rank ---
    try:
        async with client:
            listening_data = await fetcher.fetch_all(client)
    except SpotifyAuthError:
        request.session.clear()
        return RedirectResponse("/", status_code=303)
    except Exception as exc:
        logger.error("Spotify fetch failed for user_id=%s: %s", user_id, exc)
        return RedirectResponse("/dashboard?error=recommend_failed", status_code=303)

    candidates = candidate_gen.generate(listening_data)
    if not candidates:
        logger.warning("No candidates for user_id=%s", user_id)
        return RedirectResponse("/dashboard?error=no_candidates", status_code=303)

    history = rec_repo.get_recent(db, user_id, days=30)
    ranked = ranker.rank(candidates, listening_data, history)

    if not ranked:
        return RedirectResponse("/dashboard?error=no_candidates", status_code=303)

    top = ranked[0]
    explanation = explainer.explain(top, listening_data)

    # --- Persist ---
    rec_repo.create(db, user_id, top, explanation)

    return RedirectResponse("/dashboard", status_code=303)
