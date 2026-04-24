"""
Artist matcher: resolve Last.fm artist names to Spotify artist IDs.

Runs for artists in the DB that have a lastfm_name but no spotify_artist_id.
Uses Spotify search + normalised name comparison to find matches.
"""

import logging
import re
import unicodedata
from datetime import datetime

from sqlalchemy.orm import Session

from models.db_models import Artist
from services.spotify_client import SpotifyClient

logger = logging.getLogger(__name__)

_MATCH_LIMIT = 25   # max unresolved artists to attempt per run


def _normalise(name: str) -> str:
    """Lowercase, strip accents, remove punctuation, collapse whitespace."""
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")  # strip combining marks
    name = name.lower()
    name = re.sub(r"[^\w\s]", "", name)         # remove punctuation
    name = re.sub(r"\b(feat|ft|and|the)\b", "", name)  # remove noise words
    return re.sub(r"\s+", " ", name).strip()


async def match_unresolved_artists(db: Session, client: SpotifyClient) -> None:
    """
    Attempt to resolve up to _MATCH_LIMIT unresolved Last.fm artists to Spotify IDs.
    Silently skips artists that don't match confidently.
    """
    unresolved = (
        db.query(Artist)
        .filter(Artist.spotify_artist_id.is_(None), Artist.lastfm_name.isnot(None))
        .limit(_MATCH_LIMIT)
        .all()
    )

    if not unresolved:
        return

    logger.info("Attempting to match %d unresolved artists", len(unresolved))

    for artist in unresolved:
        await _try_match(db, client, artist)


async def _try_match(db: Session, client: SpotifyClient, artist: Artist) -> None:
    name = artist.lastfm_name or artist.name
    try:
        data = await client.get("/search", q=f"artist:{name}", type="artist", limit=5)
        items = data.get("artists", {}).get("items") or []
    except Exception as exc:
        logger.warning("Spotify search failed for '%s': %s", name, exc)
        return

    norm_target = _normalise(name)

    for item in items:
        if not item or not item.get("id"):
            continue

        norm_candidate = _normalise(item.get("name", ""))
        if norm_candidate == norm_target:
            # Check no other artist already has this Spotify ID
            conflict = db.query(Artist).filter(
                Artist.spotify_artist_id == item["id"],
                Artist.id != artist.id,
            ).first()
            if conflict:
                logger.info("Spotify ID %s already claimed — skipping '%s'", item["id"], name)
                return

            artist.spotify_artist_id = item["id"]
            artist.name = item["name"]   # use Spotify's canonical spelling
            db.commit()
            logger.info("Matched '%s' → Spotify ID %s", name, item["id"])
            return

    logger.debug("No confident match for '%s'", name)
