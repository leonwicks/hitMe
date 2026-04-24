"""
Last.fm API client.

Read-only — only needs an API key (no OAuth).
All methods return parsed dicts; callers handle persistence.
"""

import asyncio
import logging
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

_BASE = "https://ws.audioscrobbler.com/2.0/"
_TIMEOUT = 10.0
_SEMAPHORE = asyncio.Semaphore(5)   # max 5 concurrent Last.fm requests


class LastFmError(Exception):
    pass


async def _get(params: dict) -> dict:
    """Raw GET to Last.fm. Raises LastFmError on API-level failures."""
    async with _SEMAPHORE:
        params = {
            "api_key": settings.lastfm_api_key,
            "format": "json",
            **params,
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(_BASE, params=params)
        if resp.status_code == 429:
            logger.warning("Last.fm rate-limited — backing off 2s")
            await asyncio.sleep(2)
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(_BASE, params=params)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise LastFmError(f"Last.fm error {data['error']}: {data.get('message', '')}")
        return data


async def get_similar_artists(artist_name: str, limit: int = 50) -> list[dict]:
    """
    Return up to `limit` similar artists for `artist_name`.

    Each dict has keys: name, match (similarity 0–1).
    Returns [] on any error so callers can continue.
    """
    try:
        data = await _get({
            "method": "artist.getSimilar",
            "artist": artist_name,
            "limit": limit,
            "autocorrect": 1,
        })
        items = data.get("similarartists", {}).get("artist", [])
        return [
            {"name": a["name"], "match": float(a.get("match", 0))}
            for a in items
            if isinstance(a, dict) and a.get("name")
        ]
    except Exception as exc:
        logger.warning("getSimilar failed for '%s': %s", artist_name, exc)
        return []


async def get_artist_tags(artist_name: str, limit: int = 15) -> list[dict]:
    """
    Return top tags for `artist_name`.

    Each dict has keys: name, count (community tag count, 0–100).
    """
    try:
        data = await _get({
            "method": "artist.getTopTags",
            "artist": artist_name,
            "autocorrect": 1,
        })
        items = data.get("toptags", {}).get("tag", [])[:limit]
        return [
            {"name": t["name"].lower().strip(), "count": int(t.get("count", 0))}
            for t in items
            if isinstance(t, dict) and t.get("name")
        ]
    except Exception as exc:
        logger.warning("getTopTags failed for '%s': %s", artist_name, exc)
        return []


async def get_album_tags(artist_name: str, album_name: str, limit: int = 10) -> list[dict]:
    """Return top tags for a specific album."""
    try:
        data = await _get({
            "method": "album.getTopTags",
            "artist": artist_name,
            "album": album_name,
            "autocorrect": 1,
        })
        items = data.get("toptags", {}).get("tag", [])[:limit]
        return [
            {"name": t["name"].lower().strip(), "count": int(t.get("count", 0))}
            for t in items
            if isinstance(t, dict) and t.get("name")
        ]
    except Exception as exc:
        logger.warning("album.getTopTags failed for '%s / %s': %s", artist_name, album_name, exc)
        return []
