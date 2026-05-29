from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.config import LOW_STOCK_DEFAULT


class SignupPayload(BaseModel):
    email: str = Field(min_length=5, max_length=190)
    password: str = Field(min_length=8, max_length=128)
    shop_name: str = Field(min_length=2, max_length=120)
    shop_phone: str = Field(default="", max_length=40)
    shop_address: str = Field(default="", max_length=255)
    cashier_name: str = Field(default="Caissier", max_length=120)


class LoginPayload(BaseModel):
    email: str = Field(min_length=5, max_length=190)
    password: str = Field(min_length=8, max_length=128)


class StaffLoginPayload(BaseModel):
    shop_email: str = Field(min_length=5, max_length=190)
    login: str = Field(min_length=2, max_length=60)
    password: str = Field(min_length=4, max_length=128)


class AuthOut(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    shop_id: int
    email: str
    shop_name: str
    role: Literal["owner", "admin", "cashier"]
    actor_name: str


class ProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    sku: str = Field(min_length=2, max_length=60)
    stock_qty: int = Field(ge=0)
    min_qty: int = Field(default=LOW_STOCK_DEFAULT, ge=0, le=100000)
    unit: str = Field(default="piece", min_length=1, max_length=20)
    sale_price: int = Field(default=0, ge=0)


class ProductUpdate(ProductCreate):
    pass


class ProductOut(BaseModel):
    id: int
    name: str
    sku: str
    stock_qty: int
    min_qty: int
    unit: str
    sale_price: int


class StockMoveCreate(BaseModel):
    product_id: int
    kind: Literal["in", "out"]
    qty: int = Field(ge=1)
    note: str = Field(default="", max_length=255)


class DebtCreate(BaseModel):
    customer_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(default="", max_length=40)
    product_id: int = Field(ge=1)
    quantity: int = Field(default=1, ge=1)
    due_date: str = Field(default="", max_length=20)
    note: str = Field(default="", max_length=255)


class DebtPayment(BaseModel):
    amount: int = Field(ge=1)
    method: Literal["especes", "flooz", "t_money", "virement"] = "especes"
    note: str = Field(default="", max_length=255)


class SensitiveApprovalPayload(BaseModel):
    password: str = Field(min_length=4, max_length=128)


class ShopUserCreate(BaseModel):
    login: str = Field(min_length=2, max_length=60)
    display_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=4, max_length=128)
    role: Literal["admin", "cashier"] = "cashier"


class ShopUserOut(BaseModel):
    id: int
    login: str
    display_name: str
    role: Literal["admin", "cashier"]
    is_active: bool


class NotificationOut(BaseModel):
    id: int
    actor_name: str
    actor_role: str
    category: str
    severity: Literal["info", "warning", "danger"]
    title: str
    message: str
    is_read: bool
    created_at: str
