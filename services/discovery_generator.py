"""
Discovery candidate generator.

Queries the artist similarity graph for artists the user has never heard,
fetches their albums from Spotify, and annotates each with a genre_overlap_score
derived from the persisted taste profile.
"""

import asyncio
import logging

from sqlalchemy.orm import Session

from models.db_models import Artist, ArtistSimilarityEdge, UserTasteProfile
from models.schemas import AlbumCandidate, AlbumData
import services.spotify_fetcher as fetcher
from services.spotify_client import SpotifyClient

logger = logging.getLogger(__name__)

_MAX_DISCOVERY_ARTISTS = 12   # how many discovery artists to expand per request


def _tag_overlap(artist: Artist, tag_weights: dict) -> float:
    """
    Weighted dot product between artist's Last.fm tags and the user's tag profile.
    Returns 0–1.
    """
    if not artist.tags or not tag_weights:
        return 0.0
    score = sum(tag_weights.get(t.tag, 0.0) * t.weight for t in artist.tags)
    max_score = sum(tag_weights.values())
    return min(score / max_score, 1.0) if max_score else 0.0


def get_discovery_candidates(
    db: Session,
    taste_profile: UserTasteProfile,
) -> list[tuple[Artist, float]]:
    """
    Return (Artist, aggregated_similarity_score) pairs for discovery artists.

    Discovery artists are neighbours in the similarity graph whose Spotify ID
    is resolved but who are NOT in the user's known artist set.
    """
    known_ids = taste_profile.known_artist_ids_set
    tag_weights = taste_profile.tag_weights_dict

    # Find DB IDs for known artists
    known_db_artists = (
        db.query(Artist)
        .filter(Artist.spotify_artist_id.in_(known_ids))
        .all()
    ) if known_ids else []
    known_db_ids = {a.id for a in known_db_artists}

    if not known_db_ids:
        return []

    # Fetch all outgoing edges from known artists to resolved targets
    edges = (
        db.query(ArtistSimilarityEdge)
        .filter(
            ArtistSimilarityEdge.source_artist_id.in_(known_db_ids),
            ArtistSimilarityEdge.similarity_score >= 0.1,
        )
        .all()
    )

    # Aggregate similarity scores per target artist
    target_scores: dict[int, float] = {}
    for edge in edges:
        target_scores[edge.target_artist_id] = (
            target_scores.get(edge.target_artist_id, 0) + edge.similarity_score
        )

    # Remove known artists from targets
    discovery_ids = {aid for aid in target_scores if aid not in known_db_ids}
    if not discovery_ids:
        return []

    # Fetch artist records — only those with a resolved Spotify ID
    candidates = (
        db.query(Artist)
        .filter(
            Artist.id.in_(discovery_ids),
            Artist.spotify_artist_id.isnot(None),
        )
        .all()
    )

    # Score each by similarity + tag overlap, sort, cap
    scored = []
    for artist in candidates:
        sim = target_scores.get(artist.id, 0)
        tag_ov = _tag_overlap(artist, tag_weights)
        combined = 0.7 * sim + 0.3 * tag_ov
        scored.append((artist, combined))

    scored.sort(key=lambda x: -x[1])
    return scored[:_MAX_DISCOVERY_ARTISTS]


async def fetch_discovery_album_candidates(
    db: Session,
    client: SpotifyClient,
    taste_profile: UserTasteProfile,
) -> list[AlbumCandidate]:
    """
    Fetch albums for discovery artists and return tagged AlbumCandidate objects.
    """
    artist_scores = get_discovery_candidates(db, taste_profile)
    if not artist_scores:
        return []

    tag_weights = taste_profile.tag_weights_dict

    # Fetch albums for all discovery artists concurrently
    album_lists = await asyncio.gather(
        *[fetcher._get_artist_albums(client, a.spotify_artist_id) for a, _ in artist_scores]
    )

    candidates: list[AlbumCandidate] = []
    for (artist, sim_score), albums in zip(artist_scores, album_lists):
        tag_ov = _tag_overlap(artist, tag_weights)
        genre_overlap = round(0.7 * sim_score + 0.3 * tag_ov, 4)

        for album in albums:
            if not album.image_url:
                continue
            c = AlbumCandidate(
                album_id=album.album_id,
                album_name=album.album_name,
                artist_id=album.artist_id,
                artist_name=album.artist_name,
                image_url=album.image_url,
                spotify_url=album.spotify_url,
                release_date=album.release_date,
                source="discovery",
                genre_overlap_score=genre_overlap,
            )
            candidates.append(c)

    logger.info(
        "Generated %d discovery candidates from %d artists",
        len(candidates), len(artist_scores),
    )
    return candidates
