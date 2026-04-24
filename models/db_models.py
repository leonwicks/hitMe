"""SQLAlchemy ORM models."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Text, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship

from db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    spotify_user_id = Column(String, unique=True, index=True, nullable=False)
    display_name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    spotify_account = relationship("SpotifyAccount", back_populates="user", uselist=False)
    recommendations = relationship("RecommendationHistory", back_populates="user", order_by="RecommendationHistory.recommendation_date.desc()")


class SpotifyAccount(Base):
    __tablename__ = "spotify_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text)
    expires_at = Column(DateTime)
    scopes = Column(String)

    user = relationship("User", back_populates="spotify_account")


class RecommendationHistory(Base):
    __tablename__ = "recommendation_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    recommendation_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    spotify_album_id = Column(String, nullable=False)
    album_name = Column(String, nullable=False)
    artist_name = Column(String, nullable=False)
    spotify_artist_id = Column(String)
    image_url = Column(String)
    spotify_url = Column(String)
    release_date = Column(String)
    bucket = Column(String)  # comfort | adjacent | rediscovery
    score = Column(Float)
    explanation_summary = Column(Text)
    explanation_bullets = Column(Text)   # JSON-encoded list[str]
    score_breakdown = Column(Text)       # JSON-encoded dict
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="recommendations")

    @property
    def bullets(self) -> list[str]:
        if not self.explanation_bullets:
            return []
        try:
            return json.loads(self.explanation_bullets)
        except (ValueError, TypeError):
            return []

    @property
    def breakdown(self) -> dict:
        if not self.score_breakdown:
            return {}
        try:
            return json.loads(self.score_breakdown)
        except (ValueError, TypeError):
            return {}


class Artist(Base):
    """
    Canonical artist record bridging Spotify and Last.fm.

    A row may exist with only lastfm_name (not yet matched to Spotify)
    or only spotify_artist_id (not yet enriched via Last.fm).
    """
    __tablename__ = "artists"

    id = Column(Integer, primary_key=True, index=True)
    spotify_artist_id = Column(String, unique=True, index=True)   # nullable until matched
    lastfm_name = Column(String, unique=True, index=True)         # nullable for Spotify-only artists
    name = Column(String, nullable=False)
    genres = Column(Text)              # JSON list[str] from Spotify
    genres_refreshed_at = Column(DateTime)
    similarity_refreshed_at = Column(DateTime)
    tags_refreshed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    tags = relationship("ArtistTag", back_populates="artist", cascade="all, delete-orphan")
    outgoing_edges = relationship(
        "ArtistSimilarityEdge",
        foreign_keys="ArtistSimilarityEdge.source_artist_id",
        back_populates="source_artist",
        cascade="all, delete-orphan",
    )


class ArtistSimilarityEdge(Base):
    """Directed similarity edge: source → target with a Last.fm similarity score."""
    __tablename__ = "artist_similarity_edges"
    __table_args__ = (UniqueConstraint("source_artist_id", "target_artist_id"),)

    id = Column(Integer, primary_key=True, index=True)
    source_artist_id = Column(Integer, ForeignKey("artists.id", ondelete="CASCADE"), nullable=False, index=True)
    target_artist_id = Column(Integer, ForeignKey("artists.id", ondelete="CASCADE"), nullable=False, index=True)
    similarity_score = Column(Float, nullable=False)
    refreshed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    source_artist = relationship("Artist", foreign_keys=[source_artist_id], back_populates="outgoing_edges")
    target_artist = relationship("Artist", foreign_keys=[target_artist_id])


class ArtistTag(Base):
    """Last.fm tag attached to an artist with a community weight."""
    __tablename__ = "artist_tags"
    __table_args__ = (UniqueConstraint("artist_id", "tag"),)

    id = Column(Integer, primary_key=True, index=True)
    artist_id = Column(Integer, ForeignKey("artists.id", ondelete="CASCADE"), nullable=False, index=True)
    tag = Column(String, nullable=False)
    weight = Column(Float, nullable=False, default=1.0)
    refreshed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    artist = relationship("Artist", back_populates="tags")


class AlbumTag(Base):
    """Last.fm tag attached to a specific album."""
    __tablename__ = "album_tags"
    __table_args__ = (UniqueConstraint("spotify_album_id", "tag"),)

    id = Column(Integer, primary_key=True, index=True)
    spotify_album_id = Column(String, nullable=False, index=True)
    tag = Column(String, nullable=False)
    weight = Column(Float, nullable=False, default=1.0)
    refreshed_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class UserTasteProfile(Base):
    """
    Persisted taste profile derived from a user's Spotify data + Last.fm graph.
    Rebuilt at most once per 24 hours.
    """
    __tablename__ = "user_taste_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    genre_weights = Column(Text)        # JSON dict[str, float]
    tag_weights = Column(Text)          # JSON dict[str, float]
    known_artist_ids = Column(Text)     # JSON list[str] of spotify_artist_ids
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User")

    @property
    def genre_weights_dict(self) -> dict:
        return json.loads(self.genre_weights) if self.genre_weights else {}

    @property
    def tag_weights_dict(self) -> dict:
        return json.loads(self.tag_weights) if self.tag_weights else {}

    @property
    def known_artist_ids_set(self) -> set:
        return set(json.loads(self.known_artist_ids)) if self.known_artist_ids else set()


# ---------------------------------------------------------------------------
# Catalogue — shared across all users
# ---------------------------------------------------------------------------

class Album(Base):
    """Canonical album record. Primary artist stored directly for fast lookup."""
    __tablename__ = "albums"

    id = Column(Integer, primary_key=True, index=True)
    spotify_album_id = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, nullable=False)
    primary_artist_id = Column(Integer, ForeignKey("artists.id", ondelete="SET NULL"))
    release_date = Column(String)
    image_url = Column(String)
    spotify_url = Column(String)
    album_type = Column(String)     # album | single | compilation
    total_tracks = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    primary_artist = relationship("Artist", foreign_keys=[primary_artist_id])


class Track(Base):
    """Canonical track record."""
    __tablename__ = "tracks"

    id = Column(Integer, primary_key=True, index=True)
    spotify_track_id = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, nullable=False)
    album_id = Column(Integer, ForeignKey("albums.id", ondelete="SET NULL"))
    primary_artist_id = Column(Integer, ForeignKey("artists.id", ondelete="SET NULL"))
    duration_ms = Column(Integer)
    explicit = Column(Boolean)
    track_number = Column(Integer)
    popularity = Column(Integer)
    preview_url = Column(String)
    spotify_url = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    album = relationship("Album", foreign_keys=[album_id])
    primary_artist = relationship("Artist", foreign_keys=[primary_artist_id])


class ArtistAlbumLink(Base):
    """Associates an artist with albums in their discography."""
    __tablename__ = "artist_album_links"
    __table_args__ = (UniqueConstraint("artist_id", "album_id"),)

    id = Column(Integer, primary_key=True, index=True)
    artist_id = Column(Integer, ForeignKey("artists.id", ondelete="CASCADE"), nullable=False, index=True)
    album_id = Column(Integer, ForeignKey("albums.id", ondelete="CASCADE"), nullable=False, index=True)

    artist = relationship("Artist")
    album = relationship("Album")


# ---------------------------------------------------------------------------
# Per-user listening signal snapshots
# ---------------------------------------------------------------------------

class UserSyncStatus(Base):
    """
    Tracks when each Spotify signal type was last fetched for a user.
    One row per user. NULL means never fetched.
    """
    __tablename__ = "user_sync_status"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    top_artists_synced_at = Column(DateTime)
    top_tracks_synced_at = Column(DateTime)
    saved_albums_synced_at = Column(DateTime)
    saved_tracks_synced_at = Column(DateTime)
    artist_albums_synced_at = Column(DateTime)

    user = relationship("User")


class UserTopArtist(Base):
    """
    Current top-artist snapshot for a user + time range.
    Fully replaced on each sync — not a history table.
    """
    __tablename__ = "user_top_artists"
    __table_args__ = (UniqueConstraint("user_id", "artist_id", "time_range"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    artist_id = Column(Integer, ForeignKey("artists.id", ondelete="CASCADE"), nullable=False)
    time_range = Column(String, nullable=False)   # short_term | medium_term | long_term
    rank = Column(Integer, nullable=False)

    artist = relationship("Artist")


class UserTopTrack(Base):
    """Current top-track snapshot for a user + time range."""
    __tablename__ = "user_top_tracks"
    __table_args__ = (UniqueConstraint("user_id", "track_id", "time_range"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    track_id = Column(Integer, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False)
    time_range = Column(String, nullable=False)
    rank = Column(Integer, nullable=False)

    track = relationship("Track")


class UserSavedAlbum(Base):
    """Albums currently in the user's Spotify library."""
    __tablename__ = "user_saved_albums"
    __table_args__ = (UniqueConstraint("user_id", "album_id"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    album_id = Column(Integer, ForeignKey("albums.id", ondelete="CASCADE"), nullable=False)
    saved_at = Column(DateTime)   # when the user saved it on Spotify

    album = relationship("Album")


class UserSavedTrack(Base):
    """Tracks currently in the user's Spotify library."""
    __tablename__ = "user_saved_tracks"
    __table_args__ = (UniqueConstraint("user_id", "track_id"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    track_id = Column(Integer, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False)
    saved_at = Column(DateTime)

    track = relationship("Track")
