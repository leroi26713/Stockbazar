from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.bootstrap import bootstrap_app
from app.config import (
    APP_ROOT,
    CORS_ALLOW_ORIGINS,
    ENABLE_ADMIN_RESET,
    FRONTEND_FILE,
    SENSITIVE_STOCK_OUT_QTY,
    TOKEN_TTL_HOURS,
)
from app.database import engine
from app.models import CustomerDebt, DebtPaymentLog, Product, ShopAccount, ShopNotification, ShopUser, StockMovement
from app.schemas import (
    AuthOut,
    DebtCreate,
    DebtPayment,
    LoginPayload,
    NotificationOut,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    SensitiveApprovalPayload,
    ShopUserCreate,
    ShopUserOut,
    SignupPayload,
    StaffLoginPayload,
    StockMoveCreate,
)
from app.security import (
    AuthContext,
    create_sensitive_approval,
    create_token,
    current_auth,
    current_shop,
    hash_password,
    require_roles,
    require_sensitive_approval,
    verify_actor_password,
    verify_password,
)
from app.utils import build_receipt_number, normalize_method, normalize_phone, parse_due_date, save_upload


bootstrap_app()

app = FastAPI(title="REDESTOCK API", version="0.4.0")


def _notify(
    session: Session,
    auth: AuthContext,
    *,
    category: str,
    title: str,
    message: str,
    severity: Literal["info", "warning", "danger"] = "info",
) -> None:
    session.add(
        ShopNotification(
            shop_id=auth.shop.id,
            actor_name=auth.actor_name,
            actor_role=auth.role,
            category=category,
            severity=severity,
            title=title[:160],
            message=message[:500],
        )
    )

origins = [x.strip() for x in CORS_ALLOW_ORIGINS.split(",") if x.strip()]
if not origins:
    origins = ["*"]
allow_credentials = "*" not in origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


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

    token = create_token(
        shop.id,
        shop.email,
        role="owner",
        actor_type="shop",
        actor_id=shop.id,
        actor_name=shop.shop_name,
    )
    return AuthOut(
        access_token=token,
        token_type="bearer",
        expires_in=TOKEN_TTL_HOURS * 3600,
        shop_id=shop.id,
        email=shop.email,
        shop_name=shop.shop_name,
        role="owner",
        actor_name=shop.shop_name,
    )


@app.post("/api/auth/login", response_model=AuthOut)
def auth_login(payload: LoginPayload):
    email = payload.email.strip().lower()
    with Session(engine) as session:
        shop = session.scalar(select(ShopAccount).where(ShopAccount.email == email))
        if not shop or not verify_password(payload.password, shop.password_hash):
            raise HTTPException(status_code=401, detail="Email ou mot de passe invalide")

    token = create_token(
        shop.id,
        shop.email,
        role="owner",
        actor_type="shop",
        actor_id=shop.id,
        actor_name=shop.shop_name,
    )
    return AuthOut(
        access_token=token,
        token_type="bearer",
        expires_in=TOKEN_TTL_HOURS * 3600,
        shop_id=shop.id,
        email=shop.email,
        shop_name=shop.shop_name,
        role="owner",
        actor_name=shop.shop_name,
    )


@app.post("/api/auth/staff/login", response_model=AuthOut)
def auth_staff_login(payload: StaffLoginPayload):
    shop_email = payload.shop_email.strip().lower()
    login = payload.login.strip().lower()
    with Session(engine) as session:
        shop = session.scalar(select(ShopAccount).where(ShopAccount.email == shop_email))
        if not shop:
            raise HTTPException(status_code=401, detail="Boutique ou identifiants invalides")

        staff = session.scalar(
            select(ShopUser).where(
                ShopUser.shop_id == shop.id,
                ShopUser.login == login,
                ShopUser.is_active.is_(True),
            )
        )
        if not staff or not verify_password(payload.password, staff.password_hash):
            raise HTTPException(status_code=401, detail="Boutique ou identifiants invalides")

    token = create_token(
        shop.id,
        shop.email,
        role=staff.role,
        actor_type="staff",
        actor_id=staff.id,
        actor_name=staff.display_name,
    )
    return AuthOut(
        access_token=token,
        token_type="bearer",
        expires_in=TOKEN_TTL_HOURS * 3600,
        shop_id=shop.id,
        email=shop.email,
        shop_name=shop.shop_name,
        role=staff.role,
        actor_name=staff.display_name,
    )


@app.get("/api/auth/me")
def auth_me(auth: AuthContext = Depends(current_auth)):
    shop = auth.shop
    return {
        "shop_id": shop.id,
        "email": shop.email,
        "shop_name": shop.shop_name,
        "shop_phone": shop.shop_phone,
        "shop_address": shop.shop_address,
        "cashier_name": shop.cashier_name,
        "logo_url": shop.logo_url,
        "signature_url": shop.signature_url,
        "role": auth.role,
        "actor_name": auth.actor_name,
        "sensitive_stock_out_qty": SENSITIVE_STOCK_OUT_QTY,
    }


@app.get("/api/notifications", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=30, ge=1, le=100),
    auth: AuthContext = Depends(current_auth),
):
    require_roles(auth, "owner", "admin")
    filters = [ShopNotification.shop_id == auth.shop.id]
    if unread_only:
        filters.append(ShopNotification.is_read.is_(False))

    with Session(engine) as session:
        notifications = session.scalars(
            select(ShopNotification).where(*filters).order_by(ShopNotification.id.desc()).limit(limit)
        ).all()
        return [
            NotificationOut(
                id=item.id,
                actor_name=item.actor_name,
                actor_role=item.actor_role,
                category=item.category,
                severity=item.severity,
                title=item.title,
                message=item.message,
                is_read=item.is_read,
                created_at=item.created_at.isoformat(),
            )
            for item in notifications
        ]


@app.post("/api/notifications/mark-read")
def mark_notifications_read(auth: AuthContext = Depends(current_auth)):
    require_roles(auth, "owner", "admin")
    with Session(engine) as session:
        rows = session.scalars(
            select(ShopNotification).where(
                ShopNotification.shop_id == auth.shop.id,
                ShopNotification.is_read.is_(False),
            )
        ).all()
        for item in rows:
            item.is_read = True
        session.commit()
        return {"status": "ok", "marked": len(rows)}


@app.post("/api/auth/sensitive-approval")
def auth_sensitive_approval(payload: SensitiveApprovalPayload, auth: AuthContext = Depends(current_auth)):
    require_roles(auth, "owner", "admin")
    verify_actor_password(auth, payload.password)
    token, expires_in = create_sensitive_approval(auth.shop.id, auth.actor_type, auth.actor_id, auth.role)
    return {"approval_token": token, "expires_in": expires_in}


@app.get("/api/users", response_model=list[ShopUserOut])
def list_users(auth: AuthContext = Depends(current_auth)):
    require_roles(auth, "owner", "admin")
    with Session(engine) as session:
        users = session.scalars(
            select(ShopUser).where(ShopUser.shop_id == auth.shop.id).order_by(ShopUser.id.desc())
        ).all()
        return [
            ShopUserOut(
                id=user.id,
                login=user.login,
                display_name=user.display_name,
                role=user.role,
                is_active=user.is_active,
            )
            for user in users
        ]


@app.post("/api/users", response_model=ShopUserOut)
def create_user(payload: ShopUserCreate, auth: AuthContext = Depends(current_auth)):
    require_roles(auth, "owner", "admin")
    login = payload.login.strip().lower()
    display_name = payload.display_name.strip()
    with Session(engine) as session:
        exists = session.scalar(select(ShopUser).where(ShopUser.shop_id == auth.shop.id, ShopUser.login == login))
        if exists:
            raise HTTPException(status_code=409, detail="Login deja utilise")
        user = ShopUser(
            shop_id=auth.shop.id,
            login=login,
            display_name=display_name,
            password_hash=hash_password(payload.password),
            role=payload.role,
            is_active=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return ShopUserOut(
            id=user.id,
            login=user.login,
            display_name=user.display_name,
            role=user.role,
            is_active=user.is_active,
        )


@app.delete("/api/users/{user_id}")
def delete_user(
    user_id: int,
    approval_token: str | None = Header(default=None, alias="X-Sensitive-Approval"),
    auth: AuthContext = Depends(current_auth),
):
    require_roles(auth, "owner", "admin")
    require_sensitive_approval(auth, approval_token)
    with Session(engine) as session:
        user = session.scalar(select(ShopUser).where(ShopUser.id == user_id, ShopUser.shop_id == auth.shop.id))
        if not user:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable")
        session.delete(user)
        session.commit()
        return {"status": "ok", "deleted_user_id": user_id}


@app.put("/api/shop/profile")
def update_shop_profile(
    shop_name: str = Form(...),
    shop_phone: str = Form(""),
    shop_address: str = Form(""),
    cashier_name: str = Form("Caissier"),
    logo: UploadFile | None = File(default=None),
    signature: UploadFile | None = File(default=None),
    auth: AuthContext = Depends(current_auth),
):
    require_roles(auth, "owner", "admin")
    shop = auth.shop

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

        _notify(
            session,
            auth,
            category="profile",
            title="Profil boutique modifie",
            message=f"{auth.actor_name} a modifie les informations de la boutique.",
        )
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
        items = session.scalars(select(Product).where(Product.shop_id == shop.id).order_by(Product.id.desc())).all()
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
def create_product(payload: ProductCreate, auth: AuthContext = Depends(current_auth)):
    require_roles(auth, "owner", "admin")
    shop = auth.shop
    sku = payload.sku.strip().upper()
    with Session(engine) as session:
        exists = session.scalar(select(Product).where(Product.shop_id == shop.id, Product.sku == sku))
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


@app.put("/api/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    auth: AuthContext = Depends(current_auth),
):
    require_roles(auth, "owner", "admin")
    shop = auth.shop

    sku = payload.sku.strip().upper()
    name = payload.name.strip()
    unit = payload.unit.strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="Nom produit invalide")
    if len(sku) < 2:
        raise HTTPException(status_code=422, detail="SKU invalide")
    if not unit:
        raise HTTPException(status_code=422, detail="Unite invalide")

    with Session(engine) as session:
        product = session.scalar(select(Product).where(Product.id == product_id, Product.shop_id == shop.id))
        if not product:
            raise HTTPException(status_code=404, detail="Produit introuvable")

        exists = session.scalar(
            select(Product).where(
                Product.shop_id == shop.id,
                Product.sku == sku,
                Product.id != product_id,
            )
        )
        if exists:
            raise HTTPException(status_code=409, detail="SKU deja utilise")

        stock_delta = payload.stock_qty - product.stock_qty
        product.name = name
        product.sku = sku
        product.stock_qty = payload.stock_qty
        product.min_qty = payload.min_qty
        product.unit = unit
        product.sale_price = payload.sale_price

        if stock_delta != 0:
            session.add(
                StockMovement(
                    shop_id=shop.id,
                    product_id=product.id,
                    kind="in" if stock_delta > 0 else "out",
                    qty=abs(stock_delta),
                    note="Ajustement manuel via modification produit",
                )
            )

        session.commit()
        session.refresh(product)

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
def delete_product(
    product_id: int,
    approval_token: str | None = Header(default=None, alias="X-Sensitive-Approval"),
    auth: AuthContext = Depends(current_auth),
):
    require_roles(auth, "owner", "admin")
    require_sensitive_approval(auth, approval_token)
    shop = auth.shop

    with Session(engine) as session:
        product = session.scalar(select(Product).where(Product.id == product_id, Product.shop_id == shop.id))
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

        session.execute(
            delete(StockMovement).where(
                StockMovement.shop_id == shop.id,
                StockMovement.product_id == product_id,
            )
        )
        session.delete(product)
        session.commit()
        return {"status": "ok", "deleted_product_id": product_id}


@app.post("/api/stock/move")
def create_stock_move(
    payload: StockMoveCreate,
    auth: AuthContext = Depends(current_auth),
):
    require_roles(auth, "owner", "admin")
    shop = auth.shop

    with Session(engine) as session:
        product = session.scalar(select(Product).where(Product.id == payload.product_id, Product.shop_id == shop.id))
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
        severity = "warning" if payload.kind == "out" and payload.qty >= SENSITIVE_STOCK_OUT_QTY else "info"
        label = "sortie" if payload.kind == "out" else "entree"
        _notify(
            session,
            auth,
            category="stock",
            severity=severity,
            title=f"Mouvement de stock: {label}",
            message=f"{auth.actor_name} a effectue une {label} de {payload.qty} sur {product.name}.",
        )
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
            select(StockMovement).where(StockMovement.shop_id == shop.id).order_by(StockMovement.id.desc()).limit(limit)
        ).all()
        product_ids = {r.product_id for r in rows}
        if product_ids:
            product_map = {
                p.id: p.name
                for p in session.scalars(
                    select(Product).where(Product.shop_id == shop.id, Product.id.in_(product_ids))
                ).all()
            }
        else:
            product_map = {}
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
def create_debt(
    payload: DebtCreate,
    auth: AuthContext = Depends(current_auth),
):
    require_roles(auth, "owner", "admin", "cashier")
    shop = auth.shop
    due_date = parse_due_date(payload.due_date)

    with Session(engine) as session:
        product = session.scalar(select(Product).where(Product.id == payload.product_id, Product.shop_id == shop.id))
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
        _notify(
            session,
            auth,
            category="debt",
            severity="warning",
            title="Vente a credit creee",
            message=(
                f"{auth.actor_name} a cree une dette de {amount_total} FCFA pour "
                f"{debt.customer_name} ({payload.quantity} x {product.name})."
            ),
        )
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
def pay_debt(
    debt_id: int,
    payload: DebtPayment,
    auth: AuthContext = Depends(current_auth),
):
    require_roles(auth, "owner", "admin", "cashier")
    shop = auth.shop

    with Session(engine) as session:
        debt = session.scalar(select(CustomerDebt).where(CustomerDebt.id == debt_id, CustomerDebt.shop_id == shop.id))
        if not debt:
            raise HTTPException(status_code=404, detail="Dette introuvable")

        due_before = debt.amount_total - debt.amount_paid
        if due_before <= 0:
            raise HTTPException(status_code=400, detail="Cette dette est deja soldee")
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
        _notify(
            session,
            auth,
            category="money",
            title="Paiement encaisse",
            message=(
                f"{auth.actor_name} a encaisse {payload.amount} FCFA pour "
                f"{debt.customer_name} via {normalize_method(payload.method)}."
            ),
        )
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
        items = session.scalars(select(CustomerDebt).where(CustomerDebt.shop_id == shop.id).order_by(CustomerDebt.id.desc())).all()
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
        items = session.scalars(select(CustomerDebt).where(CustomerDebt.shop_id == shop.id).order_by(CustomerDebt.id.desc())).all()

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
        debt = session.scalar(select(CustomerDebt).where(CustomerDebt.id == debt_id, CustomerDebt.shop_id == shop.id))
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
        log = session.scalar(select(DebtPaymentLog).where(DebtPaymentLog.id == payment_log_id, DebtPaymentLog.shop_id == shop.id))
        if not log:
            raise HTTPException(status_code=404, detail="Paiement introuvable")

        debt = session.scalar(select(CustomerDebt).where(CustomerDebt.id == log.debt_id, CustomerDebt.shop_id == shop.id))
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
        match = re.fullmatch(r"RDS-\d{8}-(\d{6})", receipt_number.strip())
        if not match:
            return {"valid": False, "receipt_number": receipt_number}

        payment_log_id = int(match.group(1))
        log = session.scalar(select(DebtPaymentLog).where(DebtPaymentLog.id == payment_log_id, DebtPaymentLog.shop_id == shop.id))
        if log and build_receipt_number(log.id, log.created_at) == receipt_number:
            debt = session.scalar(select(CustomerDebt).where(CustomerDebt.id == log.debt_id, CustomerDebt.shop_id == shop.id))
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
        filters = [CustomerDebt.shop_id == shop.id, CustomerDebt.amount_total > CustomerDebt.amount_paid]
        if status == "overdue":
            filters.append(CustomerDebt.due_date != "")
            filters.append(CustomerDebt.due_date < today.isoformat())
        else:
            filters.append(or_(CustomerDebt.due_date == "", CustomerDebt.due_date >= today.isoformat()))
        rows = session.scalars(
            select(CustomerDebt).where(*filters).order_by(CustomerDebt.id.desc()).limit(limit)
        ).all()
        out = []
        for d in rows:
            amount_due = d.amount_total - d.amount_paid

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
            if len(out) >= limit:
                break
        return out


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

        overdue = (
            session.scalar(
                select(func.count(CustomerDebt.id)).where(
                    CustomerDebt.shop_id == shop.id,
                    CustomerDebt.amount_total > CustomerDebt.amount_paid,
                    CustomerDebt.due_date != "",
                    CustomerDebt.due_date < today.isoformat(),
                )
            )
            or 0
        )

        low_stock = (
            session.scalar(select(func.count(Product.id)).where(Product.shop_id == shop.id, Product.stock_qty <= Product.min_qty))
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
            session.scalar(select(func.coalesce(func.sum(DebtPaymentLog.amount), 0)).where(DebtPaymentLog.shop_id == shop.id))
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
def reset_data(
    confirm: str = Query(default=""),
    approval_token: str | None = Header(default=None, alias="X-Sensitive-Approval"),
    auth: AuthContext = Depends(current_auth),
):
    require_roles(auth, "owner", "admin")
    if not ENABLE_ADMIN_RESET:
        raise HTTPException(status_code=403, detail="Reset admin desactive")
    if confirm != "RESET":
        raise HTTPException(status_code=400, detail="Confirmation requise: confirm=RESET")
    require_sensitive_approval(auth, approval_token)
    shop = auth.shop

    with Session(engine) as session:
        session.query(DebtPaymentLog).filter(DebtPaymentLog.shop_id == shop.id).delete()
        session.query(CustomerDebt).filter(CustomerDebt.shop_id == shop.id).delete()
        session.query(StockMovement).filter(StockMovement.shop_id == shop.id).delete()
        session.query(Product).filter(Product.shop_id == shop.id).delete()
        session.commit()

    return {"status": "ok", "message": "Donnees boutique effacees"}


@app.get("/")
def frontend_index():
    configured_path = Path(FRONTEND_FILE)
    file_path = configured_path if configured_path.is_absolute() else APP_ROOT / configured_path
    if not file_path.exists() and FRONTEND_FILE == "backend/index.html":
        fallback = APP_ROOT / "index.html"
        if fallback.exists():
            file_path = fallback
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Frontend file not found: {file_path}")
    return FileResponse(file_path)
