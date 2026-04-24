"""Add music graph tables: artists, similarity edges, tags, taste profiles.

Revision ID: 002
Revises: 001
Create Date: 2026-04-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "artists",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("spotify_artist_id", sa.String, unique=True, index=True),
        sa.Column("lastfm_name", sa.String, unique=True, index=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("genres", sa.Text),
        sa.Column("genres_refreshed_at", sa.DateTime),
        sa.Column("similarity_refreshed_at", sa.DateTime),
        sa.Column("tags_refreshed_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "artist_similarity_edges",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_artist_id", sa.Integer, sa.ForeignKey("artists.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("target_artist_id", sa.Integer, sa.ForeignKey("artists.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("similarity_score", sa.Float, nullable=False),
        sa.Column("refreshed_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("source_artist_id", "target_artist_id"),
    )

    op.create_table(
        "artist_tags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("artist_id", sa.Integer, sa.ForeignKey("artists.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("tag", sa.String, nullable=False),
        sa.Column("weight", sa.Float, nullable=False, default=1.0),
        sa.Column("refreshed_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("artist_id", "tag"),
    )

    op.create_table(
        "album_tags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("spotify_album_id", sa.String, nullable=False, index=True),
        sa.Column("tag", sa.String, nullable=False),
        sa.Column("weight", sa.Float, nullable=False, default=1.0),
        sa.Column("refreshed_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("spotify_album_id", "tag"),
    )

    op.create_table(
        "user_taste_profiles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("genre_weights", sa.Text),
        sa.Column("tag_weights", sa.Text),
        sa.Column("known_artist_ids", sa.Text),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_taste_profiles")
    op.drop_table("album_tags")
    op.drop_table("artist_tags")
    op.drop_table("artist_similarity_edges")
    op.drop_table("artists")
