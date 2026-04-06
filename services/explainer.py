"""
Explanation generation.

Converts the raw scoring signals on an AlbumCandidate into a human-readable
summary sentence and a short list of bullet points.
"""

from models.schemas import AlbumCandidate, Explanation, ListeningData

_BUCKET_LABEL = {
    "comfort": "a favourite",
    "rediscovery": "a rediscovery",
    "adjacent": "something you might love",
}

_TERM_PHRASE = {
    "long": "one of your all-time favourite artists",
    "medium": "an artist you've been loving this year",
    "short": "an artist you've been playing a lot lately",
    "": "an artist you follow",
}


def explain(candidate: AlbumCandidate, data: ListeningData) -> Explanation:
    """
    Return a short summary and 2–4 explanatory bullets for the recommendation.
    """
    name = candidate.album_name
    artist = candidate.artist_name
    bucket_label = _BUCKET_LABEL.get(candidate.bucket, "a great pick")

    summary = f"{name} by {artist} is {bucket_label} based on your listening history."

    bullets: list[str] = []

    # Artist presence in top artists
    term = candidate.top_term_artist
    if term:
        bullets.append(f"{artist} is {_TERM_PHRASE[term]}.")

    # Top track overlap
    if candidate.top_track_count == 1:
        bullets.append("One of your top tracks comes from this album.")
    elif candidate.top_track_count > 1:
        bullets.append(f"{candidate.top_track_count} of your top tracks come from this album.")

    # Saved track overlap
    if candidate.saved_track_count == 1:
        bullets.append("You have a saved track from this album.")
    elif candidate.saved_track_count > 1:
        bullets.append(f"You've saved {candidate.saved_track_count} tracks from this album.")

    # Saved album
    if candidate.is_saved_album:
        if candidate.bucket == "rediscovery":
            bullets.append("You saved this album but haven't listened much recently — a good time to revisit.")
        else:
            bullets.append("This album is in your library.")

    # Recent play signal (only if not already covered by top track overlap)
    if candidate.recent_play_count > 0 and candidate.top_track_count == 0:
        if candidate.recent_play_count == 1:
            bullets.append("You recently played a track from this album.")
        else:
            bullets.append(f"You've recently played {candidate.recent_play_count} tracks from this album.")

    # Fallback bullet if we somehow have nothing
    if not bullets:
        bullets.append(f"Based on your listening history, {artist} aligns with your taste.")

    return Explanation(summary=summary, bullets=bullets[:4])
