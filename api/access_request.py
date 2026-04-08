"""
Access request route.

POST /request-access  → send notification email to developer, redirect home
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


def _send_access_request_email(first_name: str, last_name: str, email: str) -> None:
    """Send an access request notification to the developer's email via SMTP."""
    if not settings.notification_email or not settings.smtp_user or not settings.smtp_password:
        logger.warning(
            "Email not configured — skipping send. "
            "Set NOTIFICATION_EMAIL, SMTP_USER, SMTP_PASSWORD in .env"
        )
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"HitMe access request: {first_name} {last_name}"
    msg["From"] = settings.smtp_user
    msg["To"] = settings.notification_email

    body = (
        f"Someone has requested access to HitMe.\n\n"
        f"  First name : {first_name}\n"
        f"  Last name  : {last_name}\n"
        f"  Spotify email: {email}\n\n"
        f"Add this email to the approved users list in the Spotify Developer Dashboard:\n"
        f"https://developer.spotify.com/dashboard\n"
    )
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.sendmail(settings.smtp_user, settings.notification_email, msg.as_string())

    logger.info("Access request email sent for %s %s (%s)", first_name, last_name, email)


@router.post("/request-access")
async def request_access(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
):
    """Receive an access request form, send email to developer, redirect with confirmation."""
    first_name = first_name.strip()
    last_name = last_name.strip()
    email = email.strip()

    try:
        _send_access_request_email(first_name, last_name, email)
    except Exception as exc:
        logger.error("Failed to send access request email: %s", exc)
        return RedirectResponse("/?error=request_failed", status_code=303)

    return RedirectResponse("/?access_requested=1", status_code=303)
