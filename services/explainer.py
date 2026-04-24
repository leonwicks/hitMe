"""
Explanation generation.

Converts the raw scoring signals on an AlbumCandidate into a human-readable
summary sentence and a short list of bullet points.
"""

from models.schemas import AlbumCandidate, Explanation, QuestionnaireResponse

_BUCKET_LABEL = {
    "comfort":    "a favourite",
    "rediscovery": "a rediscovery",
    "adjacent":   "something you might love",
    "discovery":  "a new discovery",
}

_TERM_PHRASE = {
    "long":   "one of your all-time favourite artists",
    "medium": "an artist you've been loving this year",
    "short":  "an artist you've been playing a lot lately",
    "":       "an artist you follow",
}

_NOSTALGIA_PHRASE = {
    1: "a recent release",
    2: "something relatively recent",
    4: "something with a bit of history",
    5: "a classic",
}

_VIBE_PHRASE = {
    "melancholy": "quiet and a little melancholic",
    "energised":  "energised and driven",
    "warm":       "warm and familiar-feeling",
    "unsettled":  "restless and interesting",
    "focused":    "focused and undemanding",
}


def _known_artist_bullets(candidate: AlbumCandidate) -> list[str]:
    bullets = []
    term = candidate.top_term_artist
    if term:
        bullets.append(f"{candidate.artist_name} is {_TERM_PHRASE[term]}.")
    if candidate.top_track_count == 1:
        bullets.append("One of your top tracks comes from this album.")
    elif candidate.top_track_count > 1:
        bullets.append(
            f"{candidate.top_track_count} of your top tracks come from this album."
        )
    if candidate.saved_track_count == 1:
        bullets.append("You have a saved track from this album.")
    elif candidate.saved_track_count > 1:
        bullets.append(f"You've saved {candidate.saved_track_count} tracks from this album.")
    if candidate.is_saved_album:
        if candidate.bucket == "rediscovery":
            bullets.append(
                "You saved this album but haven't listened recently — "
                "a good time to revisit."
            )
        else:
            bullets.append("This album is in your library.")
    if candidate.recent_play_count > 0 and candidate.top_track_count == 0:
        if candidate.recent_play_count == 1:
            bullets.append("You recently played a track from this album.")
        else:
            bullets.append(
                f"You've recently played {candidate.recent_play_count} "
                "tracks from this album."
            )
    return bullets


def _discovery_bullets(candidate: AlbumCandidate) -> list[str]:
    bullets = [f"{candidate.artist_name} is an artist we think you'll love."]
    if candidate.genre_overlap_score >= 0.7:
        bullets.append("Their sound sits squarely in your taste profile.")
    elif candidate.genre_overlap_score >= 0.4:
        bullets.append("They share a lot of ground with artists you already love.")
    else:
        bullets.append("A bit of a stretch — but worth hearing.")
    return bullets


def _questionnaire_bullet(q: QuestionnaireResponse, candidate: AlbumCandidate) -> str:
    parts = []
    vibe = _VIBE_PHRASE.get(q.vibe)
    if vibe:
        parts.append(vibe)
    nos = _NOSTALGIA_PHRASE.get(q.nostalgia)
    if nos:
        parts.append(nos)
    if not parts:
        return ""
    sentence = f"Chosen to feel {' and '.join(parts)} today."
    # If mood scoring was active and this album scored well, acknowledge it
    if q.vibe and candidate.mood_score >= 0.65:
        sentence += " Their sound fits the mood."
    return sentence


def explain(
    candidate: AlbumCandidate,
    questionnaire: "QuestionnaireResponse | None" = None,
) -> Explanation:
    """Return a short summary and 2–4 explanatory bullets for the recommendation."""
    bucket_label = _BUCKET_LABEL.get(candidate.bucket, "a great pick")
    summary = (
        f"{candidate.album_name} by {candidate.artist_name} "
        f"is {bucket_label}."
    )

    if candidate.source == "discovery":
        bullets = _discovery_bullets(candidate)
    else:
        bullets = _known_artist_bullets(candidate)

    if questionnaire is not None:
        q_bullet = _questionnaire_bullet(questionnaire, candidate)
        if q_bullet:
            bullets.append(q_bullet)

    if not bullets:
        bullets.append(
            f"Based on your listening history, "
            f"{candidate.artist_name} aligns with your taste."
        )

    return Explanation(summary=summary, bullets=bullets[:4])
