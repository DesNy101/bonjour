from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import Notification
from app.services import access, settings_service


def notify_user(db: Session, user_id: int, title: str, body: str = "", link: str = "", kind: str = "info"):
    db.add(Notification(user_id=user_id, title=title, body=body, link=link, kind=kind))


def notify_permission(db: Session, perm: str, title: str, body: str = "", link: str = "", kind: str = "info",
                      branch_id: int | None = None, exclude_user_id: int | None = None):
    for u in access.users_with_permission(db, perm, branch_id):
        if u.id != exclude_user_id:
            notify_user(db, u.id, title, body, link, kind)


def notify_customer(db: Session, customer, title: str, body: str = "", link: str = "", kind: str = "order"):
    """In-app always. Email/SMS/WhatsApp are queued only when enabled AND provider credentials exist (otherwise 'not_configured')."""
    if customer is None:
        return
    db.add(Notification(customer_id=customer.id, user_id=customer.user_id, title=title, body=body, link=link, kind=kind))
    cfg = get_settings()
    prefs = settings_service.all_settings(db)
    if prefs.get("notify_email") and customer.email:
        db.add(Notification(customer_id=customer.id, title=title, body=body, kind=kind, channel="email", delivery_status="queued" if cfg.smtp_host else "not_configured"))
    if prefs.get("notify_sms") and customer.phone:
        db.add(Notification(customer_id=customer.id, title=title, body=body, kind=kind, channel="sms", delivery_status="queued" if cfg.sms_provider_key else "not_configured"))
    if prefs.get("notify_whatsapp") and customer.phone:
        db.add(Notification(customer_id=customer.id, title=title, body=body, kind=kind, channel="whatsapp", delivery_status="queued" if cfg.whatsapp_provider_key else "not_configured"))
