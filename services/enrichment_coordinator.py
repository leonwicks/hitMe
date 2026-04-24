"""
Enrichment coordinator.

Called once per recommendation request (after Spotify data is fetched).
Decides what needs refreshing, runs enrichment, rebuilds the taste profile,
and returns it. Designed to be a no-op when everything is fresh.
"""

import asyncio
import logging

from sqlalchemy.orm import Session

from config import settings
from models.db_models import Artist, UserTasteProfile
from models.schemas import ListeningData
import services.spotify_enrichment as spotify_enrich
import services.lastfm_enrichment as lfm_enrich
import services.artist_matcher as matcher
import services.taste_profiler as profiler
from services.spotify_client import SpotifyClient

logger = logging.getLogger(__name__)


async def ensure_fresh(
    db: Session,
    user_id: int,
    client: SpotifyClient,
    data: ListeningData,
) -> UserTasteProfile:
    """
    Ensure the user's taste profile is up to date.

    1. Upsert known artists + refresh Spotify genres (if stale).
    2. Refresh Last.fm similarity + tags for known artists (if stale).
    3. Attempt to resolve unmatched Last.fm artists to Spotify IDs.
    4. Rebuild the taste profile (if stale or missing).

    Returns the (possibly freshly rebuilt) UserTasteProfile.
    """
    # Check profile staleness first — if fresh, skip all enrichment
    existing = db.query(UserTasteProfile).filter(UserTasteProfile.user_id == user_id).first()
    if existing and not profiler._is_stale(existing):
        return existing

    # Build the list of known artists from Spotify data
    known = _collect_known_artists(data)

    # Step 1: Spotify genre enrichment (batch, fast)
    async with client:
        await spotify_enrich.enrich_artist_genres(db, client, known)

    # Step 2: Last.fm enrichment for known artists (parallel, rate-limited by semaphore)
    if settings.lastfm_api_key:
        known_artist_rows = [
            db.query(Artist).filter(Artist.spotify_artist_id == sid).first()
            for sid, _ in known
        ]
        known_artist_rows = [r for r in known_artist_rows if r]
        await asyncio.gather(*[lfm_enrich.enrich_artist(db, a) for a in known_artist_rows])

        # Step 3: Resolve unmatched discovery artists to Spotify IDs
        async with client:
            await matcher.match_unresolved_artists(db, client)
    else:
        logger.info("No Last.fm API key configured — skipping Last.fm enrichment")

    # Step 4: Rebuild taste profile
    return profiler.get_or_build(db, user_id, data)


def _collect_known_artists(data: ListeningData) -> list[tuple[str, str]]:
    """Return deduplicated (spotify_artist_id, name) pairs from all listening data."""
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for artist_list in (data.long_term_artists, data.medium_term_artists, data.short_term_artists):
        for a in artist_list:
            if a.artist_id and a.artist_id not in seen:
                seen.add(a.artist_id)
                result.append((a.artist_id, a.artist_name))
    return result
