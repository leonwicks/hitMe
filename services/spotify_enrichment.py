"""
Spotify enrichment: batch-fetch genres for known artists and persist them.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from models.db_models import Artist
from services.spotify_client import SpotifyClient

logger = logging.getLogger(__name__)

_GENRE_REFRESH_DAYS = 30


def _needs_genre_refresh(artist: Artist) -> bool:
    if not artist.genres_refreshed_at:
        return True
    age = (datetime.utcnow() - artist.genres_refreshed_at).days
    return age >= _GENRE_REFRESH_DAYS


async def enrich_artist_genres(
    db: Session,
    client: SpotifyClient,
    artists: list[tuple[str, str]],   # list of (spotify_artist_id, name)
) -> None:
    """
    Upsert artists into the DB and batch-refresh their genres from Spotify.

    Only fetches from Spotify for artists whose genres are missing or stale.
    """
    if not artists:
        return

    # Upsert all artists into DB first
    for spotify_id, name in artists:
        existing = db.query(Artist).filter(Artist.spotify_artist_id == spotify_id).first()
        if existing:
            continue
        # May already exist from Last.fm enrichment under the same name
        by_name = db.query(Artist).filter(Artist.lastfm_name == name).first()
        if by_name:
            by_name.spotify_artist_id = spotify_id
        else:
            db.add(Artist(
                spotify_artist_id=spotify_id,
                name=name,
                lastfm_name=name,
                created_at=datetime.utcnow(),
            ))
    db.commit()

    # Find which need refreshing
    stale_ids = []
    for spotify_id, _ in artists:
        row = db.query(Artist).filter(Artist.spotify_artist_id == spotify_id).first()
        if row and _needs_genre_refresh(row):
            stale_ids.append(spotify_id)

    if not stale_ids:
        logger.info("All %d artists have fresh genre data", len(artists))
        return

    logger.info("Refreshing genres for %d artists", len(stale_ids))

    # Batch fetch — Spotify accepts up to 50 IDs at once
    for i in range(0, len(stale_ids), 50):
        batch = stale_ids[i:i + 50]
        try:
            data = await client.get("/artists", ids=",".join(batch))
            for raw in data.get("artists") or []:
                if not raw or not raw.get("id"):
                    continue
                row = db.query(Artist).filter(Artist.spotify_artist_id == raw["id"]).first()
                if row:
                    row.genres = json.dumps(raw.get("genres") or [])
                    row.genres_refreshed_at = datetime.utcnow()
            db.commit()
        except Exception as exc:
            logger.warning("Batch genre fetch failed: %s", exc)
