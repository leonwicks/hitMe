"""
Stage 1 — Candidate Generation.

Collects every album we can reasonably suggest from the user's live
Spotify data and annotates each one with raw signal counts.  No scoring
happens here; that is Stage 2 (ranker.py).
"""

import logging
from collections import defaultdict
from typing import Optional

from models.schemas import AlbumCandidate, AlbumData, ListeningData

logger = logging.getLogger(__name__)


def _album_to_candidate(album: AlbumData) -> AlbumCandidate:
    return AlbumCandidate(
        album_id=album.album_id,
        album_name=album.album_name,
        artist_id=album.artist_id,
        artist_name=album.artist_name,
        image_url=album.image_url,
        spotify_url=album.spotify_url,
        release_date=album.release_date,
    )


def generate(data: ListeningData) -> list[AlbumCandidate]:
    """
    Build the candidate pool from all live Spotify signals.

    Returns a deduplicated list of AlbumCandidate objects annotated with:
    - is_saved_album
    - top_track_count  (across all three time ranges)
    - saved_track_count
    - recent_play_count
    """
    # -----------------------------------------------------------------------
    # 1. Collect albums by ID, merging duplicates
    # -----------------------------------------------------------------------
    albums_by_id: dict[str, AlbumCandidate] = {}

    def add(album: Optional[AlbumData]) -> None:
        if album is None or not album.album_id:
            return
        if album.album_id not in albums_by_id:
            albums_by_id[album.album_id] = _album_to_candidate(album)

    # Saved albums
    saved_album_ids: set[str] = set()
    for album in data.saved_albums:
        add(album)
        saved_album_ids.add(album.album_id)

    # Albums extracted from top tracks (all three ranges)
    for track in (*data.long_term_tracks, *data.medium_term_tracks, *data.short_term_tracks):
        if track.album_id:
            add(AlbumData(
                album_id=track.album_id,
                album_name=track.album_name,
                artist_id=track.artist_id,
                artist_name=track.artist_name,
                image_url=track.image_url,
                spotify_url="",
                release_date=track.release_date,
            ))

    # Albums extracted from saved tracks
    for track in data.saved_tracks:
        if track.album_id:
            add(AlbumData(
                album_id=track.album_id,
                album_name=track.album_name,
                artist_id=track.artist_id,
                artist_name=track.artist_name,
                image_url=track.image_url,
                spotify_url="",
                release_date=track.release_date,
            ))

    # Albums extracted from recently played
    for track in data.recently_played:
        if track.album_id:
            add(AlbumData(
                album_id=track.album_id,
                album_name=track.album_name,
                artist_id=track.artist_id,
                artist_name=track.artist_name,
                image_url=track.image_url,
                spotify_url="",
                release_date=track.release_date,
            ))

    # Albums from top artists (via artist albums endpoint)
    for artist_albums in data.artist_albums.values():
        for album in artist_albums:
            add(album)

    # -----------------------------------------------------------------------
    # 2. Annotate candidates with raw signal counts
    # -----------------------------------------------------------------------

    # top_track_count: album appears in any time range's top tracks
    top_track_album_ids: dict[str, int] = defaultdict(int)
    for track in (*data.long_term_tracks, *data.medium_term_tracks, *data.short_term_tracks):
        if track.album_id:
            top_track_album_ids[track.album_id] += 1

    # saved_track_count: how many saved tracks are on each album
    saved_track_album_counts: dict[str, int] = defaultdict(int)
    for track in data.saved_tracks:
        if track.album_id:
            saved_track_album_counts[track.album_id] += 1

    # recent_play_count: how many recently played tracks are from each album
    recent_play_album_counts: dict[str, int] = defaultdict(int)
    for track in data.recently_played:
        if track.album_id:
            recent_play_album_counts[track.album_id] += 1

    for candidate in albums_by_id.values():
        candidate.is_saved_album = candidate.album_id in saved_album_ids
        candidate.top_track_count = top_track_album_ids.get(candidate.album_id, 0)
        candidate.saved_track_count = saved_track_album_counts.get(candidate.album_id, 0)
        candidate.recent_play_count = recent_play_album_counts.get(candidate.album_id, 0)

    candidates = list(albums_by_id.values())

    # Filter out candidates with no image (display would be poor)
    candidates = [c for c in candidates if c.image_url]

    logger.info("Generated %d album candidates", len(candidates))
    return candidates
