from __future__ import annotations
from datetime import datetime, date
from typing import Optional
from sqlalchemy import (String, Integer, BigInteger, Boolean, Text, Date, DateTime, ForeignKey, CheckConstraint, Index)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.base import TimestampMixin, DemoMixin


class Order(Base, TimestampMixin, DemoMixin):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str] = mapped_column(String(30), unique=True)
    tracking_token: Mapped[str] = mapped_column(String(40), unique=True)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20), default="online")
    order_type: Mapped[str] = mapped_column(String(10), default="pickup")
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    payment_status: Mapped[str] = mapped_column(String(25), default="unpaid", index=True)
    contact_name: Mapped[str] = mapped_column(String(150))
    contact_phone: Mapped[str] = mapped_column(String(40), default="")
    contact_email: Mapped[str] = mapped_column(String(200), default="")
    delivery_address: Mapped[str] = mapped_column(String(400), default="")
    delivery_lga: Mapped[str] = mapped_column(String(80), default="")
    delivery_instructions: Mapped[str] = mapped_column(String(400), default="")
    preferred_date: Mapped[Optional[date]] = mapped_column(Date)
    preferred_time: Mapped[str] = mapped_column(String(40), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    subtotal_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    delivery_fee_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    tax_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    total_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    paid_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    cancel_reason: Mapped[str] = mapped_column(String(300), default="")
    stock_deducted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    items: Mapped[list["OrderItem"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    history: Mapped[list["OrderStatusHistory"]] = relationship(cascade="all, delete-orphan", lazy="selectin", order_by="OrderStatusHistory.id")
    payments: Mapped[list["Payment"]] = relationship(lazy="selectin", order_by="Payment.id")
    __table_args__ = (CheckConstraint("total_kobo >= 0", name="ck_order_total"), Index("ix_orders_created", "created_at"))


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    name: Mapped[str] = mapped_column(String(200))
    unit_price_kobo: Mapped[int] = mapped_column(BigInteger)
    unit_cost_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    quantity: Mapped[int] = mapped_column(Integer)
    line_total_kobo: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_item_qty"),)


class OrderStatusHistory(Base, TimestampMixin):
    __tablename__ = "order_status_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str] = mapped_column(String(30), default="")
    to_status: Mapped[str] = mapped_column(String(30))
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    user_label: Mapped[str] = mapped_column(String(150), default="")
    note: Mapped[str] = mapped_column(String(300), default="")


class Payment(Base, TimestampMixin, DemoMixin):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(40), unique=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    amount_kobo: Mapped[int] = mapped_column(BigInteger)
    method: Mapped[str] = mapped_column(String(25))
    status: Mapped[str] = mapped_column(String(25), default="pending", index=True)
    proof_reference: Mapped[str] = mapped_column(String(120), default="")
    proof_path: Mapped[str] = mapped_column(String(300), default="")
    gateway_reference: Mapped[str] = mapped_column(String(120), default="")
    recorded_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    verified_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("amount_kobo > 0", name="ck_payment_amount"),)


class PaymentVerification(Base, TimestampMixin):
    __tablename__ = "payment_verifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str] = mapped_column(String(300), default="")
