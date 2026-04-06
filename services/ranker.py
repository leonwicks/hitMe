"""
Stage 2 — Ranking.

Scores each candidate using artist affinity + album-level signals,
applies cooldown penalties from recommendation history, and assigns
a discovery bucket (comfort / adjacent / rediscovery).
"""

import logging
from datetime import datetime, timedelta

from models.db_models import RecommendationHistory
from models.schemas import AlbumCandidate, ListeningData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------
W_ARTIST_AFFINITY = 0.35
W_TOP_TRACK = 0.30
W_SAVED_TRACK = 0.20
W_RECENT_PLAY = 0.20
W_SAVED_ALBUM_BONUS = 0.10
W_OVERFAMILIARITY = 0.35

# Artist affinity component weights
W_LONG_TERM = 1.00
W_MEDIUM_TERM = 0.80
W_SHORT_TERM = 0.60
W_RECENT_PLAYS = 0.50
W_SAVED_TRACKS = 0.50
W_SAVED_ALBUM_ARTIST = 0.70

MAX_ARTIST_AFFINITY = W_LONG_TERM + W_MEDIUM_TERM + W_SHORT_TERM + W_RECENT_PLAYS + W_SAVED_TRACKS + W_SAVED_ALBUM_ARTIST

# Cooldown
SAME_ALBUM_DAYS = 30
SAME_ARTIST_PENALTY = 0.20
SAME_ARTIST_DAYS = 7


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_artist_affinity(
    artist_id: str,
    data: ListeningData,
) -> tuple[float, str]:
    """
    Return (raw_affinity_score, best_term_label).

    best_term_label is "long" | "medium" | "short" | "" — used by explainer.
    """
    score = 0.0
    best_term = ""

    lt_ids = {a.artist_id: (i + 1) for i, a in enumerate(data.long_term_artists)}
    mt_ids = {a.artist_id: (i + 1) for i, a in enumerate(data.medium_term_artists)}
    st_ids = {a.artist_id: (i + 1) for i, a in enumerate(data.short_term_artists)}

    n = max(len(data.long_term_artists), 1)

    if artist_id in lt_ids:
        rank = lt_ids[artist_id]
        score += W_LONG_TERM * (1 - (rank - 1) / n)
        best_term = "long"

    if artist_id in mt_ids:
        rank = mt_ids[artist_id]
        score += W_MEDIUM_TERM * (1 - (rank - 1) / n)
        if not best_term:
            best_term = "medium"

    if artist_id in st_ids:
        rank = st_ids[artist_id]
        score += W_SHORT_TERM * (1 - (rank - 1) / n)
        if not best_term:
            best_term = "short"

    # Recent plays for this artist
    artist_recent_counts: dict[str, int] = {}
    for t in data.recently_played:
        artist_recent_counts[t.artist_id] = artist_recent_counts.get(t.artist_id, 0) + 1
    max_recent = max(artist_recent_counts.values(), default=1)
    recent_count = artist_recent_counts.get(artist_id, 0)
    score += W_RECENT_PLAYS * (recent_count / max_recent)

    # Saved tracks for this artist
    artist_saved_counts: dict[str, int] = {}
    for t in data.saved_tracks:
        artist_saved_counts[t.artist_id] = artist_saved_counts.get(t.artist_id, 0) + 1
    max_saved = max(artist_saved_counts.values(), default=1)
    saved_count = artist_saved_counts.get(artist_id, 0)
    score += W_SAVED_TRACKS * (saved_count / max_saved)

    # Saved album signal for artist
    saved_album_artist_ids = {a.artist_id for a in data.saved_albums}
    if artist_id in saved_album_artist_ids:
        score += W_SAVED_ALBUM_ARTIST

    return score, best_term


def _normalize(values: list[float]) -> list[float]:
    """Min-max normalize a list to [0, 1]."""
    if not values:
        return values
    mn, mx = min(values), max(values)
    if mx == mn:
        return [0.5] * len(values)
    return [(v - mn) / (mx - mn) for v in values]


def _assign_bucket(candidate: AlbumCandidate) -> str:
    if candidate.is_saved_album:
        return "comfort" if candidate.recent_play_count >= 2 else "rediscovery"
    return "adjacent"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def rank(
    candidates: list[AlbumCandidate],
    data: ListeningData,
    history: list[RecommendationHistory],
) -> list[AlbumCandidate]:
    """
    Score, filter, and sort candidates.

    1. Apply hard exclusion for albums recommended within the last 30 days.
    2. Compute artist affinity and normalised album signals.
    3. Apply overfamiliarity penalty.
    4. Apply soft same-artist penalty (7-day cooldown).
    5. Sort descending by final score.
    6. Assign discovery bucket.
    """
    if not candidates:
        return []

    # --- Hard exclusions ---
    recently_recommended_album_ids = {
        rec.spotify_album_id
        for rec in history
        if (datetime.utcnow() - rec.recommendation_date).days < SAME_ALBUM_DAYS
    }
    # Recently recommended artists (for soft penalty)
    recent_artist_ids = {
        rec.spotify_artist_id
        for rec in history
        if rec.spotify_artist_id
        and (datetime.utcnow() - rec.recommendation_date).days < SAME_ARTIST_DAYS
    }

    active = [c for c in candidates if c.album_id not in recently_recommended_album_ids]
    if not active:
        # All candidates are on cooldown — release the oldest ones (remove hard block)
        logger.info("All candidates on cooldown — relaxing exclusions.")
        active = candidates

    # --- Compute raw artist affinities ---
    for c in active:
        c.artist_affinity, c.top_term_artist = _compute_artist_affinity(c.artist_id, data)

    # --- Normalise counts across all active candidates ---
    top_track_counts = [c.top_track_count for c in active]
    saved_track_counts = [c.saved_track_count for c in active]
    recent_play_counts = [c.recent_play_count for c in active]
    affinity_scores = [c.artist_affinity for c in active]

    norm_top = _normalize(top_track_counts)
    norm_saved = _normalize(saved_track_counts)
    norm_recent = _normalize(recent_play_counts)
    norm_affinity = _normalize(affinity_scores)

    for i, c in enumerate(active):
        a_norm = norm_affinity[i]
        tt_norm = norm_top[i]
        st_norm = norm_saved[i]
        rp_norm = norm_recent[i]
        saved_bonus = 1.0 if c.is_saved_album else 0.0

        # Overfamiliarity: penalise if saved AND heavily represented in both
        # top tracks and recent plays
        over = 0.0
        if c.is_saved_album:
            over = max(0.0, (tt_norm + rp_norm - 0.8))   # kicks in above combined 0.8

        # Base score
        score = (
            W_ARTIST_AFFINITY * a_norm
            + W_TOP_TRACK * tt_norm
            + W_SAVED_TRACK * st_norm
            + W_RECENT_PLAY * rp_norm
            + W_SAVED_ALBUM_BONUS * saved_bonus
            - W_OVERFAMILIARITY * over
        )

        # Soft artist cooldown penalty
        if c.artist_id in recent_artist_ids:
            score -= SAME_ARTIST_PENALTY

        c.album_score = round(score, 4)
        c.score_breakdown = {
            "artist_affinity": round(a_norm, 3),
            "top_track_overlap": round(tt_norm, 3),
            "saved_track_overlap": round(st_norm, 3),
            "recent_play_overlap": round(rp_norm, 3),
            "saved_album_bonus": round(saved_bonus, 3),
            "overfamiliarity_penalty": round(over, 3),
        }
        c.bucket = _assign_bucket(c)

    active.sort(key=lambda c: c.album_score, reverse=True)

    logger.info(
        "Top 3 candidates: %s",
        [(c.album_name, c.artist_name, c.album_score) for c in active[:3]],
    )
    return active
