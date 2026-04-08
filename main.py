"""
HitMe — entry point.

Wires together FastAPI, middleware, static files, and all routers.
Run with:  uvicorn main:app --reload
"""

import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from config import settings
import models.db_models  # noqa: F401 — imported for side-effects (registers models for Alembic)
from api import auth, pages, recommendations, access_request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)

app = FastAPI(title="HitMe", docs_url=None, redoc_url=None)

# --- Middleware ---
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="hitme_session",
    max_age=60 * 60 * 24 * 30,  # 30 days
    https_only=False,            # set True behind HTTPS in production
)

# --- Static files ---
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Routers ---
app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(recommendations.router)
app.include_router(access_request.router)


@app.on_event("startup")
async def on_startup() -> None:
    """Run on server start. Tables are managed by Alembic — see README."""
    pass
