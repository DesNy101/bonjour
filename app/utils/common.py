from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from fastapi import HTTPException

TZ = ZoneInfo("Africa/Lagos")


def set_tz(name: str):
    global TZ
    try:
        TZ = ZoneInfo(name)
    except Exception:
        pass


def today() -> date:
    return datetime.now(TZ).date()


def day_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=TZ)


def day_end(d: date) -> datetime:
    return datetime.combine(d + timedelta(days=1), time.min, tzinfo=TZ)


def dec(v) -> Decimal:
    return Decimal(str(v))


def num(v):
    """Decimal -> int when whole else float, for JSON."""
    if v is None:
        return 0
    v = Decimal(v)
    return int(v) if v == v.to_integral_value() else float(v)


def bad(msg: str, code: int = 400):
    raise HTTPException(status_code=code, detail=msg)


def naira(kobo: int) -> str:
    return f"₦{kobo / 100:,.2f}"
