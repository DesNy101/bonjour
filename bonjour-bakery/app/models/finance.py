from __future__ import annotations
from datetime import datetime, date
from typing import Optional
from sqlalchemy import (String, BigInteger, Boolean, Date, DateTime, ForeignKey, CheckConstraint, Index)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.base import TimestampMixin, DemoMixin


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    counts_in_cogs: Mapped[bool] = mapped_column(Boolean, default=False)


class Expense(Base, TimestampMixin, DemoMixin):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(40), unique=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("expense_categories.id"))
    description: Mapped[str] = mapped_column(String(300))
    amount_kobo: Mapped[int] = mapped_column(BigInteger)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    expense_date: Mapped[date] = mapped_column(Date, index=True)
    supporting_ref: Mapped[str] = mapped_column(String(200), default="")
    attachment_path: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20), default="approved")
    recorded_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    decided_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    category: Mapped[ExpenseCategory] = relationship(lazy="joined")
    approvals: Mapped[list["ExpenseApproval"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    __table_args__ = (CheckConstraint("amount_kobo > 0", name="ck_expense_amount"),)


class ExpenseApproval(Base, TimestampMixin):
    __tablename__ = "expense_approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey("expenses.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(10))
    note: Mapped[str] = mapped_column(String(300), default="")


class FinancialTransaction(Base, TimestampMixin, DemoMixin):
    """Immutable ledger of money movements. Reversals/adjustments are new rows, never edits."""
    __tablename__ = "financial_transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(40), unique=True)
    kind: Mapped[str] = mapped_column(String(25), index=True)
    direction: Mapped[str] = mapped_column(String(3))
    amount_kobo: Mapped[int] = mapped_column(BigInteger)
    method: Mapped[str] = mapped_column(String(25), default="cash")
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    txn_date: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(String(300), default="")
    sales_channel: Mapped[str] = mapped_column(String(20), default="")
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"))
    payment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("payments.id"))
    expense_id: Mapped[Optional[int]] = mapped_column(ForeignKey("expenses.id"))
    supplier_payment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("supplier_payments.id"))
    recorded_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    verification_status: Mapped[str] = mapped_column(String(15), default="verified")
    adjustment_reason: Mapped[str] = mapped_column(String(300), default="")
    __table_args__ = (CheckConstraint("amount_kobo > 0", name="ck_ftx_amount"), Index("ix_ftx_branch_date", "branch_id", "txn_date"))


class CashRegisterClose(Base, TimestampMixin, DemoMixin):
    __tablename__ = "cash_register_closes"
    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    close_date: Mapped[date] = mapped_column(Date)
    opening_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    cash_in_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    cash_out_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    expected_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    counted_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    variance_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    notes: Mapped[str] = mapped_column(String(300), default="")
    closed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
