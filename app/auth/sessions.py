## Session management utilities

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

SESSION_COOKIE_NAME = "cc_session"
ABSOLUTE_DAYS = 7

def new_raw_token() -> str:
    return secrets.token_urlsafe(32)

def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def absolute_expiry(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now + timedelta(days=ABSOLUTE_DAYS)