from fastapi import Request
from sqlalchemy.orm import Session
from app.models import AuditLog


def log(db: Session, user, action: str, entity: str = "", entity_id="", details: dict | None = None, request: Request | None = None):
    ip = ""
    if request is not None and request.client:
        ip = request.headers.get("x-forwarded-for", request.client.host).split(",")[0].strip()
    db.add(AuditLog(user_id=getattr(user, "id", None), user_label=getattr(user, "email", "") or "system",
                    action=action, entity=entity, entity_id=str(entity_id), details=details or {}, ip=ip))
