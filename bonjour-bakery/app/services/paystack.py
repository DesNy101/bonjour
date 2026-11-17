import hashlib
import hmac
from types import SimpleNamespace
import httpx
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import Payment, Order
from app.services import payments as pay_svc
from app.utils.common import bad

SYSTEM_USER = SimpleNamespace(id=None, full_name="Paystack", email="paystack", role_key="system")
API = "https://api.paystack.co"


def configured() -> bool:
    return bool(get_settings().paystack_secret_key)


def _headers():
    return {"Authorization": f"Bearer {get_settings().paystack_secret_key}"}


def initialize(db: Session, payment: Payment, order: Order, callback_url: str) -> dict:
    if not configured():
        bad("Online payment is not configured on this server yet. Please choose another payment method.", 503)
    if not order.contact_email:
        bad("An email address is required for online payment.")
    r = httpx.post(f"{API}/transaction/initialize", headers=_headers(), timeout=15,
                   json={"email": order.contact_email, "amount": payment.amount_kobo, "reference": payment.reference,
                         "callback_url": callback_url, "metadata": {"order_number": order.order_number}})
    if r.status_code >= 400 or not r.json().get("status"):
        bad("Payment gateway could not start the transaction. Please try again.", 502)
    return r.json()["data"]


def verify_with_gateway(db: Session, payment: Payment) -> bool:
    """Ask Paystack for the transaction truth; only a successful, amount-matching charge verifies the payment."""
    if not configured():
        bad("Online payment is not configured.", 503)
    r = httpx.get(f"{API}/transaction/verify/{payment.reference}", headers=_headers(), timeout=15)
    data = (r.json() or {}).get("data") or {}
    if r.status_code == 200 and data.get("status") == "success" and int(data.get("amount", -1)) == payment.amount_kobo:
        if payment.status not in ("verified", "rejected"):
            payment.gateway_reference = str(data.get("id", ""))
            pay_svc.verify(db, payment, SYSTEM_USER, True, "Confirmed by Paystack")
        return True
    if data.get("status") in ("failed", "abandoned"):
        payment.status = "failed"
    return False


def valid_signature(raw_body: bytes, signature: str) -> bool:
    key = get_settings().paystack_secret_key.encode()
    if not key or not signature:
        return False
    return hmac.compare_digest(hmac.new(key, raw_body, hashlib.sha512).hexdigest(), signature)
