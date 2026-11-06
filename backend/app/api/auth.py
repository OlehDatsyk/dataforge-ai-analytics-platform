"""Registration, login, sessions, profile, and password reset."""
from __future__ import annotations

import logging
import smtplib
from datetime import timedelta
from email.message import EmailMessage

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db, utcnow
from ..deps import client_ip, current_user, enforce_rate_limit
from ..models import PasswordResetToken, User, UserSession, Workspace, WorkspaceMember
from ..security import CSRF_COOKIE, SESSION_COOKIE, csrf_for_session, hash_password, hash_token, new_token, verify_password
from ..services.activity import audit

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger("dataforge.auth")
RESET_TTL = timedelta(hours=1)


def _strong_password(value: str) -> str:
    if len(value) < 10:
        raise ValueError("Password must be at least 10 characters.")
    if value.isdigit() or value.isalpha():
        raise ValueError("Password must mix letters with numbers or symbols.")
    return value


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(max_length=200)
    _password = field_validator("password")(_strong_password)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


class ProfileUpdate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)
    _password = field_validator("new_password")(_strong_password)


class ResetRequest(BaseModel):
    email: EmailStr


class ResetConfirm(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(max_length=200)
    _password = field_validator("new_password")(_strong_password)


def user_payload(db: Session, user: User) -> dict:
    members = db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id).order_by(WorkspaceMember.created_at)).all()
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "created_at": user.created_at,
        "workspaces": [{"id": m.workspace.id, "name": m.workspace.name, "role": m.role} for m in members],
    }


def _start_session(db: Session, response: Response, user: User) -> None:
    settings = get_settings()
    token = new_token()
    db.execute(delete(UserSession).where(UserSession.expires_at <= utcnow()))
    db.add(UserSession(user_id=user.id, token_hash=hash_token(token), expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours)))
    max_age = settings.session_ttl_hours * 3600
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/")
    # The CSRF token is readable by the page, which echoes it in a header on state-changing requests.
    response.set_cookie(CSRF_COOKIE, csrf_for_session(token), max_age=max_age, httponly=False, secure=settings.cookie_secure, samesite="lax", path="/")


@router.post("/register", status_code=201)
def register(body: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    enforce_rate_limit(request, "auth", get_settings().rate_limit_auth_per_minute)
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(email=email, full_name=body.full_name.strip(), password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    workspace = Workspace(name=f"{body.full_name.strip().split()[0]}'s Workspace", created_by=user.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    audit(db, "user.registered", workspace_id=workspace.id, user_id=user.id, entity_type="user", entity_id=user.id, ip=client_ip(request))
    _start_session(db, response, user)
    db.commit()
    return user_payload(db, user)


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    enforce_rate_limit(request, "auth", get_settings().rate_limit_auth_per_minute)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not verify_password(body.password, user.password_hash if user else None) or not user or not user.is_active:
        audit(db, "user.login_failed", ip=client_ip(request))
        db.commit()
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    user.last_login_at = utcnow()
    audit(db, "user.login", user_id=user.id, entity_type="user", entity_id=user.id, ip=client_ip(request))
    _start_session(db, response, user)
    db.commit()
    return user_payload(db, user)


@router.post("/logout")
def logout(request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == hash_token(token)))
    audit(db, "user.logout", user_id=user.id, entity_type="user", entity_id=user.id, ip=client_ip(request))
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return user_payload(db, user)


@router.patch("/me")
def update_profile(body: ProfileUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.full_name = body.full_name.strip()
    db.commit()
    return user_payload(db, user)


@router.post("/change-password")
def change_password(body: PasswordChange, request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="The current password is incorrect.")
    user.password_hash = hash_password(body.new_password)
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))  # sign out every other device
    audit(db, "user.password_changed", user_id=user.id, entity_type="user", entity_id=user.id, ip=client_ip(request))
    _start_session(db, response, user)
    db.commit()
    return {"ok": True}


def _send_reset_email(to_address: str, link: str) -> bool:
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_from:
        return False
    message = EmailMessage()
    message["Subject"] = "Reset your DataForge AI password"
    message["From"] = settings.smtp_from
    message["To"] = to_address
    message.set_content(f"Use this link within one hour to reset your password:\n\n{link}\n\nIf you did not request this, you can ignore this email.")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        return True
    except (smtplib.SMTPException, OSError):
        logger.error("Password reset email could not be sent")
        return False


@router.post("/password-reset/request")
def request_reset(body: ResetRequest, request: Request, db: Session = Depends(get_db)):
    """Always gives the same response, so it cannot be used to discover registered addresses."""
    settings = get_settings()
    enforce_rate_limit(request, "auth", settings.rate_limit_auth_per_minute)
    result: dict = {"message": "If that email has an account, a reset link is on its way."}
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user:
        token = new_token()
        db.add(PasswordResetToken(user_id=user.id, token_hash=hash_token(token), expires_at=utcnow() + RESET_TTL))
        audit(db, "user.password_reset_requested", user_id=user.id, entity_type="user", entity_id=user.id, ip=client_ip(request))
        db.commit()
        link = f"{settings.public_app_url.rstrip('/')}/reset-password?token={token}"
        delivered = _send_reset_email(user.email, link)
        if not delivered and not settings.is_production:
            # Local development has no mail server, so the link is returned directly.
            result["dev_reset_link"] = link
    if "dev_reset_link" not in result and not settings.is_production and not settings.smtp_host:
        result["dev_note"] = "E-mail is not configured in this environment."
    return result


@router.post("/password-reset/confirm")
def confirm_reset(body: ResetConfirm, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(request, "auth", get_settings().rate_limit_auth_per_minute)
    token = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(body.token)))
    if token is None or token.used_at is not None or token.expires_at <= utcnow():
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")
    user = db.get(User, token.user_id)
    user.password_hash = hash_password(body.new_password)
    token.used_at = utcnow()
    db.execute(update(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)).values(used_at=utcnow()))
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    audit(db, "user.password_reset", user_id=user.id, entity_type="user", entity_id=user.id, ip=client_ip(request))
    db.commit()
    return {"ok": True}
