"""
Fetches all listening signals from the Spotify Web API.

All data is fetched live and processed in memory — nothing is cached or
persisted beyond the recommendation request that triggered the fetch.
"""

import asyncio
import logging
from typing import Any, Optional

from models.schemas import (
    ArtistData,
    AlbumData,
    TrackData,
    ListeningData,
)
from services.spotify_client import SpotifyClient

logger = logging.getLogger(__name__)

# How many items to request per page
_TOP_LIMIT = 50
_SAVED_TRACK_PAGES = 4     # 50 × 4 = 200 saved tracks
_SAVED_ALBUM_PAGES = 2     # 50 × 2 = 100 saved albums
_ARTIST_ALBUMS_LIMIT = 50  # albums per artist (Spotify max)
_KEY_ARTISTS_COUNT = 15    # how many top artists to pull albums for


# ---------------------------------------------------------------------------
# Small parsers – raw Spotify dict → typed dataclass
# ---------------------------------------------------------------------------

def _parse_artist(raw: dict) -> ArtistData:
    return ArtistData(artist_id=raw["id"], artist_name=raw["name"])


def _parse_track(raw: dict) -> Optional[TrackData]:
    """Parse a full track object. Returns None for local files (no id)."""
    if not raw.get("id"):
        return None
    album = raw.get("album", {})
    images = album.get("images") or []
    artists = raw.get("artists") or []
    primary = artists[0] if artists else {}
    return TrackData(
        track_id=raw["id"],
        track_name=raw["name"],
        album_id=album.get("id", ""),
        album_name=album.get("name", ""),
        artist_id=primary.get("id", ""),
        artist_name=primary.get("name", ""),
        image_url=images[0]["url"] if images else "",
        spotify_url=raw.get("external_urls", {}).get("spotify", ""),
        release_date=album.get("release_date", ""),
    )


def _parse_album(raw: dict) -> Optional[AlbumData]:
    """Parse a simplified or full album object."""
    if not raw.get("id"):
        return None
    images = raw.get("images") or []
    artists = raw.get("artists") or []
    primary = artists[0] if artists else {}
    return AlbumData(
        album_id=raw["id"],
        album_name=raw["name"],
        artist_id=primary.get("id", ""),
        artist_name=primary.get("name", ""),
        image_url=images[0]["url"] if images else "",
        spotify_url=raw.get("external_urls", {}).get("spotify", ""),
        release_date=raw.get("release_date", ""),
        total_tracks=raw.get("total_tracks", 0) or 0,
    )


# ---------------------------------------------------------------------------
# Individual endpoint fetchers
# ---------------------------------------------------------------------------

async def _get_top_artists(client: SpotifyClient, time_range: str) -> list[ArtistData]:
    try:
        data = await client.get("/me/top/artists", time_range=time_range, limit=_TOP_LIMIT)
        return [_parse_artist(a) for a in data.get("items", [])]
    except Exception as exc:
        logger.warning("top artists (%s) failed: %s", time_range, exc)
        return []


async def _get_top_tracks(client: SpotifyClient, time_range: str) -> list[TrackData]:
    try:
        data = await client.get("/me/top/tracks", time_range=time_range, limit=_TOP_LIMIT)
        return [t for raw in data.get("items", []) if (t := _parse_track(raw))]
    except Exception as exc:
        logger.warning("top tracks (%s) failed: %s", time_range, exc)
        return []


async def _get_recently_played(client: SpotifyClient) -> list[TrackData]:
    try:
        data = await client.get("/me/player/recently-played", limit=50)
        tracks = []
        for item in data.get("items", []):
            raw_track = item.get("track") or {}
            t = _parse_track(raw_track)
            if t:
                tracks.append(t)
        return tracks
    except Exception as exc:
        logger.warning("recently played failed: %s", exc)
        return []


async def _get_saved_tracks(client: SpotifyClient) -> list[TrackData]:
    """Paginate through saved tracks (up to _SAVED_TRACK_PAGES pages)."""
    tracks: list[TrackData] = []
    try:
        for page in range(_SAVED_TRACK_PAGES):
            data = await client.get("/me/tracks", limit=50, offset=page * 50)
            items = data.get("items") or []
            for item in items:
                raw_track = (item.get("track") or {})
                t = _parse_track(raw_track)
                if t:
                    tracks.append(t)
            if not data.get("next"):
                break
    except Exception as exc:
        logger.warning("saved tracks failed at page %s: %s", len(tracks) // 50, exc)
    return tracks


async def _get_saved_albums(client: SpotifyClient) -> list[AlbumData]:
    """Paginate through saved albums (up to _SAVED_ALBUM_PAGES pages)."""
    albums: list[AlbumData] = []
    try:
        for page in range(_SAVED_ALBUM_PAGES):
            data = await client.get("/me/albums", limit=50, offset=page * 50)
            items = data.get("items") or []
            for item in items:
                raw_album = (item.get("album") or {})
                a = _parse_album(raw_album)
                if a:
                    albums.append(a)
            if not data.get("next"):
                break
    except Exception as exc:
        logger.warning("saved albums failed: %s", exc)
    return albums


async def _get_artist_albums(client: SpotifyClient, artist_id: str) -> list[AlbumData]:
    """Fetch a handful of studio albums for one artist."""
    try:
        data = await client.get(
            f"/artists/{artist_id}/albums",
            include_groups="album",
            limit=_ARTIST_ALBUMS_LIMIT,
            market="from_token",
        )
        albums = []
        for raw in data.get("items", []):
            a = _parse_album(raw)
            if a:
                albums.append(a)
        return albums
    except Exception as exc:
        logger.warning("artist albums (%s) failed: %s", artist_id, exc)
        return []


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def fetch_all(client: SpotifyClient) -> ListeningData:
    """
    Concurrently fetch all listening signals for the current user.

    Returns a ListeningData instance populated with whatever Spotify returned.
    Individual endpoint failures are logged and produce empty lists, so the
    recommender can still run with partial data.
    """
    logger.info("Fetching all listening signals from Spotify …")

    # --- Batch 1: independent calls that can run fully in parallel ---
    (
        long_artists,
        med_artists,
        short_artists,
        long_tracks,
        med_tracks,
        short_tracks,
        saved_albums,
        recently_played,
    ) = await asyncio.gather(
        _get_top_artists(client, "long_term"),
        _get_top_artists(client, "medium_term"),
        _get_top_artists(client, "short_term"),
        _get_top_tracks(client, "long_term"),
        _get_top_tracks(client, "medium_term"),
        _get_top_tracks(client, "short_term"),
        _get_saved_albums(client),
        _get_recently_played(client),
    )

    # --- Batch 2: saved tracks (paginated, one call chain) ---
    saved_tracks = await _get_saved_tracks(client)

    # --- Batch 3: artist albums for key artists ---
    # Prioritise short-term artists (freshest taste signal), fill with others
    seen_artist_ids: set[str] = set()
    key_artists: list[str] = []
    for artist_list in (short_artists, med_artists, long_artists):
        for a in artist_list:
            if a.artist_id not in seen_artist_ids:
                seen_artist_ids.add(a.artist_id)
                key_artists.append(a.artist_id)
            if len(key_artists) >= _KEY_ARTISTS_COUNT:
                break
        if len(key_artists) >= _KEY_ARTISTS_COUNT:
            break

    artist_album_lists = await asyncio.gather(
        *[_get_artist_albums(client, aid) for aid in key_artists]
    )
    artist_albums: dict[str, list[AlbumData]] = {
        aid: albums for aid, albums in zip(key_artists, artist_album_lists)
    }

    logger.info(
        "Signals fetched: %d LT artists, %d ST artists, %d saved albums, "
        "%d saved tracks, %d recently played, %d artist album entries",
        len(long_artists), len(short_artists), len(saved_albums),
        len(saved_tracks), len(recently_played), len(artist_albums),
    )

    return ListeningData(
        long_term_artists=long_artists,
        medium_term_artists=med_artists,
        short_term_artists=short_artists,
        long_term_tracks=long_tracks,
        medium_term_tracks=med_tracks,
        short_term_tracks=short_tracks,
        saved_albums=saved_albums,
        saved_tracks=saved_tracks,
        recently_played=recently_played,
        artist_albums=artist_albums,
    )
