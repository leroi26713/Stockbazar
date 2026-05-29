from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import AUTO_CREATE_SCHEMA, DATABASE_URL, validate_runtime_config

def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Base(DeclarativeBase):
    pass


def build_engine() -> Any:
    connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
    db_url = normalize_database_url(DATABASE_URL)
    return create_engine(db_url, echo=False, future=True, connect_args=connect_args)


validate_runtime_config()
engine = build_engine()
