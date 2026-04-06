import os
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8000/auth/callback")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SCOPES = "user-top-read"

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    token = request.session.get("access_token")
    if token:
        return RedirectResponse("/stats")
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/auth/login")
async def spotify_login(request: Request):
    params = {
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "scope": SCOPES,
    }
    from urllib.parse import urlencode
    url = f"{SPOTIFY_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url)


@app.get("/auth/spotify/callback")
async def spotify_callback(request: Request, code: str = None, error: str = None):
    if error or not code:
        return RedirectResponse("/?error=access_denied")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            SPOTIFY_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": SPOTIFY_REDIRECT_URI,
            },
            auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to exchange token")

    token_data = resp.json()
    request.session["access_token"] = token_data["access_token"]
    return RedirectResponse("/stats")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


async def fetch_top(token: str, item_type: str, time_range: str) -> list:
    """Fetch top 5 artists or tracks for a given time range."""
    url = f"{SPOTIFY_API_BASE}/me/top/{item_type}"
    params = {"time_range": time_range, "limit": 5}
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params, headers=headers)

    if resp.status_code == 401:
        return None  # token expired
    if resp.status_code != 200:
        return []

    items = resp.json().get("items", [])

    if item_type == "artists":
        return [
            {
                "name": a["name"],
                "image": a["images"][0]["url"] if a.get("images") else None,
                "url": a["external_urls"]["spotify"],
                "genres": ", ".join(a.get("genres", [])[:2]),
            }
            for a in items
        ]
    else:  # tracks
        return [
            {
                "name": t["name"],
                "artist": ", ".join(a["name"] for a in t["artists"]),
                "image": t["album"]["images"][0]["url"] if t["album"].get("images") else None,
                "url": t["external_urls"]["spotify"],
                "album": t["album"]["name"],
            }
            for t in items
        ]


@app.get("/stats", response_class=HTMLResponse)
async def stats(request: Request):
    token = request.session.get("access_token")
    if not token:
        return RedirectResponse("/")

    results = {}
    for time_range, label in [("long_term", "year"), ("short_term", "month")]:
        artists = await fetch_top(token, "artists", time_range)
        tracks = await fetch_top(token, "tracks", time_range)

        if artists is None or tracks is None:
            # Token expired
            request.session.clear()
            return RedirectResponse("/")

        results[label] = {"artists": artists, "tracks": tracks}

    return templates.TemplateResponse("stats.html", {"request": request, "results": results})
