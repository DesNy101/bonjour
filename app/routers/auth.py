import smtplib
from email.message import EmailMessage
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request, Response, HTTPException
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import get_db
from app.dependencies.auth import COOKIE, CSRF_COOKIE, current_principal, _load
from app.middleware.security import limiter
from app.models import User, Role, Customer, AuthSession, PasswordReset, Notification
from app.schemas.common import LoginIn, RegisterIn, PasswordChangeIn, ForgotIn, ResetIn, ProfileIn, AddressIn
from app.models import CustomerAddress
from app.security import (verify_password, hash_password, password_problem, new_token, token_hash, in_hours, now)
from app.serializers import user_out, customer_out
from app.services import audit, access, settings_service
from datetime import timedelta

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
MAX_FAILS = 5


def _client_ip(request: Request) -> str:
    return (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip()


def _start_session(db, request, response, user) -> str:
    cfg = get_settings()
    token, csrf = new_token(), new_token()
    db.add(AuthSession(token_hash=token_hash(token), csrf_token=csrf, user_id=user.id, expires_at=in_hours(cfg.session_hours),
                       ip=_client_ip(request), user_agent=request.headers.get("user-agent", "")[:300]))
    max_age = int(cfg.session_hours * 3600)
    response.set_cookie(COOKIE, token, max_age=max_age, httponly=True, samesite="lax", secure=cfg.secure_cookies, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, samesite="lax", secure=cfg.secure_cookies, path="/")
    return csrf


def _me(db, user):
    pr = access.build_principal(db, user)
    d = user_out(user, pr.permissions)
    d["branch_ids"] = None if pr.branch_ids is None else sorted(pr.branch_ids)
    if not user.role.is_staff:
        c = db.query(Customer).filter(Customer.user_id == user.id).first()
        d["customer"] = customer_out(c) if c else None
    return d


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    ip = _client_ip(request)
    if not limiter.check(f"login:{ip}", 30, 300) or not limiter.check(f"login:{ip}:{email}", 8, 300):
        raise HTTPException(429, "Too many login attempts. Please wait a few minutes and try again.")
    user = db.query(User).filter(User.email == email).first()
    if user and user.locked_until and user.locked_until > now():
        raise HTTPException(423, "Account temporarily locked after repeated failed attempts. Try again later.")
    ok = verify_password(body.password, user.password_hash if user else None)
    if not user or not ok or not user.is_active:
        if user and not ok:
            user.failed_logins = (user.failed_logins or 0) + 1
            if user.failed_logins >= MAX_FAILS:
                user.locked_until = now() + timedelta(minutes=15)
                user.failed_logins = 0
            audit.log(db, user, "login_failed", "user", user.id, request=request)
            db.commit()
        raise HTTPException(401, "Incorrect email or password.")
    user.failed_logins, user.locked_until, user.last_login = 0, None, now()
    csrf = _start_session(db, request, response, user)
    audit.log(db, user, "login", "user", user.id, request=request)
    db.commit()
    return {"user": _me(db, user), "csrf_token": csrf}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE)
    if token:
        s = db.query(AuthSession).filter(AuthSession.token_hash == token_hash(token)).first()
        if s:
            s.revoked = True
            audit.log(db, db.get(User, s.user_id), "logout", "user", s.user_id, request=request)
            db.commit()
    response.delete_cookie(COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE)
    user = _load(request, db)
    if not user:
        raise HTTPException(401, "Not signed in.")
    s = db.query(AuthSession).filter(AuthSession.token_hash == token_hash(token)).first()
    return {"user": _me(db, user), "csrf_token": s.csrf_token}


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if not limiter.check(f"register:{_client_ip(request)}", 10, 3600):
        raise HTTPException(429, "Too many registrations from this address.")
    email = body.email.lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "An account with this email already exists.")
    problem = password_problem(body.password)
    if problem:
        raise HTTPException(400, problem)
    role = db.query(Role).filter(Role.key == "customer").one()
    u = User(email=email, full_name=body.name, phone=body.phone, password_hash=hash_password(body.password), role_id=role.id)
    db.add(u)
    db.flush()
    c = db.query(Customer).filter(Customer.phone == body.phone, Customer.user_id.is_(None)).first() if body.phone else None
    if c:  # claim an earlier guest record so order history carries over
        c.user_id, c.is_guest, c.email = u.id, False, email
    else:
        c = Customer(user_id=u.id, name=body.name, phone=body.phone, email=email, is_guest=False,
                     is_demo=settings_service.is_demo_mode(db))
        db.add(c)
    db.flush()
    db.refresh(u)
    csrf = _start_session(db, request, response, u)
    audit.log(db, u, "customer_registered", "user", u.id, request=request)
    db.commit()
    return {"user": _me(db, u), "csrf_token": csrf}


@router.post("/change-password")
def change_password(body: PasswordChangeIn, request: Request, p=Depends(current_principal), db: Session = Depends(get_db)):
    u = p.user
    if not verify_password(body.current_password, u.password_hash):
        raise HTTPException(400, "Current password is incorrect.")
    problem = password_problem(body.new_password)
    if problem:
        raise HTTPException(400, problem)
    u.password_hash = hash_password(body.new_password)
    u.must_change_password = False
    # revoke all other sessions
    token = request.cookies.get(COOKIE)
    for s in db.query(AuthSession).filter(AuthSession.user_id == u.id, AuthSession.revoked == False):  # noqa
        if s.token_hash != token_hash(token):
            s.revoked = True
    audit.log(db, u, "password_changed", "user", u.id, request=request)
    db.commit()
    return {"ok": True}


def _send_email(to: str, subject: str, body: str) -> bool:
    cfg = get_settings()
    if not cfg.smtp_host:
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg.smtp_user or "no-reply@bonjour", to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=10) as s:
            s.starttls()
            if cfg.smtp_user:
                s.login(cfg.smtp_user, cfg.smtp_password)
            s.send_message(msg)
        return True
    except Exception:
        return False


@router.post("/forgot-password")
def forgot(body: ForgotIn, request: Request, db: Session = Depends(get_db)):
    if not limiter.check(f"forgot:{_client_ip(request)}", 5, 3600):
        raise HTTPException(429, "Too many requests. Try again later.")
    cfg = get_settings()
    generic = {"ok": True, "message": "If that email is registered, reset instructions have been sent."}
    u = db.query(User).filter(User.email == body.email.lower(), User.is_active == True).first()  # noqa
    if not u:
        return generic
    token = new_token()
    db.add(PasswordReset(user_id=u.id, token_hash=token_hash(token), expires_at=in_hours(1)))
    audit.log(db, u, "password_reset_requested", "user", u.id, request=request)
    db.commit()
    link = f"{cfg.public_base_url}/#/reset/{token}"
    sent = _send_email(u.email, "Reset your Bonjour Bakery password", f"Use this link within 1 hour:\n{link}")
    if not sent and not cfg.is_production:
        generic["dev_reset_token"] = token  # only outside production, when email is not configured
    if not sent:
        generic["note"] = "Email is not configured on this server. Ask an administrator to reset your password."
    return generic


@router.post("/reset-password")
def reset(body: ResetIn, request: Request, db: Session = Depends(get_db)):
    pr = db.query(PasswordReset).filter(PasswordReset.token_hash == token_hash(body.token)).first()
    if not pr or pr.used or pr.expires_at < now():
        raise HTTPException(400, "This reset link is invalid or has expired.")
    problem = password_problem(body.new_password)
    if problem:
        raise HTTPException(400, problem)
    u = db.get(User, pr.user_id)
    u.password_hash = hash_password(body.new_password)
    u.must_change_password = False
    pr.used = True
    for s in db.query(AuthSession).filter(AuthSession.user_id == u.id):
        s.revoked = True
    audit.log(db, u, "password_reset", "user", u.id, request=request)
    db.commit()
    return {"ok": True}


# ----- customer self-service profile -----
@router.patch("/profile")
def update_profile(body: ProfileIn, p=Depends(current_principal), db: Session = Depends(get_db)):
    u = p.user
    if body.name:
        u.full_name = body.name
    if body.phone is not None:
        u.phone = body.phone
    c = db.query(Customer).filter(Customer.user_id == u.id).first()
    if c:
        if body.name:
            c.name = body.name
        if body.phone is not None:
            c.phone = body.phone
        if body.preferred_branch_id is not None:
            c.preferred_branch_id = body.preferred_branch_id
    db.commit()
    return _me(db, u)


@router.post("/addresses", status_code=201)
def add_address(body: AddressIn, p=Depends(current_principal), db: Session = Depends(get_db)):
    c = db.query(Customer).filter(Customer.user_id == p.user.id).first()
    if not c:
        raise HTTPException(400, "Only customer accounts have saved addresses.")
    if body.is_default:
        for a in c.addresses:
            a.is_default = False
    db.add(CustomerAddress(customer_id=c.id, label=body.label, address=body.address, lga=body.lga, is_default=body.is_default or not c.addresses))
    db.commit()
    db.refresh(c)
    return customer_out(c)


@router.delete("/addresses/{aid}")
def del_address(aid: int, p=Depends(current_principal), db: Session = Depends(get_db)):
    c = db.query(Customer).filter(Customer.user_id == p.user.id).first()
    a = db.get(CustomerAddress, aid)
    if not c or not a or a.customer_id != c.id:
        raise HTTPException(404, "Address not found.")
    db.delete(a)
    db.commit()
    return {"ok": True}
