"""
Last.fm enrichment: persist similarity edges and artist tags.
"""

import asyncio
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from models.db_models import Artist, ArtistSimilarityEdge, ArtistTag
import services.lastfm_client as lfm

logger = logging.getLogger(__name__)

_SIMILARITY_REFRESH_DAYS = 30
_TAGS_REFRESH_DAYS = 30


def _needs_similarity_refresh(artist: Artist) -> bool:
    if not artist.similarity_refreshed_at:
        return True
    return (datetime.utcnow() - artist.similarity_refreshed_at).days >= _SIMILARITY_REFRESH_DAYS


def _needs_tags_refresh(artist: Artist) -> bool:
    if not artist.tags_refreshed_at:
        return True
    return (datetime.utcnow() - artist.tags_refreshed_at).days >= _TAGS_REFRESH_DAYS


def _get_or_create_artist_by_lastfm_name(db: Session, name: str) -> Artist:
    row = db.query(Artist).filter(Artist.lastfm_name == name).first()
    if not row:
        row = Artist(lastfm_name=name, name=name, created_at=datetime.utcnow())
        db.add(row)
        db.flush()   # get the ID without full commit
    return row


async def enrich_similarity(db: Session, artist: Artist) -> None:
    """Fetch Last.fm similar artists for `artist` and persist the edges."""
    if not _needs_similarity_refresh(artist):
        return

    lookup_name = artist.lastfm_name or artist.name
    similar = await lfm.get_similar_artists(lookup_name, limit=50)
    if not similar:
        return

    now = datetime.utcnow()
    for item in similar:
        target_name = item["name"]
        score = item["match"]
        if score < 0.05:   # ignore negligible similarity
            continue

        target = _get_or_create_artist_by_lastfm_name(db, target_name)

        existing = (
            db.query(ArtistSimilarityEdge)
            .filter(
                ArtistSimilarityEdge.source_artist_id == artist.id,
                ArtistSimilarityEdge.target_artist_id == target.id,
            )
            .first()
        )
        if existing:
            existing.similarity_score = score
            existing.refreshed_at = now
        else:
            db.add(ArtistSimilarityEdge(
                source_artist_id=artist.id,
                target_artist_id=target.id,
                similarity_score=score,
                refreshed_at=now,
            ))

    artist.similarity_refreshed_at = now
    db.commit()
    logger.info("Stored %d similarity edges for '%s'", len(similar), lookup_name)


async def enrich_tags(db: Session, artist: Artist) -> None:
    """Fetch Last.fm tags for `artist` and persist them."""
    if not _needs_tags_refresh(artist):
        return

    lookup_name = artist.lastfm_name or artist.name
    tags = await lfm.get_artist_tags(lookup_name, limit=15)
    if not tags:
        return

    now = datetime.utcnow()
    max_count = max((t["count"] for t in tags), default=1) or 1

    for item in tags:
        tag_name = item["name"]
        weight = item["count"] / max_count   # normalise to 0–1

        existing = (
            db.query(ArtistTag)
            .filter(ArtistTag.artist_id == artist.id, ArtistTag.tag == tag_name)
            .first()
        )
        if existing:
            existing.weight = weight
            existing.refreshed_at = now
        else:
            db.add(ArtistTag(
                artist_id=artist.id,
                tag=tag_name,
                weight=weight,
                refreshed_at=now,
            ))

    artist.tags_refreshed_at = now
    db.commit()
    logger.info("Stored %d tags for '%s'", len(tags), lookup_name)


async def enrich_artist(db: Session, artist: Artist) -> None:
    """Enrich a single artist: similarity + tags, concurrently."""
    await asyncio.gather(
        enrich_similarity(db, artist),
        enrich_tags(db, artist),
    )
