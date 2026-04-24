"""
Taste profile builder.

Reads enriched artist data from the DB and computes weighted genre + tag
profiles for a user. Persists the result in user_taste_profiles.
Stale check: rebuild if older than 24 hours.
"""

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from models.db_models import Artist, ArtistTag, UserTasteProfile
from models.schemas import ListeningData

logger = logging.getLogger(__name__)

_PROFILE_TTL_HOURS = 24

# Time-range weights matching ranker affinity weights
_TERM_WEIGHTS = {
    "long":   1.00,
    "medium": 0.80,
    "short":  0.60,
}


def _is_stale(profile: UserTasteProfile) -> bool:
    return (datetime.utcnow() - profile.updated_at) >= timedelta(hours=_PROFILE_TTL_HOURS)


def get_or_build(db: Session, user_id: int, data: ListeningData) -> UserTasteProfile:
    """
    Return a fresh UserTasteProfile, rebuilding from DB if stale or missing.
    """
    existing = db.query(UserTasteProfile).filter(UserTasteProfile.user_id == user_id).first()
    if existing and not _is_stale(existing):
        return existing

    logger.info("Rebuilding taste profile for user_id=%s", user_id)
    profile = _build(db, user_id, data)

    if existing:
        existing.genre_weights = profile["genre_weights"]
        existing.tag_weights = profile["tag_weights"]
        existing.known_artist_ids = profile["known_artist_ids"]
        existing.updated_at = datetime.utcnow()
        db.commit()
        return existing
    else:
        row = UserTasteProfile(
            user_id=user_id,
            genre_weights=profile["genre_weights"],
            tag_weights=profile["tag_weights"],
            known_artist_ids=profile["known_artist_ids"],
            updated_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row


def _build(db: Session, user_id: int, data: ListeningData) -> dict:
    """Compute genre + tag weights from user's listening data + DB artist records."""

    # Build a weighted list of (spotify_artist_id, weight) across all time ranges
    artist_weights: dict[str, float] = {}

    term_lists = [
        (data.long_term_artists, "long"),
        (data.medium_term_artists, "medium"),
        (data.short_term_artists, "short"),
    ]
    for artist_list, term in term_lists:
        n = max(len(artist_list), 1)
        term_w = _TERM_WEIGHTS[term]
        for rank, a in enumerate(artist_list):
            rank_score = term_w * (1 - rank / n)
            artist_weights[a.artist_id] = artist_weights.get(a.artist_id, 0) + rank_score

    all_spotify_ids = list(artist_weights.keys())

    # Fetch matching DB artist records
    db_artists = (
        db.query(Artist)
        .filter(Artist.spotify_artist_id.in_(all_spotify_ids))
        .all()
    ) if all_spotify_ids else []

    id_to_artist = {a.spotify_artist_id: a for a in db_artists}

    genre_weights: dict[str, float] = {}
    tag_weights: dict[str, float] = {}

    for spotify_id, weight in artist_weights.items():
        artist = id_to_artist.get(spotify_id)
        if not artist:
            continue

        # Genres from Spotify
        for genre in (json.loads(artist.genres) if artist.genres else []):
            genre_weights[genre] = genre_weights.get(genre, 0) + weight

        # Tags from Last.fm
        for tag_row in artist.tags:
            tag_weights[tag_row.tag] = tag_weights.get(tag_row.tag, 0) + weight * tag_row.weight

    # Normalise both dicts to sum to 1
    def _normalise(d: dict) -> dict:
        total = sum(d.values())
        if not total:
            return d
        return {k: round(v / total, 5) for k, v in sorted(d.items(), key=lambda x: -x[1])[:50]}

    return {
        "genre_weights": json.dumps(_normalise(genre_weights)),
        "tag_weights": json.dumps(_normalise(tag_weights)),
        "known_artist_ids": json.dumps(all_spotify_ids),
    }
