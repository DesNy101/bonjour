from __future__ import annotations
from datetime import datetime, date
from typing import Optional
from decimal import Decimal
from sqlalchemy import (String, BigInteger, Boolean, Text, Date, DateTime, ForeignKey, CheckConstraint, Numeric)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.base import TimestampMixin, DemoMixin
from app.models.catalog import Product


class Supplier(Base, TimestampMixin, DemoMixin):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    contact_person: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    materials_supplied: Mapped[str] = mapped_column(String(400), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PurchaseRequest(Base, TimestampMixin, DemoMixin):
    __tablename__ = "purchase_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    reason: Mapped[str] = mapped_column(Text, default="")
    decided_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str] = mapped_column(Text, default="")
    items: Mapped[list["PurchaseRequestItem"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class PurchaseRequestItem(Base):
    __tablename__ = "purchase_request_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("purchase_requests.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    est_unit_cost_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    product: Mapped[Product] = relationship(lazy="joined")


class PurchaseOrder(Base, TimestampMixin, DemoMixin):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    request_id: Mapped[Optional[int]] = mapped_column(ForeignKey("purchase_requests.id"))
    status: Mapped[str] = mapped_column(String(25), default="draft")
    total_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str] = mapped_column(Text, default="")
    items: Mapped[list["PurchaseOrderItem"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    supplier: Mapped[Supplier] = relationship(lazy="joined")


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit_cost_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    received_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    product: Mapped[Product] = relationship(lazy="joined")


class GoodsReceipt(Base, TimestampMixin):
    __tablename__ = "goods_receipts"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    received_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    delivery_note: Mapped[str] = mapped_column(String(100), default="")
    items: Mapped[list["GoodsReceiptItem"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class GoodsReceiptItem(Base):
    __tablename__ = "goods_receipt_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("goods_receipts.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))


class SupplierInvoice(Base, TimestampMixin, DemoMixin):
    __tablename__ = "supplier_invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    po_id: Mapped[Optional[int]] = mapped_column(ForeignKey("purchase_orders.id"))
    branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branches.id"))
    invoice_number: Mapped[str] = mapped_column(String(60))
    amount_kobo: Mapped[int] = mapped_column(BigInteger)
    paid_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(15), default="unpaid")
    recorded_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    supplier: Mapped[Supplier] = relationship(lazy="joined")
    __table_args__ = (CheckConstraint("amount_kobo > 0", name="ck_sinv_amount"),
                      CheckConstraint("paid_kobo >= 0 AND paid_kobo <= amount_kobo", name="ck_sinv_paid"))


class SupplierPayment(Base, TimestampMixin, DemoMixin):
    __tablename__ = "supplier_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("supplier_invoices.id"))
    branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branches.id"))
    amount_kobo: Mapped[int] = mapped_column(BigInteger)
    method: Mapped[str] = mapped_column(String(20), default="bank_transfer")
    reference: Mapped[str] = mapped_column(String(80), default="")
    paid_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="paid")
    approved_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (CheckConstraint("amount_kobo > 0", name="ck_spay_amount"),)
