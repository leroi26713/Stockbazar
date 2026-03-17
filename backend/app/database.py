from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import AUTO_CREATE_SCHEMA, DATABASE_URL, validate_runtime_config


class Base(DeclarativeBase):
    pass


def build_engine() -> Any:
    connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
    return create_engine(DATABASE_URL, echo=False, future=True, connect_args=connect_args)


validate_runtime_config()
engine = build_engine()
