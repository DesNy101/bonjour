from __future__ import annotations
from datetime import datetime, date
from typing import Optional
from decimal import Decimal
from sqlalchemy import (String, Integer, BigInteger, Boolean, Text, Date, DateTime, ForeignKey, Numeric)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.base import TimestampMixin, DemoMixin
from app.models.catalog import Product


class ProductionStage(Base):
    __tablename__ = "production_stages"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    department: Mapped[str] = mapped_column(String(80), default="Production")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProductionPlan(Base, TimestampMixin, DemoMixin):
    __tablename__ = "production_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    plan_date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expected_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    supervisor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="planned")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    batches: Mapped[list["ProductionBatch"]] = relationship(back_populates="plan", lazy="selectin")


class ProductionBatch(Base, TimestampMixin, DemoMixin):
    __tablename__ = "production_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_number: Mapped[str] = mapped_column(String(30), unique=True)
    plan_id: Mapped[Optional[int]] = mapped_column(ForeignKey("production_plans.id", ondelete="SET NULL"))
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    recipe_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recipes.id"))
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    planned_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    actual_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    rejected_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    wastage_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    status: Mapped[str] = mapped_column(String(20), default="planned", index=True)
    current_stage_id: Mapped[Optional[int]] = mapped_column(ForeignKey("production_stages.id"))
    supervisor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    scheduled_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expected_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    total_cost_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    plan: Mapped[Optional[ProductionPlan]] = relationship(back_populates="batches")
    product: Mapped[Product] = relationship(lazy="joined")
    stage_logs: Mapped[list["BatchStageLog"]] = relationship(cascade="all, delete-orphan", lazy="selectin", order_by="BatchStageLog.id")
    consumption: Mapped[list["BatchConsumption"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class BatchStageLog(Base):
    __tablename__ = "batch_stage_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("production_batches.id", ondelete="CASCADE"), index=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey("production_stages.id"))
    assigned_to: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text, default="")
    stage: Mapped[ProductionStage] = relationship(lazy="joined")


class BatchConsumption(Base):
    __tablename__ = "batch_consumption"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("production_batches.id", ondelete="CASCADE"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    expected_qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0)
    actual_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))
    cost_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    material: Mapped[Product] = relationship(lazy="joined")
