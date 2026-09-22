"""Jitsi room names + JWT tokens for bot-issued calls.

Tokens are HS256 with the claims the docker-jitsi-meet prosody
token_verification module expects (stable-11248):
  aud=jitsi, iss=lessons, sub=meet.jitsi (the XMPP domain),
  room=<room>, exp=<deadline>, context.user={id, name, moderator}.

Never log tokens: callers must pass them only into Telegram button URLs.
"""

import logging
import os
import secrets
import time

logger = logging.getLogger(__name__)

JWT_ISSUER = "lessons"
JWT_AUDIENCE = "jitsi"
JWT_SUBJECT = "meet.jitsi"  # must equal the XMPP domain (XMPP_DOMAIN)

MEET_JOIN_WINDOW_SEC = 300  # 5 minutes of open joins per /meet (Phase 1)


def get_config():
    """(domain, secret) from server .env. Empty strings when unset."""
    domain = (os.environ.get("JITSI_DOMAIN") or "").strip().strip("/")
    secret = os.environ.get("JITSI_JWT_SECRET") or ""
    return domain, secret


def is_configured():
    domain, secret = get_config()
    return bool(domain and secret)


def new_room_name(prefix="lesson-"):
    """Random room slug, e.g. lesson-a1b2c3d4e5f6 (token_urlsafe(6) is 8 chars)."""
    return f"{prefix}{secrets.token_urlsafe(6).lower()}"


def sanitize_room_name(raw, prefix="room-"):
    """Keep a user-given name Jitsi-safe; fall back to a random one."""
    cleaned = "".join(
        ch.lower() if (ch.isalnum() or ch in "-_.") else "-"
        for ch in (raw or "").strip()
    ).strip("-_.")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    if not cleaned:
        return new_room_name(prefix)
    return cleaned[:64]


def make_jwt(room, user_id, display_name, moderator, exp_epoch):
    """Mint an HS256 JWT for one room. Raises RuntimeError when unconfigured."""
    try:
        import jwt
    except ImportError as exc:
        raise RuntimeError("PyJWT is not installed (add PyJWT to requirements.txt)") from exc
    domain, secret = get_config()
    if not secret:
        raise RuntimeError("JITSI_JWT_SECRET is not set")
    now = int(time.time())
    payload = {
        "aud": JWT_AUDIENCE,
        "iss": JWT_ISSUER,
        "sub": JWT_SUBJECT,
        "room": room,
        "exp": int(exp_epoch),
        "iat": now,
        "context": {
            "user": {
                "id": str(user_id),
                "name": (display_name or "")[:64],
                "moderator": bool(moderator),
            }
        },
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def meet_url(room, token):
    """Guest/moderator join URL for a token. Domain only, never log the result."""
    domain, _ = get_config()
    return f"https://{domain}/{room}?jwt={token}"
