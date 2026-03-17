from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import AUTO_CREATE_SCHEMA, DATABASE_URL, UPLOADS_DIR
from app.database import Base, engine
from app.models import CustomerDebt


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


def bootstrap_app() -> None:
    if AUTO_CREATE_SCHEMA:
        Base.metadata.create_all(engine)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    ensure_sqlite_columns()
    normalize_legacy_debts()
