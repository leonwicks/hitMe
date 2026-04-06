# hitMe

> One album. Just for you.

hitMe recommends a single album based on your live Spotify listening history.
No questionnaire, no ratings — just connect Spotify and get one album to listen to right now.

---

## Quick start

### 1. Prerequisites

- Python 3.12+
- A [Spotify Developer app](https://developer.spotify.com/dashboard) with `http://localhost:8000/auth/callback` added as a Redirect URI

### 2. Install

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your Spotify credentials and a random SECRET_KEY
```

### 4. Run database migrations

```bash
alembic upgrade head
```

### 5. Start the server

```bash
uvicorn main:app --reload
```

Open [http://localhost:8000](http://localhost:8000).

---

## How it works

### Stage 1 — Candidate generation

All data is fetched **live** from the Spotify Web API at request time and discarded after the response. Nothing is cached.

Sources:
- Saved albums (up to 100)
- Albums from top tracks across three time ranges (short / medium / long term)
- Albums from saved tracks (up to 200)
- Albums from recently played tracks (up to 50)
- Studio albums from your top 15 artists

After deduplication by album ID: ~50–150 candidates.

### Stage 2 — Ranking

Each candidate is scored using:

| Component | Weight |
|---|---|
| Artist affinity | 0.35 |
| Top track overlap | 0.30 |
| Saved track overlap | 0.20 |
| Recent play overlap | 0.20 |
| Saved album bonus | +0.40 |
| Overfamiliarity penalty | −0.35 |

**Artist affinity** combines:
- Long-term top artist rank (×1.00)
- Medium-term top artist rank (×0.80)
- Short-term top artist rank (×0.60)
- Recent play count for artist (×0.50)
- Saved track count for artist (×0.50)
- Has a saved album by this artist (×0.70)

**Cooldowns:**
- Same album: excluded for 30 days
- Same artist: −0.20 soft penalty for 7 days

### Discovery buckets

| Bucket | Meaning |
|---|---|
| **Favourite** | You know and love this album |
| **Discovery** | Strong artist, less-played album |
| **Rediscovery** | Saved but not played recently |

---

## Project structure

```
main.py               FastAPI app + startup
config.py             Settings (via pydantic-settings)
db.py                 SQLAlchemy engine + session factory

models/
  db_models.py        ORM models (users, spotify_accounts, recommendation_history)
  schemas.py          In-memory dataclasses (AlbumCandidate, ListeningData, …)

repositories/
  users.py            User + SpotifyAccount persistence
  recommendations.py  Recommendation history persistence

services/
  spotify_client.py   Authenticated HTTP client + token refresh
  spotify_fetcher.py  All Spotify endpoint calls (fetched live, not cached)
  candidate_generator.py  Stage 1: build candidate pool
  ranker.py           Stage 2: score and rank candidates
  explainer.py        Convert signals to human-readable explanation

api/
  auth.py             OAuth routes (/login, /auth/callback, /logout)
  pages.py            HTML page routes (/, /dashboard, /history)
  recommendations.py  POST /recommend pipeline coordinator
  _templates.py       Shared Jinja2 render helper

templates/            Jinja2 HTML templates
static/               CSS

alembic/              Database migrations
```

---

## Tuning

- **More diversity:** reduce `W_ARTIST_AFFINITY` in `ranker.py`, increase `W_RECENT_PLAY`
- **Deeper catalogue:** increase `_KEY_ARTISTS_COUNT` in `spotify_fetcher.py`
- **Stricter cooldown:** change `SAME_ALBUM_DAYS` in `ranker.py`
- **More candidates:** increase `_SAVED_TRACK_PAGES` / `_SAVED_ALBUM_PAGES`

---

## Manual test plan

1. **Home → login** — click "Connect with Spotify", verify redirect to Spotify auth
2. **Callback** — after authorising, verify redirect to `/dashboard`
3. **First recommendation** — click "Get my recommendation", wait for result
4. **Card display** — verify album art, title, artist, bucket badge, bullets, score breakdown
5. **Spotify link** — click "Open in Spotify", verify correct album opens
6. **History** — navigate to `/history`, verify the recommendation appears
7. **Cooldown** — get another recommendation immediately; verify a different album is returned
8. **Token refresh** — wait for token expiry (or manually expire it in the DB) and verify seamless refresh
9. **Logout** — click Log out, verify redirect to home and session is cleared
10. **Re-login** — log back in, verify history is preserved

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `SPOTIFY_CLIENT_ID` | — | Spotify app client ID |
| `SPOTIFY_CLIENT_SECRET` | — | Spotify app client secret |
| `SPOTIFY_REDIRECT_URI` | `http://localhost:8000/auth/callback` | OAuth redirect URI |
| `SECRET_KEY` | `change-me-in-production` | Session signing key |
| `DATABASE_URL` | `sqlite:///./hitme.db` | SQLAlchemy database URL |
