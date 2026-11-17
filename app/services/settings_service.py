from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models import Setting
from app.utils import common

DEFAULTS = {
    "business_name": "Bonjour Bakery", "tagline": "Fresh bread, baked daily in Yenagoa", "contact_phone": "", "contact_email": "",
    "contact_address": "Yenagoa, Bayelsa State, Nigeria", "currency": "NGN", "timezone": "Africa/Lagos", "order_prefix": "BJ",
    "tax_enabled": False, "tax_rate_percent": 0.0, "delivery_fee_kobo": 100000, "free_delivery_above_kobo": 0, "min_order_kobo": 0,
    "delivery_lgas": ["Yenagoa", "Kolokuma/Opokuma", "Southern Ijaw", "Ogbia", "Sagbama", "Ekeremor", "Nembe", "Brass"],
    "delivery_time_slots": ["7am - 10am", "10am - 1pm", "1pm - 4pm", "4pm - 7pm"],
    "pay_cash_on_delivery": True, "pay_cash_at_pickup": True, "pay_bank_transfer": True, "pay_online": True,
    "bank_name": "", "bank_account_number": "", "bank_account_name": "",
    "expense_approval_threshold_kobo": 5000000, "overhead_percent_of_ingredient_cost": 15.0,
    "notify_email": False, "notify_sms": False, "notify_whatsapp": False, "low_stock_alerts": True, "data_mode": "live",
}
PUBLIC_KEYS = ["business_name", "tagline", "contact_phone", "contact_email", "contact_address", "currency",
               "delivery_fee_kobo", "free_delivery_above_kobo", "min_order_kobo", "delivery_lgas",
               "delivery_time_slots", "pay_cash_on_delivery", "pay_cash_at_pickup", "pay_bank_transfer", "pay_online",
               "bank_name", "bank_account_number", "bank_account_name", "tax_enabled", "tax_rate_percent"]


def all_settings(db: Session) -> dict:
    out = dict(DEFAULTS)
    for s in db.query(Setting).all():
        out[s.key] = s.value.get("v") if isinstance(s.value, dict) else s.value
    return out


def get(db: Session, key: str):
    s = db.get(Setting, key)
    return DEFAULTS.get(key) if s is None else s.value.get("v")


def set_value(db: Session, key: str, value):
    if key not in DEFAULTS:
        raise KeyError(key)
    s = db.get(Setting, key)
    if s is None:
        s = Setting(key=key, value={"v": value})
        db.add(s)
    else:
        s.value = {"v": value}
    s.updated_at = datetime.now(timezone.utc)
    if key == "timezone":
        common.set_tz(value)


def is_demo_mode(db: Session) -> bool:
    return get(db, "data_mode") == "demo"
