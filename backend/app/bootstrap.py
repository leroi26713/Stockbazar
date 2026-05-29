from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import AUTO_CREATE_SCHEMA, DATABASE_URL
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


def ensure_sqlite_indexes() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return

    statements = [
        "CREATE INDEX IF NOT EXISTS ix_shop_users_shop_login ON shop_users (shop_id, login)",
        "CREATE INDEX IF NOT EXISTS ix_shop_users_shop_active ON shop_users (shop_id, is_active)",
        "CREATE INDEX IF NOT EXISTS ix_products_shop_sku ON products (shop_id, sku)",
        "CREATE INDEX IF NOT EXISTS ix_products_shop_id_desc ON products (shop_id, id)",
        "CREATE INDEX IF NOT EXISTS ix_products_shop_low_stock ON products (shop_id, stock_qty, min_qty)",
        "CREATE INDEX IF NOT EXISTS ix_stock_movements_shop_id_desc ON stock_movements (shop_id, id)",
        "CREATE INDEX IF NOT EXISTS ix_stock_movements_shop_product ON stock_movements (shop_id, product_id)",
        "CREATE INDEX IF NOT EXISTS ix_customer_debts_shop_id_desc ON customer_debts (shop_id, id)",
        "CREATE INDEX IF NOT EXISTS ix_customer_debts_shop_product ON customer_debts (shop_id, product_id)",
        "CREATE INDEX IF NOT EXISTS ix_customer_debts_shop_due ON customer_debts (shop_id, due_date)",
        "CREATE INDEX IF NOT EXISTS ix_customer_debts_shop_customer ON customer_debts (shop_id, customer_name)",
        "CREATE INDEX IF NOT EXISTS ix_debt_payment_logs_shop_id_desc ON debt_payment_logs (shop_id, id)",
        "CREATE INDEX IF NOT EXISTS ix_debt_payment_logs_shop_debt ON debt_payment_logs (shop_id, debt_id)",
        "CREATE INDEX IF NOT EXISTS ix_debt_payment_logs_shop_created ON debt_payment_logs (shop_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_shop_notifications_shop_read_id ON shop_notifications (shop_id, is_read, id)",
        "CREATE INDEX IF NOT EXISTS ix_shop_notifications_shop_id_desc ON shop_notifications (shop_id, id)",
    ]

    with Session(engine) as session:
        for statement in statements:
            session.execute(text(statement))
        session.execute(text("PRAGMA optimize"))
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
    ensure_sqlite_columns()
    ensure_sqlite_indexes()
    normalize_legacy_debts()
