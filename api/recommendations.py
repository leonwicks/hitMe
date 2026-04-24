"""
Recommendation route.

POST /recommend  → run the full pipeline and redirect to /dashboard
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from db import get_db
from models.schemas import QuestionnaireResponse
import repositories.recommendations as rec_repo
from services.spotify_client import get_valid_client, SpotifyAuthError
import services.spotify_sync as spotify_sync
import services.candidate_generator as candidate_gen
import services.ranker as ranker
import services.explainer as explainer
import services.enrichment_coordinator as enrichment
import services.discovery_generator as discovery_gen
import services.mood_scorer as mood_scorer

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/recommend")
async def recommend(
    request: Request,
    db: Session = Depends(get_db),
    vibe: Optional[str] = Form(""),
    listening_mode: Optional[str] = Form(""),
    familiarity: Optional[str] = Form("balanced"),
    nostalgia: Optional[int] = Form(0),
    heaviness: Optional[int] = Form(5),
):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/", status_code=303)

    try:
        client = await get_valid_client(db, user_id)
    except SpotifyAuthError:
        logger.warning("SpotifyAuthError for user_id=%s — clearing session", user_id)
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    # --- Fetch / load listening data (syncs from Spotify if stale) ---
    try:
        listening_data = await spotify_sync.get_listening_data(db, user_id, client)
    except SpotifyAuthError:
        request.session.clear()
        return RedirectResponse("/", status_code=303)
    except Exception as exc:
        logger.error("Spotify sync failed for user_id=%s: %s", user_id, exc)
        return RedirectResponse("/dashboard?error=recommend_failed", status_code=303)

    # --- Enrichment + taste profile (no-op when fresh) ---
    try:
        client = await get_valid_client(db, user_id)
        taste_profile = await enrichment.ensure_fresh(db, user_id, client, listening_data)
    except Exception as exc:
        logger.warning("Enrichment failed — proceeding without discovery: %s", exc)
        taste_profile = None

    # --- Build candidate pool ---
    candidates = candidate_gen.generate(listening_data)

    # Append discovery candidates if the taste profile is available
    if taste_profile is not None:
        try:
            client = await get_valid_client(db, user_id)
            async with client:
                discovery_candidates = await discovery_gen.fetch_discovery_album_candidates(
                    db, client, taste_profile
                )
            candidates.extend(discovery_candidates)
            logger.info("Added %d discovery candidates", len(discovery_candidates))
        except Exception as exc:
            logger.warning("Discovery generation failed: %s", exc)

    if not candidates:
        logger.warning("No candidates for user_id=%s", user_id)
        return RedirectResponse("/dashboard?error=no_candidates", status_code=303)

    # --- Build questionnaire ---
    _valid_vibe = {"melancholy", "energised", "warm", "unsettled", "focused"}
    _valid_mode = {"immersive", "background", "energise", "unwind"}
    _valid_familiarity = {"familiar", "rediscovery", "new", "balanced"}
    q = QuestionnaireResponse(
        vibe=vibe if vibe in _valid_vibe else "",
        listening_mode=listening_mode if listening_mode in _valid_mode else "",
        familiarity=familiarity if familiarity in _valid_familiarity else "balanced",
        nostalgia=max(0, min(5, nostalgia or 0)),
        heaviness=max(0, min(10, heaviness or 5)),
    )

    # --- Mood scoring (annotates candidates in-place before ranking) ---
    mood_scorer.score_candidates(db, candidates, q)

    # --- Rank ---
    history = rec_repo.get_recent(db, user_id, days=30)
    ranked = ranker.rank(candidates, listening_data, history, questionnaire=q)

    if not ranked:
        return RedirectResponse("/dashboard?error=no_candidates", status_code=303)

    top = ranked[0]
    explanation = explainer.explain(top, questionnaire=q)

    rec_repo.create(db, user_id, top, explanation)
    return RedirectResponse("/dashboard", status_code=303)
