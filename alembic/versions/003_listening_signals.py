"""Add persisted listening signal tables.

Revision ID: 003
Revises: 002
Create Date: 2026-04-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Catalogue ---
    op.create_table(
        "albums",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("spotify_album_id", sa.String, unique=True, nullable=False, index=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("primary_artist_id", sa.Integer, sa.ForeignKey("artists.id", ondelete="SET NULL")),
        sa.Column("release_date", sa.String),
        sa.Column("image_url", sa.String),
        sa.Column("spotify_url", sa.String),
        sa.Column("album_type", sa.String),
        sa.Column("total_tracks", sa.Integer),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "tracks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("spotify_track_id", sa.String, unique=True, nullable=False, index=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("album_id", sa.Integer, sa.ForeignKey("albums.id", ondelete="SET NULL")),
        sa.Column("primary_artist_id", sa.Integer, sa.ForeignKey("artists.id", ondelete="SET NULL")),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("explicit", sa.Boolean),
        sa.Column("track_number", sa.Integer),
        sa.Column("popularity", sa.Integer),
        sa.Column("preview_url", sa.String),
        sa.Column("spotify_url", sa.String),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "artist_album_links",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("artist_id", sa.Integer, sa.ForeignKey("artists.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("album_id", sa.Integer, sa.ForeignKey("albums.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.UniqueConstraint("artist_id", "album_id"),
    )

    # --- User sync tracking ---
    op.create_table(
        "user_sync_status",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("top_artists_synced_at", sa.DateTime),
        sa.Column("top_tracks_synced_at", sa.DateTime),
        sa.Column("saved_albums_synced_at", sa.DateTime),
        sa.Column("saved_tracks_synced_at", sa.DateTime),
        sa.Column("artist_albums_synced_at", sa.DateTime),
    )

    # --- User signal snapshots ---
    op.create_table(
        "user_top_artists",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("artist_id", sa.Integer, sa.ForeignKey("artists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("time_range", sa.String, nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.UniqueConstraint("user_id", "artist_id", "time_range"),
    )

    op.create_table(
        "user_top_tracks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("track_id", sa.Integer, sa.ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("time_range", sa.String, nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.UniqueConstraint("user_id", "track_id", "time_range"),
    )

    op.create_table(
        "user_saved_albums",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("album_id", sa.Integer, sa.ForeignKey("albums.id", ondelete="CASCADE"), nullable=False),
        sa.Column("saved_at", sa.DateTime),
        sa.UniqueConstraint("user_id", "album_id"),
    )

    op.create_table(
        "user_saved_tracks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("track_id", sa.Integer, sa.ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("saved_at", sa.DateTime),
        sa.UniqueConstraint("user_id", "track_id"),
    )


def downgrade() -> None:
    op.drop_table("user_saved_tracks")
    op.drop_table("user_saved_albums")
    op.drop_table("user_top_tracks")
    op.drop_table("user_top_artists")
    op.drop_table("user_sync_status")
    op.drop_table("artist_album_links")
    op.drop_table("tracks")
    op.drop_table("albums")
