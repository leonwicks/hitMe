"""Pydantic schemas for data transfer between layers."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ArtistData:
    """A Spotify artist with just the fields we need."""
    artist_id: str
    artist_name: str


@dataclass
class TrackData:
    """A Spotify track with album info."""
    track_id: str
    track_name: str
    album_id: str
    album_name: str
    artist_id: str       # primary artist
    artist_name: str
    image_url: str
    spotify_url: str
    release_date: str = ""


@dataclass
class AlbumData:
    """A Spotify album."""
    album_id: str
    album_name: str
    artist_id: str
    artist_name: str
    image_url: str
    spotify_url: str
    release_date: str = ""


@dataclass
class ListeningData:
    """All raw listening signals fetched from Spotify."""
    long_term_artists: list[ArtistData] = field(default_factory=list)
    medium_term_artists: list[ArtistData] = field(default_factory=list)
    short_term_artists: list[ArtistData] = field(default_factory=list)
    long_term_tracks: list[TrackData] = field(default_factory=list)
    medium_term_tracks: list[TrackData] = field(default_factory=list)
    short_term_tracks: list[TrackData] = field(default_factory=list)
    saved_albums: list[AlbumData] = field(default_factory=list)
    saved_tracks: list[TrackData] = field(default_factory=list)
    recently_played: list[TrackData] = field(default_factory=list)
    artist_albums: dict[str, list[AlbumData]] = field(default_factory=dict)


@dataclass
class AlbumCandidate:
    """A ranked album candidate with all computed signals."""
    album_id: str
    album_name: str
    artist_id: str
    artist_name: str
    image_url: str
    spotify_url: str
    release_date: str

    # Raw signal counts
    is_saved_album: bool = False
    top_track_count: int = 0
    saved_track_count: int = 0
    recent_play_count: int = 0

    # Computed scores
    artist_affinity: float = 0.0
    album_score: float = 0.0
    bucket: str = "adjacent"

    # For explanation
    top_term_artist: str = ""   # "long" | "medium" | "short" | ""
    score_breakdown: dict = field(default_factory=dict)


@dataclass
class Explanation:
    summary: str
    bullets: list[str]
