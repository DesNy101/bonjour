from __future__ import annotations
from datetime import datetime, date
from typing import Optional
from sqlalchemy import (String, Integer, Boolean, Text, Date, DateTime, ForeignKey, JSON)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.base import TimestampMixin, DemoMixin


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Counter(Base):
    """Atomic document-number sequences (orders, batches, POs, ...)."""
    __tablename__ = "counters"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str] = mapped_column(String(200), default="")
    module: Mapped[str] = mapped_column(String(50), default="")


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(300), default="")
    all_branches: Mapped[bool] = mapped_column(Boolean, default=False)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=True)
    permissions: Mapped[list[Permission]] = relationship(secondary="role_permissions", lazy="selectin")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)


class Branch(Base, TimestampMixin, DemoMixin):
    __tablename__ = "branches"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(300), default="")
    state: Mapped[str] = mapped_column(String(80), default="Bayelsa")
    lga: Mapped[str] = mapped_column(String(80), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    manager_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", use_alter=True, name="fk_branch_manager"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    opened_on: Mapped[Optional[date]] = mapped_column(Date)
    accepts_online_orders: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base, TimestampMixin, DemoMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    full_name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(40), default="")
    password_hash: Mapped[str] = mapped_column(String(300))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branches.id"))
    employee_id: Mapped[Optional[str]] = mapped_column(String(40), unique=True)
    department: Mapped[str] = mapped_column(String(80), default="")
    job_title: Mapped[str] = mapped_column(String(100), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    work_schedule: Mapped[str] = mapped_column(String(300), default="")

    role: Mapped[Role] = relationship(lazy="joined")
    branch: Mapped[Optional[Branch]] = relationship(foreign_keys=[branch_id], lazy="joined")


class UserPermission(Base):
    """Per-user override of the role's permissions (granted=True adds, False removes)."""
    __tablename__ = "user_permissions"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)
    granted: Mapped[bool] = mapped_column(Boolean, default=True)
    permission: Mapped[Permission] = relationship(lazy="joined")


class UserBranch(Base):
    __tablename__ = "user_branches"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True)


class AuthSession(Base, TimestampMixin):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    ip: Mapped[str] = mapped_column(String(60), default="")
    user_agent: Mapped[str] = mapped_column(String(300), default="")


class PasswordReset(Base, TimestampMixin):
    __tablename__ = "password_resets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    user_label: Mapped[str] = mapped_column(String(200), default="")
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity: Mapped[str] = mapped_column(String(60), default="")
    entity_id: Mapped[str] = mapped_column(String(60), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str] = mapped_column(String(60), default="")


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(50), default="info")
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(200), default="")
    channel: Mapped[str] = mapped_column(String(20), default="in_app")
    delivery_status: Mapped[str] = mapped_column(String(20), default="delivered")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)


class Customer(Base, TimestampMixin, DemoMixin):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(40), default="", index=True)
    email: Mapped[str] = mapped_column(String(200), default="", index=True)
    customer_type: Mapped[str] = mapped_column(String(20), default="retail")
    preferred_branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branches.id"))
    notes: Mapped[str] = mapped_column(Text, default="")
    is_guest: Mapped[bool] = mapped_column(Boolean, default=False)
    addresses: Mapped[list["CustomerAddress"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class CustomerAddress(Base):
    __tablename__ = "customer_addresses"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(60), default="Home")
    address: Mapped[str] = mapped_column(String(300))
    lga: Mapped[str] = mapped_column(String(80), default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    instructions: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    status: Mapped[str] = mapped_column(String(20), default="assigned")
    assigned_to: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True)
    department: Mapped[str] = mapped_column(String(80), default="")
    branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branches.id"))
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    completion_notes: Mapped[str] = mapped_column(Text, default="")
    problem_report: Mapped[str] = mapped_column(Text, default="")
    review_note: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
