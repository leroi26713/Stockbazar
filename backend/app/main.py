from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Integer, String, create_engine, func, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


load_dotenv()
APP_ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./stockbazar.db")
AUTO_CREATE_SCHEMA = os.getenv("AUTO_CREATE_SCHEMA", "true").lower() == "true"
CORS_ALLOW_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", "*")
LOW_STOCK_DEFAULT = int(os.getenv("LOW_STOCK_DEFAULT", "5"))
FRONTEND_FILE = os.getenv("FRONTEND_FILE", "index.html")
AUTH_SECRET = os.getenv("AUTH_SECRET", "change-me-redestock-auth-secret")
TOKEN_TTL_HOURS = int(os.getenv("TOKEN_TTL_HOURS", "24"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "4"))
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", str(APP_ROOT / "uploads"))).resolve()


class Base(DeclarativeBase):
    pass


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


class Product(Base):
    __tablename__ = "products"

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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shop_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class CustomerDebt(Base):
    __tablename__ = "customer_debts"

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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shop_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    debt_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="especes")
    note: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


def build_engine() -> any:
    connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
    return create_engine(DATABASE_URL, echo=False, future=True, connect_args=connect_args)


engine = build_engine()
if AUTO_CREATE_SCHEMA:
    Base.metadata.create_all(engine)


UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def ensure_sqlite_columns() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return

    table_alters = {
        "products": {
            "shop_id": "ALTER TABLE products ADD COLUMN shop_id INTEGER NOT NULL DEFAULT 1",
        },
        "stock_movements": {
            "shop_id": "ALTER TABLE stock_movements ADD COLUMN shop_id INTEGER NOT NULL DEFAULT 1",
        },
        "customer_debts": {
            "shop_id": "ALTER TABLE customer_debts ADD COLUMN shop_id INTEGER NOT NULL DEFAULT 1",
            "product_id": "ALTER TABLE customer_debts ADD COLUMN product_id INTEGER",
            "product_name": "ALTER TABLE customer_debts ADD COLUMN product_name VARCHAR(120) NOT NULL DEFAULT ''",
            "quantity": "ALTER TABLE customer_debts ADD COLUMN quantity INTEGER NOT NULL DEFAULT 0",
            "unit_price": "ALTER TABLE customer_debts ADD COLUMN unit_price INTEGER NOT NULL DEFAULT 0",
        },
        "debt_payment_logs": {
            "shop_id": "ALTER TABLE debt_payment_logs ADD COLUMN shop_id INTEGER NOT NULL DEFAULT 1",
            "method": "ALTER TABLE debt_payment_logs ADD COLUMN method VARCHAR(20) NOT NULL DEFAULT 'especes'",
        },
    }

    with Session(engine) as session:
        for table_name, alters in table_alters.items():
            cols = session.execute(text(f"PRAGMA table_info({table_name})")).all()
            if not cols:
                continue
            existing = {row[1] for row in cols}
            changed = False
            for col_name, stmt in alters.items():
                if col_name not in existing:
                    session.execute(text(stmt))
                    changed = True
            if changed:
                session.commit()


ensure_sqlite_columns()


def normalize_legacy_debts() -> None:
    with Session(engine) as session:
        debts = session.scalars(select(CustomerDebt)).all()
        changed = False
        for debt in debts:
            if not debt.product_name.strip():
                debt.product_name = "Article non renseigne (ancienne dette)"
                changed = True
            if debt.quantity <= 0:
                debt.quantity = 1
                changed = True
            if debt.unit_price <= 0:
                debt.unit_price = debt.amount_total
                changed = True
        if changed:
            session.commit()


normalize_legacy_debts()


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


class AuthOut(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    shop_id: int
    email: str
    shop_name: str


class ProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    sku: str = Field(min_length=2, max_length=60)
    stock_qty: int = Field(ge=0)
    min_qty: int = Field(default=LOW_STOCK_DEFAULT, ge=0, le=100000)
    unit: str = Field(default="piece", min_length=1, max_length=20)
    sale_price: int = Field(default=0, ge=0)


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


app = FastAPI(title="REDESTOCK API", version="0.4.0")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

origins = [x.strip() for x in CORS_ALLOW_ORIGINS.split(",") if x.strip()]
if not origins:
    origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 150000).hex()
    return f"{salt}${pwd_hash}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, expected = password_hash.split("$", 1)
    except ValueError:
        return False
    got = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 150000).hex()
    return hmac.compare_digest(got, expected)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode((raw + padding).encode())


def create_token(shop_id: int, email: str) -> str:
    payload = {
        "sub": shop_id,
        "email": email,
        "exp": int(time.time()) + TOKEN_TTL_HOURS * 3600,
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(AUTH_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64url_encode(sig)}"


def parse_token(token: str) -> dict:
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        expected_sig = hmac.new(AUTH_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_decode(sig_b64), expected_sig):
            raise ValueError("invalid signature")
        payload = json.loads(_b64url_decode(payload_b64).decode())
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("expired")
        return payload
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=401, detail="Token invalide") from exc


def current_shop(authorization: str | None = Header(default=None)) -> ShopAccount:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization Bearer requis")
    token = authorization.split(" ", 1)[1].strip()
    payload = parse_token(token)
    shop_id = int(payload.get("sub", 0))
    with Session(engine) as session:
        shop = session.get(ShopAccount, shop_id)
        if not shop:
            raise HTTPException(status_code=401, detail="Compte introuvable")
        return shop


def parse_due_date(value: str) -> str:
    if not value:
        return ""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Format due_date invalide (attendu YYYY-MM-DD)") from exc


def build_receipt_number(payment_log_id: int, created_at: datetime) -> str:
    return f"RDS-{created_at.strftime('%Y%m%d')}-{payment_log_id:06d}"


def normalize_method(method: str) -> str:
    labels = {
        "especes": "Especes",
        "flooz": "Flooz",
        "t_money": "T-Money",
        "virement": "Virement",
    }
    return labels.get(method, method)


def normalize_phone(raw_phone: str) -> str:
    digits = re.sub(r"\D", "", raw_phone or "")
    if not digits:
        return ""
    if digits.startswith("228"):
        return digits
    return f"228{digits}"


def save_upload(file: UploadFile, prefix: str, shop_id: int) -> str:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        raise HTTPException(status_code=422, detail="Format image non supporte")

    raw = file.file.read()
    if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=422, detail=f"Image trop volumineuse (max {MAX_UPLOAD_MB} MB)")

    filename = f"shop_{shop_id}_{prefix}_{uuid.uuid4().hex}{ext}"
    path = UPLOADS_DIR / filename
    path.write_bytes(raw)
    return f"/uploads/{filename}"


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "redestock", "version": "0.4.0"}


@app.post("/api/auth/signup", response_model=AuthOut)
def auth_signup(payload: SignupPayload):
    email = payload.email.strip().lower()
    with Session(engine) as session:
        exists = session.scalar(select(ShopAccount).where(ShopAccount.email == email))
        if exists:
            raise HTTPException(status_code=409, detail="Email deja utilise")

        shop = ShopAccount(
            email=email,
            password_hash=hash_password(payload.password),
            shop_name=payload.shop_name.strip(),
            shop_phone=payload.shop_phone.strip(),
            shop_address=payload.shop_address.strip(),
            cashier_name=payload.cashier_name.strip() or "Caissier",
        )
        session.add(shop)
        session.commit()
        session.refresh(shop)

    token = create_token(shop.id, shop.email)
    return AuthOut(
        access_token=token,
        token_type="bearer",
        expires_in=TOKEN_TTL_HOURS * 3600,
        shop_id=shop.id,
        email=shop.email,
        shop_name=shop.shop_name,
    )


@app.post("/api/auth/login", response_model=AuthOut)
def auth_login(payload: LoginPayload):
    email = payload.email.strip().lower()
    with Session(engine) as session:
        shop = session.scalar(select(ShopAccount).where(ShopAccount.email == email))
        if not shop or not verify_password(payload.password, shop.password_hash):
            raise HTTPException(status_code=401, detail="Email ou mot de passe invalide")

    token = create_token(shop.id, shop.email)
    return AuthOut(
        access_token=token,
        token_type="bearer",
        expires_in=TOKEN_TTL_HOURS * 3600,
        shop_id=shop.id,
        email=shop.email,
        shop_name=shop.shop_name,
    )


@app.get("/api/auth/me")
def auth_me(shop: ShopAccount = Depends(current_shop)):
    return {
        "shop_id": shop.id,
        "email": shop.email,
        "shop_name": shop.shop_name,
        "shop_phone": shop.shop_phone,
        "shop_address": shop.shop_address,
        "cashier_name": shop.cashier_name,
        "logo_url": shop.logo_url,
        "signature_url": shop.signature_url,
    }


@app.put("/api/shop/profile")
def update_shop_profile(
    shop_name: str = Form(...),
    shop_phone: str = Form(""),
    shop_address: str = Form(""),
    cashier_name: str = Form("Caissier"),
    logo: UploadFile | None = File(default=None),
    signature: UploadFile | None = File(default=None),
    shop: ShopAccount = Depends(current_shop),
):
    with Session(engine) as session:
        db_shop = session.get(ShopAccount, shop.id)
        if not db_shop:
            raise HTTPException(status_code=404, detail="Compte introuvable")

        db_shop.shop_name = shop_name.strip()[:120] or db_shop.shop_name
        db_shop.shop_phone = shop_phone.strip()[:40]
        db_shop.shop_address = shop_address.strip()[:255]
        db_shop.cashier_name = cashier_name.strip()[:120] or "Caissier"

        if logo is not None and logo.filename:
            db_shop.logo_url = save_upload(logo, "logo", db_shop.id)

        if signature is not None and signature.filename:
            db_shop.signature_url = save_upload(signature, "signature", db_shop.id)

        session.commit()
        session.refresh(db_shop)

        return {
            "shop_name": db_shop.shop_name,
            "shop_phone": db_shop.shop_phone,
            "shop_address": db_shop.shop_address,
            "cashier_name": db_shop.cashier_name,
            "logo_url": db_shop.logo_url,
            "signature_url": db_shop.signature_url,
        }


@app.get("/api/products")
def list_products(shop: ShopAccount = Depends(current_shop)):
    with Session(engine) as session:
        items = session.scalars(
            select(Product).where(Product.shop_id == shop.id).order_by(Product.id.desc())
        ).all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "sku": p.sku,
                "stock_qty": p.stock_qty,
                "min_qty": p.min_qty,
                "unit": p.unit,
                "sale_price": p.sale_price,
                "is_low_stock": p.stock_qty <= p.min_qty,
            }
            for p in items
        ]


@app.post("/api/products", response_model=ProductOut)
def create_product(payload: ProductCreate, shop: ShopAccount = Depends(current_shop)):
    sku = payload.sku.strip().upper()
    with Session(engine) as session:
        exists = session.scalar(
            select(Product).where(Product.shop_id == shop.id, Product.sku == sku)
        )
        if exists:
            raise HTTPException(status_code=409, detail="SKU deja utilise")

        product = Product(
            shop_id=shop.id,
            name=payload.name.strip(),
            sku=sku,
            stock_qty=payload.stock_qty,
            min_qty=payload.min_qty,
            unit=payload.unit.strip(),
            sale_price=payload.sale_price,
        )
        session.add(product)
        session.commit()
        session.refresh(product)
        if product.stock_qty > 0:
            session.add(
                StockMovement(
                    shop_id=shop.id,
                    product_id=product.id,
                    kind="in",
                    qty=product.stock_qty,
                    note="Stock initial a la creation produit",
                )
            )
            session.commit()


        return ProductOut(
            id=product.id,
            name=product.name,
            sku=product.sku,
            stock_qty=product.stock_qty,
            min_qty=product.min_qty,
            unit=product.unit,
            sale_price=product.sale_price,
        )


@app.delete("/api/products/{product_id}")
def delete_product(product_id: int, shop: ShopAccount = Depends(current_shop)):
    with Session(engine) as session:
        product = session.scalar(
            select(Product).where(Product.id == product_id, Product.shop_id == shop.id)
        )
        if not product:
            raise HTTPException(status_code=404, detail="Produit introuvable")

        debt_count = session.scalar(
            select(func.count(CustomerDebt.id)).where(
                CustomerDebt.shop_id == shop.id,
                CustomerDebt.product_id == product_id,
            )
        ) or 0
        if debt_count > 0:
            raise HTTPException(status_code=409, detail="Impossible de supprimer: produit lie a des dettes")

        moves = session.scalars(
            select(StockMovement).where(
                StockMovement.shop_id == shop.id,
                StockMovement.product_id == product_id,
            )
        ).all()
        for mv in moves:
            session.delete(mv)
        session.delete(product)
        session.commit()
        return {"status": "ok", "deleted_product_id": product_id}


@app.post("/api/stock/move")
def create_stock_move(payload: StockMoveCreate, shop: ShopAccount = Depends(current_shop)):
    with Session(engine) as session:
        product = session.scalar(
            select(Product).where(Product.id == payload.product_id, Product.shop_id == shop.id)
        )
        if not product:
            raise HTTPException(status_code=404, detail="Produit introuvable")

        if payload.kind == "out" and payload.qty > product.stock_qty:
            raise HTTPException(status_code=400, detail="Stock insuffisant")

        if payload.kind == "in":
            product.stock_qty += payload.qty
        else:
            product.stock_qty -= payload.qty

        mv = StockMovement(
            shop_id=shop.id,
            product_id=product.id,
            kind=payload.kind,
            qty=payload.qty,
            note=payload.note,
        )
        session.add(mv)
        session.commit()

        return {
            "status": "ok",
            "product_id": product.id,
            "new_stock_qty": product.stock_qty,
        }


@app.get("/api/stock/movements")
def list_stock_movements(limit: int = 50, shop: ShopAccount = Depends(current_shop)):
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit doit etre entre 1 et 500")

    with Session(engine) as session:
        rows = session.scalars(
            select(StockMovement)
            .where(StockMovement.shop_id == shop.id)
            .order_by(StockMovement.id.desc())
            .limit(limit)
        ).all()
        product_map = {
            p.id: p.name
            for p in session.scalars(select(Product).where(Product.shop_id == shop.id)).all()
        }
        return [
            {
                "id": r.id,
                "product_id": r.product_id,
                "product_name": product_map.get(r.product_id, "Produit supprime"),
                "kind": r.kind,
                "qty": r.qty,
                "note": r.note,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]


@app.get("/api/alerts/low-stock")
def low_stock_alerts(shop: ShopAccount = Depends(current_shop)):
    with Session(engine) as session:
        items = session.scalars(
            select(Product)
            .where(Product.shop_id == shop.id, Product.stock_qty <= Product.min_qty)
            .order_by(Product.stock_qty.asc())
        ).all()
        return {
            "count": len(items),
            "items": [
                {
                    "id": p.id,
                    "name": p.name,
                    "sku": p.sku,
                    "stock_qty": p.stock_qty,
                    "min_qty": p.min_qty,
                }
                for p in items
            ],
        }


@app.post("/api/debts")
def create_debt(payload: DebtCreate, shop: ShopAccount = Depends(current_shop)):
    due_date = parse_due_date(payload.due_date)

    with Session(engine) as session:
        product = session.scalar(
            select(Product).where(Product.id == payload.product_id, Product.shop_id == shop.id)
        )
        if not product:
            raise HTTPException(status_code=404, detail="Produit introuvable pour la dette")
        if payload.quantity > product.stock_qty:
            raise HTTPException(status_code=400, detail="Stock insuffisant pour une vente a credit")
        if product.sale_price <= 0:
            raise HTTPException(status_code=400, detail="Prix produit invalide")

        amount_total = product.sale_price * payload.quantity

        product.stock_qty -= payload.quantity
        session.add(
            StockMovement(
                shop_id=shop.id,
                product_id=product.id,
                kind="out",
                qty=payload.quantity,
                note=f"Vente a credit: {payload.customer_name.strip()}",
            )
        )

        debt = CustomerDebt(
            shop_id=shop.id,
            customer_name=payload.customer_name.strip(),
            phone=payload.phone.strip(),
            product_id=product.id,
            product_name=product.name,
            quantity=payload.quantity,
            unit_price=product.sale_price,
            amount_total=amount_total,
            amount_paid=0,
            due_date=due_date,
            note=payload.note.strip(),
        )
        session.add(debt)
        session.commit()
        session.refresh(debt)

        return {
            "id": debt.id,
            "customer_name": debt.customer_name,
            "product_id": debt.product_id,
            "product_name": debt.product_name,
            "quantity": debt.quantity,
            "unit_price": debt.unit_price,
            "amount_total": debt.amount_total,
            "amount_paid": debt.amount_paid,
            "amount_due": debt.amount_total - debt.amount_paid,
            "due_date": debt.due_date,
        }


@app.post("/api/debts/{debt_id}/pay")
def pay_debt(debt_id: int, payload: DebtPayment, shop: ShopAccount = Depends(current_shop)):
    with Session(engine) as session:
        debt = session.scalar(
            select(CustomerDebt).where(CustomerDebt.id == debt_id, CustomerDebt.shop_id == shop.id)
        )
        if not debt:
            raise HTTPException(status_code=404, detail="Dette introuvable")

        due_before = debt.amount_total - debt.amount_paid
        if payload.amount > due_before:
            raise HTTPException(status_code=400, detail=f"Montant superieur au solde ({due_before})")

        debt.amount_paid += payload.amount
        log = DebtPaymentLog(
            shop_id=shop.id,
            debt_id=debt.id,
            amount=payload.amount,
            method=payload.method,
            note=payload.note,
        )
        session.add(log)
        session.commit()
        session.refresh(log)

        receipt_number = build_receipt_number(log.id, log.created_at)
        return {
            "id": debt.id,
            "customer_name": debt.customer_name,
            "amount_due": debt.amount_total - debt.amount_paid,
            "is_settled": (debt.amount_total - debt.amount_paid) == 0,
            "payment_log_id": log.id,
            "receipt_number": receipt_number,
            "payment_amount": log.amount,
            "payment_method": log.method,
            "paid_at": log.created_at.isoformat(),
        }


@app.get("/api/debts")
def list_debts(shop: ShopAccount = Depends(current_shop)):
    today = date.today()
    with Session(engine) as session:
        items = session.scalars(
            select(CustomerDebt)
            .where(CustomerDebt.shop_id == shop.id)
            .order_by(CustomerDebt.id.desc())
        ).all()
        out = []
        for d in items:
            due_amount = d.amount_total - d.amount_paid
            is_overdue = False
            if d.due_date and due_amount > 0:
                try:
                    is_overdue = date.fromisoformat(d.due_date) < today
                except ValueError:
                    is_overdue = False
            out.append(
                {
                    "id": d.id,
                    "customer_name": d.customer_name,
                    "phone": d.phone,
                    "product_id": d.product_id,
                    "product_name": d.product_name,
                    "quantity": d.quantity,
                    "unit_price": d.unit_price,
                    "amount_total": d.amount_total,
                    "amount_paid": d.amount_paid,
                    "amount_due": due_amount,
                    "due_date": d.due_date,
                    "note": d.note,
                    "is_overdue": is_overdue,
                    "is_settled": due_amount == 0,
                }
            )
        return out


@app.get("/api/debts/export.csv")
def export_debts_csv(
    status: Literal["all", "open", "overdue", "settled"] = "all",
    q: str = "",
    shop: ShopAccount = Depends(current_shop),
):
    today = date.today()
    query_text = q.strip().lower()

    with Session(engine) as session:
        items = session.scalars(
            select(CustomerDebt)
            .where(CustomerDebt.shop_id == shop.id)
            .order_by(CustomerDebt.id.desc())
        ).all()

    rows: list[dict] = []
    for d in items:
        due_amount = d.amount_total - d.amount_paid
        is_overdue = False
        if d.due_date and due_amount > 0:
            try:
                is_overdue = date.fromisoformat(d.due_date) < today
            except ValueError:
                is_overdue = False

        is_settled = due_amount == 0
        state = "Solde" if is_settled else ("En retard" if is_overdue else "En cours")

        if status == "open" and (is_settled or is_overdue):
            continue
        if status == "overdue" and (not is_overdue or is_settled):
            continue
        if status == "settled" and not is_settled:
            continue

        if query_text:
            haystack = f"{d.id} {d.customer_name} {d.product_name}".lower()
            if query_text not in haystack:
                continue

        rows.append(
            {
                "id": d.id,
                "customer_name": d.customer_name,
                "phone": d.phone,
                "product_name": d.product_name,
                "quantity": d.quantity,
                "unit_price": d.unit_price,
                "amount_total": d.amount_total,
                "amount_paid": d.amount_paid,
                "amount_due": due_amount,
                "due_date": d.due_date,
                "state": state,
                "note": d.note,
            }
        )

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "id",
            "customer_name",
            "phone",
            "product_name",
            "quantity",
            "unit_price",
            "amount_total",
            "amount_paid",
            "amount_due",
            "due_date",
            "state",
            "note",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    headers = {"Content-Disposition": f'attachment; filename="debts_{stamp}.csv"'}
    return Response(content=output.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@app.get("/api/debts/{debt_id}/payments")
def debt_payments(debt_id: int, shop: ShopAccount = Depends(current_shop)):
    with Session(engine) as session:
        debt = session.scalar(
            select(CustomerDebt).where(CustomerDebt.id == debt_id, CustomerDebt.shop_id == shop.id)
        )
        if not debt:
            raise HTTPException(status_code=404, detail="Dette introuvable")

        logs = session.scalars(
            select(DebtPaymentLog)
            .where(DebtPaymentLog.shop_id == shop.id, DebtPaymentLog.debt_id == debt_id)
            .order_by(DebtPaymentLog.id.desc())
        ).all()

        return {
            "debt_id": debt.id,
            "customer_name": debt.customer_name,
            "payments": [
                {
                    "id": l.id,
                    "receipt_number": build_receipt_number(l.id, l.created_at),
                    "amount": l.amount,
                    "method": l.method,
                    "note": l.note,
                    "created_at": l.created_at.isoformat(),
                }
                for l in logs
            ],
        }


@app.get("/api/receipts/payments/{payment_log_id}")
def payment_receipt(payment_log_id: int, shop: ShopAccount = Depends(current_shop)):
    with Session(engine) as session:
        log = session.scalar(
            select(DebtPaymentLog).where(DebtPaymentLog.id == payment_log_id, DebtPaymentLog.shop_id == shop.id)
        )
        if not log:
            raise HTTPException(status_code=404, detail="Paiement introuvable")

        debt = session.scalar(
            select(CustomerDebt).where(CustomerDebt.id == log.debt_id, CustomerDebt.shop_id == shop.id)
        )
        if not debt:
            raise HTTPException(status_code=404, detail="Dette introuvable pour ce paiement")

        shop_db = session.get(ShopAccount, shop.id)
        receipt_number = build_receipt_number(log.id, log.created_at)
        amount_due_after = debt.amount_total - debt.amount_paid

        return {
            "payment_log_id": log.id,
            "receipt_number": receipt_number,
            "issued_at": log.created_at.isoformat(),
            "customer_name": debt.customer_name,
            "customer_phone": debt.phone,
            "product_name": debt.product_name,
            "quantity": debt.quantity,
            "unit_price": debt.unit_price,
            "payment_amount": log.amount,
            "payment_method": log.method,
            "payment_method_label": normalize_method(log.method),
            "debt_total": debt.amount_total,
            "debt_paid": debt.amount_paid,
            "debt_due_after_payment": amount_due_after,
            "payment_note": log.note,
            "shop_name": shop_db.shop_name,
            "shop_phone": shop_db.shop_phone,
            "shop_address": shop_db.shop_address,
            "cashier_name": shop_db.cashier_name,
            "shop_logo_url": shop_db.logo_url,
            "shop_signature_url": shop_db.signature_url,
        }


@app.get("/api/receipts/verify/{receipt_number}")
def verify_receipt(receipt_number: str, shop: ShopAccount = Depends(current_shop)):
    with Session(engine) as session:
        logs = session.scalars(select(DebtPaymentLog).where(DebtPaymentLog.shop_id == shop.id)).all()
        for log in logs:
            expected = build_receipt_number(log.id, log.created_at)
            if expected == receipt_number:
                debt = session.scalar(
                    select(CustomerDebt).where(CustomerDebt.id == log.debt_id, CustomerDebt.shop_id == shop.id)
                )
                return {
                    "valid": True,
                    "receipt_number": receipt_number,
                    "issued_at": log.created_at.isoformat(),
                    "payment_amount": log.amount,
                    "payment_method": log.method,
                    "customer_name": debt.customer_name if debt else "",
                }
        return {"valid": False, "receipt_number": receipt_number}


@app.get("/api/debts/followups")
def debt_followups(
    status: Literal["overdue", "open"] = "overdue",
    limit: int = 50,
    shop: ShopAccount = Depends(current_shop),
):
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit doit etre entre 1 et 500")

    today = date.today()
    with Session(engine) as session:
        rows = session.scalars(
            select(CustomerDebt).where(CustomerDebt.shop_id == shop.id).order_by(CustomerDebt.id.desc())
        ).all()
        out = []
        for d in rows:
            amount_due = d.amount_total - d.amount_paid
            if amount_due <= 0:
                continue

            overdue = False
            if d.due_date:
                try:
                    overdue = date.fromisoformat(d.due_date) < today
                except ValueError:
                    overdue = False

            if status == "overdue" and not overdue:
                continue
            if status == "open" and overdue:
                continue

            phone = normalize_phone(d.phone)
            sender_phone = shop.shop_phone.strip()
            sender_phone_norm = normalize_phone(shop.shop_phone)
            wa_link = None
            if phone:
                shop_label = shop.shop_name.strip() or "votre boutique"
                contact_label = sender_phone or "la boutique"
                msg = (
                    f"Bonjour {d.customer_name}, ceci est un rappel de {shop_label}. "
                    f"Votre solde est de {amount_due} FCFA ({d.product_name}). "
                    f"Merci de contacter {contact_label} pour le paiement."
                )
                wa_link = f"https://wa.me/{phone}?text={quote(msg)}"

            out.append(
                {
                    "id": d.id,
                    "customer_name": d.customer_name,
                    "phone": d.phone,
                    "product_name": d.product_name,
                    "amount_due": amount_due,
                    "due_date": d.due_date,
                    "is_overdue": overdue,
                    "sender_phone": sender_phone,
                    "sender_phone_normalized": sender_phone_norm,
                    "shop_name": shop.shop_name,
                    "whatsapp_link": wa_link,
                }
            )
        return out[:limit]


@app.get("/api/summary")
def summary(shop: ShopAccount = Depends(current_shop)):
    today = date.today()
    week_start = datetime.combine(today - timedelta(days=7), datetime.min.time())
    month_start = datetime.combine(today - timedelta(days=30), datetime.min.time())

    with Session(engine) as session:
        products = session.scalar(select(func.count(Product.id)).where(Product.shop_id == shop.id)) or 0
        debts = session.scalar(select(func.count(CustomerDebt.id)).where(CustomerDebt.shop_id == shop.id)) or 0
        outstanding = (
            session.scalar(
                select(func.coalesce(func.sum(CustomerDebt.amount_total - CustomerDebt.amount_paid), 0)).where(CustomerDebt.shop_id == shop.id)
            )
            or 0
        )

        debt_rows = session.scalars(select(CustomerDebt).where(CustomerDebt.shop_id == shop.id)).all()
        overdue = 0
        for d in debt_rows:
            due_amount = d.amount_total - d.amount_paid
            if d.due_date and due_amount > 0:
                try:
                    if date.fromisoformat(d.due_date) < today:
                        overdue += 1
                except ValueError:
                    pass

        low_stock = (
            session.scalar(
                select(func.count(Product.id)).where(Product.shop_id == shop.id, Product.stock_qty <= Product.min_qty)
            )
            or 0
        )

        collected_7d = (
            session.scalar(
                select(func.coalesce(func.sum(DebtPaymentLog.amount), 0)).where(
                    DebtPaymentLog.shop_id == shop.id,
                    DebtPaymentLog.created_at >= week_start,
                )
            )
            or 0
        )
        collected_30d = (
            session.scalar(
                select(func.coalesce(func.sum(DebtPaymentLog.amount), 0)).where(
                    DebtPaymentLog.shop_id == shop.id,
                    DebtPaymentLog.created_at >= month_start,
                )
            )
            or 0
        )
        collected_total = (
            session.scalar(
                select(func.coalesce(func.sum(DebtPaymentLog.amount), 0)).where(DebtPaymentLog.shop_id == shop.id)
            )
            or 0
        )

        return {
            "products": int(products),
            "debts": int(debts),
            "outstanding_amount": int(outstanding),
            "low_stock_count": int(low_stock),
            "overdue_debts": int(overdue),
            "collected_7d": int(collected_7d),
            "collected_30d": int(collected_30d),
            "collected_total": int(collected_total),
        }


@app.post("/api/admin/reset-data")
def reset_data(confirm: str = Query(default=""), shop: ShopAccount = Depends(current_shop)):
    if confirm != "RESET":
        raise HTTPException(status_code=400, detail="Confirmation requise: confirm=RESET")

    with Session(engine) as session:
        session.query(DebtPaymentLog).filter(DebtPaymentLog.shop_id == shop.id).delete()
        session.query(CustomerDebt).filter(CustomerDebt.shop_id == shop.id).delete()
        session.query(StockMovement).filter(StockMovement.shop_id == shop.id).delete()
        session.query(Product).filter(Product.shop_id == shop.id).delete()
        session.commit()

    return {"status": "ok", "message": "Donnees boutique effacees"}


@app.get("/")
def frontend_index():
    file_path = APP_ROOT / FRONTEND_FILE
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Frontend file not found: {file_path}")
    return FileResponse(file_path)
