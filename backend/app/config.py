from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

APP_ROOT = Path(__file__).resolve().parents[2]
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./stockbazar.db")
AUTO_CREATE_SCHEMA = os.getenv("AUTO_CREATE_SCHEMA", "true").lower() == "true"
CORS_ALLOW_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", "*")
LOW_STOCK_DEFAULT = int(os.getenv("LOW_STOCK_DEFAULT", "5"))
FRONTEND_FILE = os.getenv("FRONTEND_FILE", "backend/index.html")
AUTH_SECRET = os.getenv("AUTH_SECRET", "change-me-redestock-auth-secret")
TOKEN_TTL_HOURS = int(os.getenv("TOKEN_TTL_HOURS", "24"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "4"))
ENABLE_ADMIN_RESET = os.getenv("ENABLE_ADMIN_RESET", "false").lower() == "true"
SENSITIVE_APPROVAL_TTL_MINUTES = int(os.getenv("SENSITIVE_APPROVAL_TTL_MINUTES", "10"))
SENSITIVE_STOCK_OUT_QTY = int(os.getenv("SENSITIVE_STOCK_OUT_QTY", "10"))


def validate_runtime_config() -> None:
    if LOW_STOCK_DEFAULT < 0:
        raise RuntimeError("LOW_STOCK_DEFAULT doit etre positif ou nul")
    if TOKEN_TTL_HOURS < 1 or TOKEN_TTL_HOURS > 24 * 30:
        raise RuntimeError("TOKEN_TTL_HOURS doit etre entre 1 et 720")
    if MAX_UPLOAD_MB < 1 or MAX_UPLOAD_MB > 20:
        raise RuntimeError("MAX_UPLOAD_MB doit etre entre 1 et 20")
    if SENSITIVE_APPROVAL_TTL_MINUTES < 1 or SENSITIVE_APPROVAL_TTL_MINUTES > 120:
        raise RuntimeError("SENSITIVE_APPROVAL_TTL_MINUTES doit etre entre 1 et 120")
    if SENSITIVE_STOCK_OUT_QTY < 1 or SENSITIVE_STOCK_OUT_QTY > 100000:
        raise RuntimeError("SENSITIVE_STOCK_OUT_QTY doit etre entre 1 et 100000")
    if APP_ENV not in {"development", "test", "staging", "production"}:
        raise RuntimeError("APP_ENV invalide")
    if APP_ENV in {"staging", "production"} and AUTH_SECRET == "change-me-redestock-auth-secret":
        raise RuntimeError("AUTH_SECRET doit etre remplace avant le deploiement")
