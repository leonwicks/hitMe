"""User and SpotifyAccount repository functions."""

from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from models.db_models import User, SpotifyAccount


def get_by_spotify_id(db: Session, spotify_user_id: str) -> Optional[User]:
    return db.query(User).filter(User.spotify_user_id == spotify_user_id).first()


def get_by_id(db: Session, user_id: int) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


def upsert(
    db: Session,
    spotify_user_id: str,
    display_name: str,
) -> User:
    """Create or update a user by Spotify user ID."""
    user = get_by_spotify_id(db, spotify_user_id)
    if user is None:
        user = User(spotify_user_id=spotify_user_id, display_name=display_name)
        db.add(user)
        db.flush()
    else:
        user.display_name = display_name
    return user


def upsert_spotify_account(
    db: Session,
    user_id: int,
    access_token: str,
    refresh_token: Optional[str],
    expires_at: datetime,
    scopes: str,
) -> SpotifyAccount:
    """Create or update the SpotifyAccount for a user."""
    account = db.query(SpotifyAccount).filter(SpotifyAccount.user_id == user_id).first()
    if account is None:
        account = SpotifyAccount(
            user_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scopes=scopes,
        )
        db.add(account)
    else:
        account.access_token = access_token
        if refresh_token:
            account.refresh_token = refresh_token
        account.expires_at = expires_at
        account.scopes = scopes
    return account


def get_spotify_account(db: Session, user_id: int) -> Optional[SpotifyAccount]:
    return db.query(SpotifyAccount).filter(SpotifyAccount.user_id == user_id).first()
