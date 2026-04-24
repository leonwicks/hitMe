"""Pydantic schemas for data transfer between layers."""

from __future__ import annotations
from dataclasses import dataclass, field


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
    total_tracks: int = 0


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
    long_term_top_track_count: int = 0
    saved_track_count: int = 0
    recent_play_count: int = 0
    total_tracks: int = 0               # 0 = unknown

    # Computed scores
    artist_affinity: float = 0.0
    album_score: float = 0.0
    bucket: str = "adjacent"

    # Discovery
    source: str = "known"               # "known" | "discovery"
    genre_overlap_score: float = 0.0    # set by discovery_generator

    # Mood (Phase 6) — separate scores per dimension
    mood_score: float = 0.5             # combined, kept for explanation/display
    vibe_score: float = 0.5             # set by mood_scorer (tone + energy axes)
    mode_score: float = 0.5             # set by mood_scorer (engagement axis)
    weight_score: float = 0.5           # set by mood_scorer (0=light genre, 1=heavy)

    # For explanation
    top_term_artist: str = ""   # "long" | "medium" | "short" | ""
    score_breakdown: dict = field(default_factory=dict)


@dataclass
class Explanation:
    summary: str
    bullets: list[str]


@dataclass
class QuestionnaireResponse:
    """User's mood/context from the step-through questionnaire."""
    vibe: str = ""              # "melancholy"|"energised"|"warm"|"unsettled"|"focused"|""
    listening_mode: str = ""    # "immersive"|"background"|"unwind"|""
    familiarity: str = "balanced"  # "familiar"|"rediscovery"|"new"|"balanced"
    nostalgia: int = 0          # 0=any | 1=2015+ | 2=2005-14 | 4=1980-95 | 5=pre-1980
    heaviness: int = 5          # 0=light genres … 10=heavy genres (rock/metal/dnb)
