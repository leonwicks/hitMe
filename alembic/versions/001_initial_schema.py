"""Initial schema: users, spotify_accounts, recommendation_history.

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("spotify_user_id", sa.String, unique=True, nullable=False, index=True),
        sa.Column("display_name", sa.String),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "spotify_accounts",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("access_token", sa.Text, nullable=False),
        sa.Column("refresh_token", sa.Text),
        sa.Column("expires_at", sa.DateTime),
        sa.Column("scopes", sa.String),
    )

    op.create_table(
        "recommendation_history",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("recommendation_date", sa.DateTime, nullable=False),
        sa.Column("spotify_album_id", sa.String, nullable=False),
        sa.Column("album_name", sa.String, nullable=False),
        sa.Column("artist_name", sa.String, nullable=False),
        sa.Column("spotify_artist_id", sa.String),
        sa.Column("image_url", sa.String),
        sa.Column("spotify_url", sa.String),
        sa.Column("release_date", sa.String),
        sa.Column("bucket", sa.String),
        sa.Column("score", sa.Float),
        sa.Column("explanation_summary", sa.Text),
        sa.Column("explanation_bullets", sa.Text),
        sa.Column("score_breakdown", sa.Text),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("recommendation_history")
    op.drop_table("spotify_accounts")
    op.drop_table("users")
