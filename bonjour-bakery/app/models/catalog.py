from __future__ import annotations
from datetime import datetime
from typing import Optional
from decimal import Decimal
from sqlalchemy import (String, Boolean, Text, DateTime, ForeignKey, UniqueConstraint, BigInteger,
                        CheckConstraint, Index, Numeric)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.base import TimestampMixin, DemoMixin


class ProductCategory(Base):
    __tablename__ = "product_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="finished")


class Product(Base, TimestampMixin, DemoMixin):
    """Any stockable item: finished goods (sellable), raw materials, packaging."""
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="finished")
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("product_categories.id"))
    size_label: Mapped[str] = mapped_column(String(40), default="")
    unit: Mapped[str] = mapped_column(String(20), default="pcs")
    description: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(String(300), default="")
    price_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    wholesale_price_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_sellable: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[Optional[ProductCategory]] = relationship(lazy="joined")
    __table_args__ = (CheckConstraint("price_kobo >= 0", name="ck_product_price"),
                      CheckConstraint("cost_kobo >= 0", name="ck_product_cost"))


class InventoryBalance(Base):
    __tablename__ = "inventory_balances"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    __table_args__ = (UniqueConstraint("product_id", "branch_id", name="uq_balance_product_branch"),
                      CheckConstraint("quantity >= 0", name="ck_balance_nonneg"),
                      Index("ix_balance_branch", "branch_id"))


class StockMovement(Base, TimestampMixin, DemoMixin):
    __tablename__ = "stock_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    movement_type: Mapped[str] = mapped_column(String(30), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    balance_after: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    reason: Mapped[str] = mapped_column(String(300), default="")
    reference_type: Mapped[str] = mapped_column(String(40), default="")
    reference_id: Mapped[str] = mapped_column(String(40), default="")
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    product: Mapped[Product] = relationship(lazy="joined")


class StockTransfer(Base, TimestampMixin):
    __tablename__ = "stock_transfers"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    from_branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    to_branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    note: Mapped[str] = mapped_column(String(300), default="")
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (CheckConstraint("from_branch_id <> to_branch_id", name="ck_transfer_diff"),
                      CheckConstraint("quantity > 0", name="ck_transfer_qty"))


class Recipe(Base, TimestampMixin):
    __tablename__ = "recipes"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    yield_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=1)
    instructions: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    ingredients: Mapped[list["RecipeIngredient"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    product: Mapped[Product] = relationship(lazy="joined")
    __table_args__ = (CheckConstraint("yield_qty > 0", name="ck_recipe_yield"),)


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"
    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    material: Mapped[Product] = relationship(lazy="joined")
