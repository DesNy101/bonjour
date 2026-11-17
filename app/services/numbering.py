from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.utils import common
from app.services import settings_service


def next_seq(db: Session, key: str) -> int:
    row = db.execute(text("INSERT INTO counters(key, value) VALUES (:k, 1) ON CONFLICT (key) DO UPDATE SET value = counters.value + 1 RETURNING value"), {"k": key}).one()
    return row[0]


def number(db: Session, kind: str, prefix: str | None = None, daily: bool = True) -> str:
    p = prefix or settings_service.get(db, "order_prefix") or "BJ"
    d = datetime.now(common.TZ).strftime("%Y%m%d")
    key = f"{kind}:{p}:{d}" if daily else f"{kind}:{p}"
    n = next_seq(db, key)
    return f"{p}-{d}-{n:04d}" if daily else f"{p}-{n:05d}"
