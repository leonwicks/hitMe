"""
Stage 2 — Ranking.

Scores each candidate using artist affinity + album-level signals,
applies cooldown penalties from recommendation history, and assigns
a discovery bucket (comfort / adjacent / rediscovery / discovery).
"""

import logging
from datetime import datetime

from models.db_models import RecommendationHistory
from models.schemas import AlbumCandidate, ListeningData, QuestionnaireResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Weights — known-artist scoring
# ---------------------------------------------------------------------------
W_ARTIST_AFFINITY   = 0.35
W_TOP_TRACK         = 0.30
W_SAVED_TRACK       = 0.20
W_RECENT_PLAY       = 0.20
W_SAVED_ALBUM_BONUS = 0.10
W_OVERFAMILIARITY   = 0.35

# Artist affinity component weights
W_LONG_TERM        = 1.00
W_MEDIUM_TERM      = 0.80
W_SHORT_TERM       = 0.60
W_RECENT_PLAYS     = 0.50
W_SAVED_TRACKS     = 0.50
W_SAVED_ALBUM_ARTIST = 0.70

# Cooldown
SAME_ALBUM_DAYS  = 30
SAME_ARTIST_DAYS = 7

# Year filters for nostalgia — must match questionnaire labels exactly.
# Ranges are exclusive on max (e.g. 2005 ≤ year < 2015 for "Recent past").
_NOSTALGIA_YEAR_FILTER: dict[int, tuple] = {
    1: (2015, None),    # Right now: 2015+
    2: (2005, 2015),    # Recent past: 2005–2014
    4: (1980, 1996),    # Before the internet: 1980–1995
    5: (None, 1980),    # Way back: pre-1980
}
_MAX_ALBUM_AGE_YEARS = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_artist_affinity(artist_id: str, data: ListeningData) -> tuple[float, str]:
    score = 0.0
    best_term = ""
    n = max(len(data.long_term_artists), 1)

    lt_ids = {a.artist_id: i + 1 for i, a in enumerate(data.long_term_artists)}
    mt_ids = {a.artist_id: i + 1 for i, a in enumerate(data.medium_term_artists)}
    st_ids = {a.artist_id: i + 1 for i, a in enumerate(data.short_term_artists)}

    if artist_id in lt_ids:
        score += W_LONG_TERM * (1 - (lt_ids[artist_id] - 1) / n)
        best_term = "long"
    if artist_id in mt_ids:
        score += W_MEDIUM_TERM * (1 - (mt_ids[artist_id] - 1) / n)
        best_term = best_term or "medium"
    if artist_id in st_ids:
        score += W_SHORT_TERM * (1 - (st_ids[artist_id] - 1) / n)
        best_term = best_term or "short"

    recent_counts: dict[str, int] = {}
    for t in data.recently_played:
        recent_counts[t.artist_id] = recent_counts.get(t.artist_id, 0) + 1
    max_recent = max(recent_counts.values(), default=1)
    score += W_RECENT_PLAYS * (recent_counts.get(artist_id, 0) / max_recent)

    saved_counts: dict[str, int] = {}
    for t in data.saved_tracks:
        saved_counts[t.artist_id] = saved_counts.get(t.artist_id, 0) + 1
    max_saved = max(saved_counts.values(), default=1)
    score += W_SAVED_TRACKS * (saved_counts.get(artist_id, 0) / max_saved)

    if artist_id in {a.artist_id for a in data.saved_albums}:
        score += W_SAVED_ALBUM_ARTIST

    return score, best_term


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return values
    mn, mx = min(values), max(values)
    if mx == mn:
        return [0.5] * len(values)
    return [(v - mn) / (mx - mn) for v in values]


def _assign_bucket(c: AlbumCandidate) -> str:
    if c.source == "discovery":
        return "discovery"
    if c.is_saved_album:
        return "comfort" if c.recent_play_count >= 2 else "rediscovery"
    return "adjacent"


def _release_year(c: AlbumCandidate) -> int:
    try:
        return int(c.release_date[:4])
    except (ValueError, TypeError, IndexError):
        return datetime.utcnow().year - 15


def _nostalgia_score(c: AlbumCandidate, nostalgia: int) -> float:
    age = max(0, datetime.utcnow().year - _release_year(c))
    age_norm = min(age / _MAX_ALBUM_AGE_YEARS, 1.0)
    target = (nostalgia - 1) / 4   # 1→0.0, 5→1.0
    return 1.0 - abs(age_norm - target)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def rank(
    candidates: list[AlbumCandidate],
    data: ListeningData,
    history: list[RecommendationHistory],
    questionnaire: "QuestionnaireResponse | None" = None,
) -> list[AlbumCandidate]:
    if not candidates:
        return []

    # --- Hard exclusions ---
    recently_recommended_album_ids = {
        rec.spotify_album_id for rec in history
        if (datetime.utcnow() - rec.recommendation_date).days < SAME_ALBUM_DAYS
    }
    recently_recommended_artist_ids = {
        rec.spotify_artist_id for rec in history
        if rec.spotify_artist_id
        and (datetime.utcnow() - rec.recommendation_date).days < SAME_ARTIST_DAYS
    }

    active = [
        c for c in candidates
        if c.album_id not in recently_recommended_album_ids
        and c.artist_id not in recently_recommended_artist_ids
    ]
    if not active:
        active = [c for c in candidates if c.album_id not in recently_recommended_album_ids]
    if not active:
        logger.info("All candidates on cooldown — relaxing all exclusions.")
        active = list(candidates)

    # --- Assign buckets early (needed for familiarity filter) ---
    for c in active:
        c.bucket = _assign_bucket(c)

    # --- Pre-filters ---
    if questionnaire is not None:
        familiarity = questionnaire.familiarity

        if familiarity == "new":
            # Include genuine discovery candidates + zero-signal known albums
            filtered = [
                c for c in active
                if c.source == "discovery"
                or (
                    not c.is_saved_album
                    and c.top_track_count == 0
                    and c.saved_track_count == 0
                    and c.recent_play_count == 0
                )
            ]
        elif familiarity == "rediscovery":
            filtered = [c for c in active if c.bucket == "rediscovery"]
        elif familiarity == "familiar":
            filtered = [c for c in active if c.bucket == "comfort"]
        else:
            filtered = active   # "balanced" — no filter

        if filtered and familiarity != "balanced":
            active = filtered
            logger.info("Familiarity filter '%s' → %d candidates", familiarity, len(active))
        elif not filtered:
            logger.info("Familiarity filter '%s' matched nothing — using full pool", familiarity)

        # Nostalgia year filter (skip if nostalgia=0 or nostalgia=3 neutral)
        if questionnaire.nostalgia and questionnaire.nostalgia != 3:
            year_bounds = _NOSTALGIA_YEAR_FILTER.get(questionnaire.nostalgia)
            if year_bounds:
                min_yr, max_yr = year_bounds
                filtered = [
                    c for c in active
                    if (min_yr is None or _release_year(c) >= min_yr)
                    and (max_yr is None or _release_year(c) < max_yr)
                ]
                if filtered:
                    active = filtered
                    logger.info("Nostalgia filter %d → %d candidates", questionnaire.nostalgia, len(active))
                else:
                    logger.info("Nostalgia filter %d matched nothing — using full pool", questionnaire.nostalgia)

    # --- Score ---
    affinity_scores = [
        _compute_artist_affinity(c.artist_id, data)[0] if c.source == "known" else 0.0
        for c in active
    ]
    norm_affinity = _normalize(affinity_scores)
    norm_top    = _normalize([c.top_track_count for c in active])
    norm_saved  = _normalize([c.saved_track_count for c in active])
    norm_recent = _normalize([c.recent_play_count for c in active])

    q = questionnaire  # shorthand
    has_vibe      = q is not None and bool(q.vibe)
    has_mode      = q is not None and bool(q.listening_mode)
    has_nostalgia = q is not None and q.nostalgia != 0
    has_weight    = q is not None and q.heaviness != 5  # non-neutral weight slider

    # Max fraction each signal can contribute when it is the only active signal.
    # Base score always receives whatever is left; it gets at least BASE_MIN.
    _SIG_MAX  = {'vibe': 0.52, 'mode': 0.45, 'weight': 0.38, 'nos': 0.40}
    BASE_MIN  = 0.30

    for i, c in enumerate(active):
        vibe_s = c.vibe_score
        mode_s = c.mode_score
        nos    = _nostalgia_score(c, q.nostalgia) if has_nostalgia else 0.5

        # Genre weight match: how close is the album's heaviness to what was requested
        if has_weight:
            target_w = q.heaviness / 10.0
            weight_match = 1.0 - abs(c.weight_score - target_w)
        else:
            weight_match = 0.5

        if c.source == "discovery":
            base = c.genre_overlap_score
            c.artist_affinity, c.top_term_artist = 0.0, ""
            a_norm = tt_norm = st_norm = rp_norm = saved_bonus = over = 0.0
        else:
            a_norm      = norm_affinity[i]
            tt_norm     = norm_top[i]
            st_norm     = norm_saved[i]
            # Only count recent plays if the album also has long-term top tracks.
            rp_norm     = norm_recent[i] if c.long_term_top_track_count > 0 else 0.0
            saved_bonus = 1.0 if c.is_saved_album else 0.0
            over        = max(0.0, (tt_norm + rp_norm - 0.8)) if c.is_saved_album else 0.0

            base = (
                W_ARTIST_AFFINITY * a_norm
                + W_TOP_TRACK * tt_norm
                + W_SAVED_TRACK * st_norm
                + W_RECENT_PLAY * rp_norm
                + W_SAVED_ALBUM_BONUS * saved_bonus
                - W_OVERFAMILIARITY * over
            )
            c.artist_affinity, c.top_term_artist = _compute_artist_affinity(c.artist_id, data)

        # Dynamic blend: collect active signals, scale so base always gets >= BASE_MIN
        active_sigs: dict[str, float] = {}
        if has_vibe:      active_sigs['vibe']   = vibe_s
        if has_mode:      active_sigs['mode']   = mode_s
        if has_weight:    active_sigs['weight'] = weight_match
        if has_nostalgia: active_sigs['nos']    = nos

        if not active_sigs:
            score = base
        else:
            raw_budget = sum(_SIG_MAX[k] for k in active_sigs)
            budget = 1.0 - BASE_MIN
            factor = min(1.0, budget / raw_budget)
            base_frac = 1.0 - raw_budget * factor
            score = base_frac * base + sum(
                active_sigs[k] * _SIG_MAX[k] * factor for k in active_sigs
            )

        c.album_score = round(score, 4)
        if c.source == "discovery":
            c.score_breakdown = {
                "genre_overlap":   round(base, 3),
                "vibe_score":      round(vibe_s, 3),
                "mode_score":      round(mode_s, 3),
                "weight_score":    round(weight_match, 3),
                "nostalgia_score": round(nos, 3),
            }
        else:
            c.score_breakdown = {
                "artist_affinity":         round(a_norm, 3),
                "top_track_overlap":       round(tt_norm, 3),
                "saved_track_overlap":     round(st_norm, 3),
                "recent_play_overlap":     round(rp_norm, 3),
                "saved_album_bonus":       round(saved_bonus, 3),
                "overfamiliarity_penalty": round(over, 3),
                "vibe_score":              round(vibe_s, 3),
                "mode_score":              round(mode_s, 3),
                "weight_score":            round(weight_match, 3),
                "nostalgia_score":         round(nos, 3),
            }

    active.sort(key=lambda c: c.album_score, reverse=True)

    # One album per artist
    seen: set[str] = set()
    deduped: list[AlbumCandidate] = []
    for c in active:
        if c.artist_id not in seen:
            seen.add(c.artist_id)
            deduped.append(c)

    logger.info("Top 3: %s", [(c.album_name, c.artist_name, c.album_score) for c in deduped[:3]])
    return deduped
