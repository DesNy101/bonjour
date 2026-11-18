from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import (String, Integer, Boolean, Text, DateTime, ForeignKey, Float)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.base import TimestampMixin, DemoMixin


class Driver(Base, TimestampMixin, DemoMixin):
    __tablename__ = "drivers"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    license_no: Mapped[str] = mapped_column(String(60), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branches.id"))
    status: Mapped[str] = mapped_column(String(15), default="available")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    user: Mapped["User"] = relationship(lazy="joined")  # noqa: F821


class Vehicle(Base, TimestampMixin, DemoMixin):
    __tablename__ = "vehicles"
    id: Mapped[int] = mapped_column(primary_key=True)
    plate_number: Mapped[str] = mapped_column(String(30), unique=True)
    vehicle_type: Mapped[str] = mapped_column(String(50), default="Van")
    capacity_units: Mapped[int] = mapped_column(Integer, default=500)
    branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branches.id"))
    status: Mapped[str] = mapped_column(String(15), default="available")
    notes: Mapped[str] = mapped_column(String(300), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class VehicleIssue(Base, TimestampMixin):
    __tablename__ = "vehicle_issues"
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    reported_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), default="open")


class DeliveryRun(Base, TimestampMixin, DemoMixin):
    __tablename__ = "delivery_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_number: Mapped[str] = mapped_column(String(30), unique=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    scheduled_departure: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expected_return: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(15), default="planned", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    actual_departure: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_return: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    driver: Mapped[Driver] = relationship(lazy="joined")
    vehicle: Mapped[Vehicle] = relationship(lazy="joined")
    assignments: Mapped[list["DeliveryAssignment"]] = relationship(cascade="all, delete-orphan", lazy="selectin", order_by="DeliveryAssignment.sequence")


class DeliveryAssignment(Base, TimestampMixin):
    __tablename__ = "delivery_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("delivery_runs.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="assigned")
    failure_reason: Mapped[str] = mapped_column(String(300), default="")
    driver_notes: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    run: Mapped[DeliveryRun] = relationship(back_populates="assignments")
    confirmation: Mapped[Optional["DeliveryConfirmation"]] = relationship(uselist=False, lazy="selectin", cascade="all, delete-orphan")


class DeliveryConfirmation(Base, TimestampMixin):
    __tablename__ = "delivery_confirmations"
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("delivery_assignments.id", ondelete="CASCADE"), unique=True)
    received_by_name: Mapped[str] = mapped_column(String(150), default="")
    customer_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    photo_path: Mapped[str] = mapped_column(String(300), default="")
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
