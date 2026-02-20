## Current user dependency + dashboard
from datetime import datetime, timezone, timedelta
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.deps import get_db
from app.db.models.session_token import SessionToken
from app.db.models.user import User
from app.auth.sessions import SESSION_COOKIE_NAME, hash_token
from app.settings import settings

class NotAuthenticated(Exception):
    pass

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw:
        raise NotAuthenticated()

    h = hash_token(raw)
    tok = (
        db.query(SessionToken)
        .filter(SessionToken.token_hash == h,
        SessionToken.revoked_at.is_(None))
        .first()
    )

    if not tok:
        raise NotAuthenticated()

    now = datetime.now(timezone.utc)
    # Absolute expiry
    if tok.expires_at <= now:
        raise NotAuthenticated()

    # Idle timeout (server-side)
    idle_deadline = tok.last_seen_at + timedelta(minutes=settings.session_idle_minutes)
    if idle_deadline <= now:
        # Revoke server-side so the token can't be reused
        tok.revoked_at = now
        db.commit()
        raise NotAuthenticated()

    # Update activity
    tok.last_seen_at = now
    db.commit()

    user = db.query(User).filter(User.id == tok.user_id).first()
    if not user or not user.is_active:
        raise NotAuthenticated()
    return user
    

