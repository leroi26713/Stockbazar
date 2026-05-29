from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.config import LOW_STOCK_DEFAULT
from app.database import Base


class ShopAccount(Base):
    __tablename__ = "shop_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(190), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    shop_name: Mapped[str] = mapped_column(String(120), nullable=False)
    shop_phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    shop_address: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    cashier_name: Mapped[str] = mapped_column(String(120), nullable=False, default="Caissier")
    logo_url: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    signature_url: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ShopUser(Base):
    __tablename__ = "shop_users"
    __table_args__ = (
        Index("ix_shop_users_shop_login", "shop_id", "login"),
        Index("ix_shop_users_shop_active", "shop_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shop_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    login: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="cashier")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_shop_sku", "shop_id", "sku"),
        Index("ix_products_shop_id_desc", "shop_id", "id"),
        Index("ix_products_shop_low_stock", "shop_id", "stock_qty", "min_qty"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shop_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    sku: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    stock_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=LOW_STOCK_DEFAULT)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="piece")
    sale_price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("ix_stock_movements_shop_id_desc", "shop_id", "id"),
        Index("ix_stock_movements_shop_product", "shop_id", "product_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shop_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class CustomerDebt(Base):
    __tablename__ = "customer_debts"
    __table_args__ = (
        Index("ix_customer_debts_shop_id_desc", "shop_id", "id"),
        Index("ix_customer_debts_shop_product", "shop_id", "product_id"),
        Index("ix_customer_debts_shop_due", "shop_id", "due_date"),
        Index("ix_customer_debts_shop_customer", "shop_id", "customer_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shop_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    customer_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    product_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    product_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amount_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amount_paid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    due_date: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    note: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class DebtPaymentLog(Base):
    __tablename__ = "debt_payment_logs"
    __table_args__ = (
        Index("ix_debt_payment_logs_shop_id_desc", "shop_id", "id"),
        Index("ix_debt_payment_logs_shop_debt", "shop_id", "debt_id"),
        Index("ix_debt_payment_logs_shop_created", "shop_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shop_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    debt_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="especes")
    note: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ShopNotification(Base):
    __tablename__ = "shop_notifications"
    __table_args__ = (
        Index("ix_shop_notifications_shop_read_id", "shop_id", "is_read", "id"),
        Index("ix_shop_notifications_shop_id_desc", "shop_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shop_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    actor_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    actor_role: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
