# Authentication routes (register/login/logout)
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.deps import get_db
from app.db.models.user import User
from app.db.models.session_token import SessionToken
from app.auth.hashing import hash_password, verify_password
from app.auth.sessions import SESSION_COOKIE_NAME, new_raw_token, hash_token, absolute_expiry
from fastapi.templating import Jinja2Templates

from app.settings import settings

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()

@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@router.post("/register")
def register(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    email_norm = email.strip().lower()
    exists = db.query(User).filter(User.email == email_norm).first()
    if exists:
        return RedirectResponse(url="/register?error=exists", status_code=303)
    
    user = User(email=email_norm, password_hash=hash_password((password)))
    db.add(user)
    db.commit()
    return RedirectResponse(url="/login?registered=1", status_code=303)

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/login")
def login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    email_norm = email.strip().lower()
    user = db.query(User).filter(User.email == email_norm).first()
    if not user or not verify_password(password, user.password_hash):
        return RedirectResponse(url="/login?error=bad_credentials",
        status_code=303)
    
    raw = new_raw_token()
    tok = SessionToken(
        user_id=user.id,
        token_hash=hash_token(raw),
        expires_at=absolute_expiry(),
        last_seen_at=datetime.now(timezone.utc),
    )
    db.add(tok)
    db.commit()

    resp = RedirectResponse(url="/dashboard", status_code=303)
    # Cookie security flags: httpOnly always; secure=True in prod over HTTPS
    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw,
        httponly=True,
        secure=(settings.env == "prod"),  # Set to True in production with HTTPS
        samesite="lax",
        max_age=60 * 60 * 24 * settings.session_absolute_days,
        path="/",
    )
    return resp

@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if raw:
        h = hash_token(raw)
        tok = db.query(SessionToken).filter(SessionToken.token_hash == h,
        SessionToken.revoked_at.is_(None)).first()
        if tok:
            tok.revoked_at = datetime.now(timezone.utc)
            db.commit()

    resp = RedirectResponse(url="/login?logged_out=1", status_code=303)
    resp.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return resp



