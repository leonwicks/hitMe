"""SQLAlchemy ORM models."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Text, UniqueConstraint
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
