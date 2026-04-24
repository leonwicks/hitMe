"""
Spotify sync service.

Single entry point: get_listening_data(db, user_id, client).

For each signal type, checks whether the persisted data is stale (>= 7 days
or never fetched). Stale signals are re-fetched from the Spotify API and
written to the DB. Fresh signals are loaded directly from the DB.

Recently played is always fetched live and never stored — it changes too
fast to be worth persisting and is not used for historical analysis.

The pipeline always reads ListeningData from the DB after any sync, so the
rest of the codebase sees a consistent view regardless of what was refreshed.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from models.db_models import (
    Album, Artist, ArtistAlbumLink, Track,
    UserSavedAlbum, UserSavedTrack,
    UserSyncStatus, UserTopArtist, UserTopTrack,
)
from models.schemas import AlbumData, ArtistData, ListeningData, TrackData
import services.spotify_fetcher as fetcher
from services.spotify_client import SpotifyClient

logger = logging.getLogger(__name__)

SYNC_TTL_DAYS = 7
_KEY_ARTISTS_COUNT = 15


def _utcnow() -> datetime:
    return datetime.utcnow()


def _is_stale(synced_at: Optional[datetime]) -> bool:
    if synced_at is None:
        return True
    return (_utcnow() - synced_at).days >= SYNC_TTL_DAYS


# ---------------------------------------------------------------------------
# Catalogue upserts — shared across users
# ---------------------------------------------------------------------------

def _upsert_artist(db: Session, spotify_id: str, name: str) -> Artist:
    # Check by Spotify ID first (the common case)
    row = db.query(Artist).filter(Artist.spotify_artist_id == spotify_id).first()
    if row:
        return row
    # Check by lastfm_name — row may exist from Last.fm enrichment without a Spotify ID yet
    row = db.query(Artist).filter(Artist.lastfm_name == name).first()
    if row:
        row.spotify_artist_id = spotify_id
        db.flush()
        return row
    row = Artist(
        spotify_artist_id=spotify_id,
        lastfm_name=name,
        name=name,
        created_at=_utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def _upsert_album(db: Session, album_data: AlbumData, artist: Artist) -> Album:
    row = db.query(Album).filter(Album.spotify_album_id == album_data.album_id).first()
    if row:
        # Refresh mutable fields in case they've changed
        row.image_url = album_data.image_url or row.image_url
        row.spotify_url = album_data.spotify_url or row.spotify_url
        row.updated_at = _utcnow()
        return row
    row = Album(
        spotify_album_id=album_data.album_id,
        title=album_data.album_name,
        primary_artist_id=artist.id,
        release_date=album_data.release_date,
        image_url=album_data.image_url,
        spotify_url=album_data.spotify_url,
        total_tracks=album_data.total_tracks or None,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def _upsert_track(db: Session, track_data: TrackData, album: Album, artist: Artist) -> Track:
    row = db.query(Track).filter(Track.spotify_track_id == track_data.track_id).first()
    if row:
        return row
    row = Track(
        spotify_track_id=track_data.track_id,
        title=track_data.track_name,
        album_id=album.id,
        primary_artist_id=artist.id,
        spotify_url=track_data.spotify_url,
        created_at=_utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def _link_artist_album(db: Session, artist_id: int, album_id: int) -> None:
    exists = db.query(ArtistAlbumLink).filter_by(
        artist_id=artist_id, album_id=album_id
    ).first()
    if not exists:
        db.add(ArtistAlbumLink(artist_id=artist_id, album_id=album_id))


# ---------------------------------------------------------------------------
# Signal sync functions
# ---------------------------------------------------------------------------

async def _sync_top_artists(db: Session, client: SpotifyClient, user_id: int) -> None:
    logger.info("Syncing top artists for user_id=%s", user_id)
    # Delete existing snapshot for all time ranges
    db.query(UserTopArtist).filter(UserTopArtist.user_id == user_id).delete()
    db.commit()

    for time_range in ("long_term", "medium_term", "short_term"):
        artists = await fetcher._get_top_artists(client, time_range)
        for rank, a in enumerate(artists, start=1):
            artist_row = _upsert_artist(db, a.artist_id, a.artist_name)
            db.flush()
            db.add(UserTopArtist(
                user_id=user_id,
                artist_id=artist_row.id,
                time_range=time_range,
                rank=rank,
            ))
        db.commit()


async def _sync_top_tracks(db: Session, client: SpotifyClient, user_id: int) -> None:
    logger.info("Syncing top tracks for user_id=%s", user_id)
    db.query(UserTopTrack).filter(UserTopTrack.user_id == user_id).delete()
    db.commit()

    for time_range in ("long_term", "medium_term", "short_term"):
        tracks = await fetcher._get_top_tracks(client, time_range)
        for rank, t in enumerate(tracks, start=1):
            if not t.album_id:
                continue
            artist_row = _upsert_artist(db, t.artist_id, t.artist_name)
            album_data = AlbumData(
                album_id=t.album_id, album_name=t.album_name,
                artist_id=t.artist_id, artist_name=t.artist_name,
                image_url=t.image_url, spotify_url="",
                release_date=t.release_date,
            )
            album_row = _upsert_album(db, album_data, artist_row)
            track_row = _upsert_track(db, t, album_row, artist_row)
            db.flush()
            db.add(UserTopTrack(
                user_id=user_id,
                track_id=track_row.id,
                time_range=time_range,
                rank=rank,
            ))
        db.commit()


async def _sync_saved_albums(db: Session, client: SpotifyClient, user_id: int) -> None:
    logger.info("Syncing saved albums for user_id=%s", user_id)
    db.query(UserSavedAlbum).filter(UserSavedAlbum.user_id == user_id).delete()
    db.commit()

    albums = await fetcher._get_saved_albums(client)
    for a in albums:
        artist_row = _upsert_artist(db, a.artist_id, a.artist_name)
        album_row = _upsert_album(db, a, artist_row)
        db.flush()
        db.add(UserSavedAlbum(user_id=user_id, album_id=album_row.id))
    db.commit()


async def _sync_saved_tracks(db: Session, client: SpotifyClient, user_id: int) -> None:
    logger.info("Syncing saved tracks for user_id=%s", user_id)
    db.query(UserSavedTrack).filter(UserSavedTrack.user_id == user_id).delete()
    db.commit()

    tracks = await fetcher._get_saved_tracks(client)
    for t in tracks:
        if not t.album_id:
            continue
        artist_row = _upsert_artist(db, t.artist_id, t.artist_name)
        album_data = AlbumData(
            album_id=t.album_id, album_name=t.album_name,
            artist_id=t.artist_id, artist_name=t.artist_name,
            image_url=t.image_url, spotify_url="",
            release_date=t.release_date,
        )
        album_row = _upsert_album(db, album_data, artist_row)
        track_row = _upsert_track(db, t, album_row, artist_row)
        db.flush()
        db.add(UserSavedTrack(user_id=user_id, track_id=track_row.id))
    db.commit()


async def _sync_artist_albums(db: Session, client: SpotifyClient, user_id: int) -> None:
    """Fetch discography albums for the user's top key artists."""
    logger.info("Syncing artist albums for user_id=%s", user_id)

    # Determine key artists: top _KEY_ARTISTS_COUNT unique artists across all ranges
    rows = (
        db.query(UserTopArtist)
        .filter(UserTopArtist.user_id == user_id)
        .order_by(UserTopArtist.time_range, UserTopArtist.rank)
        .all()
    )

    seen: set[int] = set()
    key_artist_rows: list[Artist] = []
    for row in rows:
        if row.artist_id not in seen:
            seen.add(row.artist_id)
            key_artist_rows.append(row.artist)
        if len(key_artist_rows) >= _KEY_ARTISTS_COUNT:
            break

    # Fetch and store albums for each key artist concurrently
    album_lists = await asyncio.gather(
        *[
            fetcher._get_artist_albums(client, a.spotify_artist_id)
            for a in key_artist_rows
            if a.spotify_artist_id
        ]
    )

    for artist_row, albums in zip(key_artist_rows, album_lists):
        for a in albums:
            artist_for_album = _upsert_artist(db, a.artist_id, a.artist_name)
            album_row = _upsert_album(db, a, artist_for_album)
            db.flush()
            _link_artist_album(db, artist_row.id, album_row.id)
        db.commit()


# ---------------------------------------------------------------------------
# Load ListeningData from DB
# ---------------------------------------------------------------------------

def _load_top_artists(db: Session, user_id: int, time_range: str) -> list[ArtistData]:
    rows = (
        db.query(UserTopArtist)
        .filter(UserTopArtist.user_id == user_id, UserTopArtist.time_range == time_range)
        .order_by(UserTopArtist.rank)
        .all()
    )
    return [ArtistData(artist_id=r.artist.spotify_artist_id, artist_name=r.artist.name) for r in rows if r.artist and r.artist.spotify_artist_id]


def _load_top_tracks(db: Session, user_id: int, time_range: str) -> list[TrackData]:
    rows = (
        db.query(UserTopTrack)
        .filter(UserTopTrack.user_id == user_id, UserTopTrack.time_range == time_range)
        .order_by(UserTopTrack.rank)
        .all()
    )
    result = []
    for r in rows:
        t = r.track
        if not t or not t.album:
            continue
        result.append(TrackData(
            track_id=t.spotify_track_id,
            track_name=t.title,
            album_id=t.album.spotify_album_id,
            album_name=t.album.title,
            artist_id=t.primary_artist.spotify_artist_id if t.primary_artist else "",
            artist_name=t.primary_artist.name if t.primary_artist else "",
            image_url=t.album.image_url or "",
            spotify_url=t.spotify_url or "",
            release_date=t.album.release_date or "",
        ))
    return result


def _load_saved_albums(db: Session, user_id: int) -> list[AlbumData]:
    rows = db.query(UserSavedAlbum).filter(UserSavedAlbum.user_id == user_id).all()
    result = []
    for r in rows:
        a = r.album
        if not a:
            continue
        result.append(AlbumData(
            album_id=a.spotify_album_id,
            album_name=a.title,
            artist_id=a.primary_artist.spotify_artist_id if a.primary_artist else "",
            artist_name=a.primary_artist.name if a.primary_artist else "",
            image_url=a.image_url or "",
            spotify_url=a.spotify_url or "",
            release_date=a.release_date or "",
            total_tracks=a.total_tracks or 0,
        ))
    return result


def _load_saved_tracks(db: Session, user_id: int) -> list[TrackData]:
    rows = db.query(UserSavedTrack).filter(UserSavedTrack.user_id == user_id).all()
    result = []
    for r in rows:
        t = r.track
        if not t or not t.album:
            continue
        result.append(TrackData(
            track_id=t.spotify_track_id,
            track_name=t.title,
            album_id=t.album.spotify_album_id,
            album_name=t.album.title,
            artist_id=t.primary_artist.spotify_artist_id if t.primary_artist else "",
            artist_name=t.primary_artist.name if t.primary_artist else "",
            image_url=t.album.image_url or "",
            spotify_url=t.spotify_url or "",
            release_date=t.album.release_date or "",
        ))
    return result


def _load_artist_albums(db: Session, user_id: int) -> dict[str, list[AlbumData]]:
    """Load discography albums for the user's key artists."""
    top_artist_rows = (
        db.query(UserTopArtist)
        .filter(UserTopArtist.user_id == user_id)
        .order_by(UserTopArtist.time_range, UserTopArtist.rank)
        .all()
    )

    seen: set[int] = set()
    key_artists: list[Artist] = []
    for row in top_artist_rows:
        if row.artist_id not in seen:
            seen.add(row.artist_id)
            key_artists.append(row.artist)
        if len(key_artists) >= _KEY_ARTISTS_COUNT:
            break

    result: dict[str, list[AlbumData]] = {}
    for artist in key_artists:
        if not artist or not artist.spotify_artist_id:
            continue
        links = (
            db.query(ArtistAlbumLink)
            .filter(ArtistAlbumLink.artist_id == artist.id)
            .all()
        )
        albums = []
        for link in links:
            a = link.album
            if not a:
                continue
            albums.append(AlbumData(
                album_id=a.spotify_album_id,
                album_name=a.title,
                artist_id=artist.spotify_artist_id,
                artist_name=artist.name,
                image_url=a.image_url or "",
                spotify_url=a.spotify_url or "",
                release_date=a.release_date or "",
                total_tracks=a.total_tracks or 0,
            ))
        if albums:
            result[artist.spotify_artist_id] = albums

    return result


# ---------------------------------------------------------------------------
# DB-only load (no sync, no API calls)
# ---------------------------------------------------------------------------

def load_from_db(db: Session, user_id: int) -> ListeningData:
    """
    Load ListeningData entirely from the DB with no Spotify API calls.
    Recently played will be an empty list — only use this for offline testing.
    Returns None-equivalent (empty ListeningData) if user has no synced data.
    """
    return ListeningData(
        long_term_artists=_load_top_artists(db, user_id, "long_term"),
        medium_term_artists=_load_top_artists(db, user_id, "medium_term"),
        short_term_artists=_load_top_artists(db, user_id, "short_term"),
        long_term_tracks=_load_top_tracks(db, user_id, "long_term"),
        medium_term_tracks=_load_top_tracks(db, user_id, "medium_term"),
        short_term_tracks=_load_top_tracks(db, user_id, "short_term"),
        saved_albums=_load_saved_albums(db, user_id),
        saved_tracks=_load_saved_tracks(db, user_id),
        recently_played=[],
        artist_albums=_load_artist_albums(db, user_id),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def get_listening_data(
    db: Session,
    user_id: int,
    client: SpotifyClient,
) -> ListeningData:
    """
    Return a fully-populated ListeningData for the user.

    Each signal type is re-fetched from Spotify if its last sync was >= 7 days
    ago (or never). Otherwise loaded from the DB. Recently played is always
    fetched live.
    """
    sync = db.query(UserSyncStatus).filter(UserSyncStatus.user_id == user_id).first()
    if not sync:
        sync = UserSyncStatus(user_id=user_id)
        db.add(sync)
        db.commit()

    now = _utcnow()

    async with client:
        # Determine what needs refreshing and run in parallel where independent
        stale_top_artists = _is_stale(sync.top_artists_synced_at)
        stale_top_tracks  = _is_stale(sync.top_tracks_synced_at)
        stale_saved_albums = _is_stale(sync.saved_albums_synced_at)
        stale_saved_tracks = _is_stale(sync.saved_tracks_synced_at)
        stale_artist_albums = _is_stale(sync.artist_albums_synced_at)

        tasks = []
        if stale_top_artists:
            tasks.append(_sync_top_artists(db, client, user_id))
        if stale_top_tracks:
            tasks.append(_sync_top_tracks(db, client, user_id))
        if stale_saved_albums:
            tasks.append(_sync_saved_albums(db, client, user_id))
        if stale_saved_tracks:
            tasks.append(_sync_saved_tracks(db, client, user_id))

        if tasks:
            await asyncio.gather(*tasks)

        # Artist albums depend on top artists being fresh first
        if stale_artist_albums or stale_top_artists:
            await _sync_artist_albums(db, client, user_id)

        # Always fetch recently played live
        recently_played = await fetcher._get_recently_played(client)

    # Update sync timestamps
    if stale_top_artists:
        sync.top_artists_synced_at = now
    if stale_top_tracks:
        sync.top_tracks_synced_at = now
    if stale_saved_albums:
        sync.saved_albums_synced_at = now
    if stale_saved_tracks:
        sync.saved_tracks_synced_at = now
    if stale_artist_albums or stale_top_artists:
        sync.artist_albums_synced_at = now
    db.commit()

    logger.info(
        "Listening data ready for user_id=%s "
        "(refreshed: top_artists=%s top_tracks=%s saved_albums=%s saved_tracks=%s artist_albums=%s)",
        user_id,
        stale_top_artists, stale_top_tracks,
        stale_saved_albums, stale_saved_tracks,
        stale_artist_albums or stale_top_artists,
    )

    return ListeningData(
        long_term_artists=_load_top_artists(db, user_id, "long_term"),
        medium_term_artists=_load_top_artists(db, user_id, "medium_term"),
        short_term_artists=_load_top_artists(db, user_id, "short_term"),
        long_term_tracks=_load_top_tracks(db, user_id, "long_term"),
        medium_term_tracks=_load_top_tracks(db, user_id, "medium_term"),
        short_term_tracks=_load_top_tracks(db, user_id, "short_term"),
        saved_albums=_load_saved_albums(db, user_id),
        saved_tracks=_load_saved_tracks(db, user_id),
        recently_played=recently_played,
        artist_albums=_load_artist_albums(db, user_id),
    )
