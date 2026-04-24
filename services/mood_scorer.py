"""
Phase 6 — Mood scoring.

Maps questionnaire vibe + listening_mode to Last.fm tag sets, then scores
each candidate by how well their artist's tags match the mood target.

Called after candidate generation and before ranking so the ranker can
treat mood_score as just another signal.
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from models.db_models import Artist, ArtistTag
from models.schemas import AlbumCandidate, QuestionnaireResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tag mappings
# Each entry is (positive_tags, negative_tags).
# Positive tags lift the score; negative tags drag it down.
# ---------------------------------------------------------------------------

_VIBE_TAGS: dict[str, tuple[list[str], list[str]]] = {
    "melancholy": (
        ["melancholic", "sad", "melancholy", "introspective", "dark", "emotional",
         "depressive", "heartbreak", "atmospheric", "dreamy", "ethereal", "slowcore",
         "shoegaze", "post-rock", "indie", "alternative"],
        ["happy", "upbeat", "energetic", "party", "dance", "fun", "uplifting",
         "hip hop", "rap", "grime", "uk hip hop", "trap", "drill", "r&b"],
    ),
    "energised": (
        ["energetic", "upbeat", "driving", "powerful", "intense", "aggressive",
         "electronic", "dance", "high energy", "fast", "anthemic",
         "hip hop", "rap", "grime", "uk hip hop", "trap", "drill", "punk", "metal"],
        ["ambient", "calm", "relaxing", "mellow", "acoustic", "slow", "quiet",
         "melancholic", "sad", "sleep", "folk"],
    ),
    "warm": (
        ["warm", "cozy", "soulful", "acoustic", "folk", "indie folk", "soft",
         "mellow", "gentle", "heartfelt", "intimate", "singer-songwriter",
         "soul", "jazz", "blues", "country"],
        ["aggressive", "harsh", "industrial", "noise", "abrasive", "dark",
         "hip hop", "rap", "grime", "trap", "drill", "metal", "punk"],
    ),
    "unsettled": (
        ["experimental", "dark", "avant-garde", "post-punk", "noise", "industrial",
         "complex", "challenging", "tense", "dissonant", "psychedelic", "art rock",
         "krautrock", "no wave", "free jazz", "drone"],
        ["happy", "upbeat", "easy listening", "pop", "fun", "mainstream", "dance"],
    ),
    "focused": (
        ["ambient", "instrumental", "electronic", "post-rock", "classical",
         "focus", "concentration", "background", "chill", "minimal", "drone",
         "jazz", "neoclassical", "modern classical"],
        ["party", "dance", "loud", "aggressive", "hip hop", "rap", "grime",
         "trap", "drill", "punk", "metal"],
    ),
}

# Genre weight axis — used for the "light & breezy ↔ heavy" slider.
# weight_score ≈ 0 = light genres, ≈ 1 = heavy genres, 0.5 = unknown/neutral.
_HEAVINESS_TAGS: tuple[list[str], list[str]] = (
    # heavy side
    ["rock", "metal", "heavy metal", "hard rock", "drum and bass", "dnb", "hardcore",
     "punk", "thrash metal", "doom metal", "noise rock", "industrial", "stoner rock",
     "grunge", "alternative rock", "post-punk", "noise", "shoegaze"],
    # light side
    ["acoustic", "ambient", "folk", "easy listening", "lo-fi", "soft",
     "classical", "chamber music", "piano", "singer-songwriter", "bossa nova",
     "new age", "chill"],
)

_LISTENING_MODE_TAGS: dict[str, tuple[list[str], list[str]]] = {
    "immersive": (
        ["progressive", "complex", "concept album", "epic", "art rock",
         "post-rock", "ambient", "psychedelic", "experimental", "cinematic"],
        ["background", "easy listening", "pop"],
    ),
    "background": (
        ["ambient", "easy listening", "chill", "instrumental", "soft",
         "lo-fi", "mellow", "acoustic"],
        ["aggressive", "complex", "progressive", "experimental", "harsh"],
    ),
    "energise": (
        ["energetic", "upbeat", "driving", "powerful", "dance",
         "electronic", "rock", "anthemic", "intense"],
        ["ambient", "calm", "slow", "mellow", "acoustic"],
    ),
    "unwind": (
        ["chill", "relaxing", "mellow", "acoustic", "soft", "calm",
         "lo-fi", "jazz", "folk", "sleep", "ambient"],
        ["energetic", "aggressive", "loud", "intense", "dance"],
    ),
}


def _score_tags(
    artist_tags: list[ArtistTag],
    positive: list[str],
    negative: list[str],
) -> float:
    """
    Score an artist's tags against a positive/negative tag set.
    Returns a value roughly in [-0.5, 1.0] — callers clamp to [0, 1].
    """
    if not artist_tags:
        return 0.5   # neutral — no tag data, don't penalise

    tag_map = {t.tag: t.weight for t in artist_tags}

    pos_score = sum(tag_map.get(tag, 0.0) for tag in positive)
    neg_score = sum(tag_map.get(tag, 0.0) for tag in negative)

    # Normalise by number of tags so dense tag profiles don't dominate
    n_pos = max(len(positive), 1)
    n_neg = max(len(negative), 1)

    return (pos_score / n_pos) - 0.5 * (neg_score / n_neg)


def fetch_tags(db: Session, candidates: list[AlbumCandidate]) -> dict:
    """
    Pre-fetch all artist tags needed for a candidate pool.
    Returns a dict: spotify_artist_id -> list[ArtistTag].
    Call this once and pass the result to score_candidates_with_tags.
    """
    artist_ids = list({c.artist_id for c in candidates if c.artist_id})
    if not artist_ids:
        return {}
    db_artists = db.query(Artist).filter(Artist.spotify_artist_id.in_(artist_ids)).all()
    return {a.spotify_artist_id: a.tags for a in db_artists if a.spotify_artist_id}


def score_candidates(
    db: Session,
    candidates: list[AlbumCandidate],
    q: QuestionnaireResponse,
) -> None:
    """Score candidates in-place, fetching tags from DB. Use for single requests."""
    tags = fetch_tags(db, candidates)
    score_candidates_with_tags(candidates, q, tags)


def score_candidates_with_tags(
    candidates: list[AlbumCandidate],
    q: QuestionnaireResponse,
    tags_by_artist: dict,
) -> None:
    """
    Compute vibe_score, mode_score, and combined mood_score for each candidate
    in-place using pre-fetched tags.
    Use this when scoring many questionnaire combinations to avoid repeated DB queries.
    """
    vibe = q.vibe
    mode = q.listening_mode

    vibe_pos, vibe_neg = _VIBE_TAGS.get(vibe, ([], []))
    mode_pos, mode_neg = _LISTENING_MODE_TAGS.get(mode, ([], []))

    for c in candidates:
        artist_tags = tags_by_artist.get(c.artist_id, [])

        if vibe:
            c.vibe_score = max(0.0, min(1.0, _score_tags(artist_tags, vibe_pos, vibe_neg) + 0.5))
        else:
            c.vibe_score = 0.5

        if mode:
            c.mode_score = max(0.0, min(1.0, _score_tags(artist_tags, mode_pos, mode_neg) + 0.5))
        else:
            c.mode_score = 0.5

        # Combined mood_score for display/explanation
        # Genre weight score (light ↔ heavy) — always computed
        heavy_pos, light_pos = _HEAVINESS_TAGS
        c.weight_score = max(0.0, min(1.0, _score_tags(artist_tags, heavy_pos, light_pos) + 0.5))

        # Combined mood_score for display/explanation
        if vibe and mode:
            c.mood_score = 0.6 * c.vibe_score + 0.4 * c.mode_score
        elif vibe:
            c.mood_score = c.vibe_score
        elif mode:
            c.mood_score = c.mode_score
        else:
            c.mood_score = 0.5

    logger.info("Mood scored %d candidates (vibe=%s, mode=%s)", len(candidates), vibe or "—", mode or "—")
