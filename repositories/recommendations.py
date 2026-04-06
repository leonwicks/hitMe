"""Recommendation history repository functions."""

import json
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session

from models.db_models import RecommendationHistory
from models.schemas import AlbumCandidate, Explanation


def create(
    db: Session,
    user_id: int,
    candidate: AlbumCandidate,
    explanation: Explanation,
) -> RecommendationHistory:
    """Persist a new recommendation."""
    rec = RecommendationHistory(
        user_id=user_id,
        recommendation_date=datetime.utcnow(),
        spotify_album_id=candidate.album_id,
        album_name=candidate.album_name,
        artist_name=candidate.artist_name,
        spotify_artist_id=candidate.artist_id,
        image_url=candidate.image_url,
        spotify_url=candidate.spotify_url,
        release_date=candidate.release_date,
        bucket=candidate.bucket,
        score=round(candidate.album_score, 4),
        explanation_summary=explanation.summary,
        explanation_bullets=json.dumps(explanation.bullets),
        score_breakdown=json.dumps(candidate.score_breakdown),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def get_latest(db: Session, user_id: int) -> Optional[RecommendationHistory]:
    return (
        db.query(RecommendationHistory)
        .filter(RecommendationHistory.user_id == user_id)
        .order_by(RecommendationHistory.recommendation_date.desc())
        .first()
    )


def get_recent(db: Session, user_id: int, days: int = 30) -> list[RecommendationHistory]:
    """Return recommendations within the last `days` days — used for cooldown checks."""
    since = datetime.utcnow() - timedelta(days=days)
    return (
        db.query(RecommendationHistory)
        .filter(
            RecommendationHistory.user_id == user_id,
            RecommendationHistory.recommendation_date >= since,
        )
        .order_by(RecommendationHistory.recommendation_date.desc())
        .all()
    )


def get_history(db: Session, user_id: int, limit: int = 50) -> list[RecommendationHistory]:
    """Return full recommendation history for the history page."""
    return (
        db.query(RecommendationHistory)
        .filter(RecommendationHistory.user_id == user_id)
        .order_by(RecommendationHistory.recommendation_date.desc())
        .limit(limit)
        .all()
    )
