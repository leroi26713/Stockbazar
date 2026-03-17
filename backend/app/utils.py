from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import MAX_UPLOAD_MB, UPLOADS_DIR


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
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=422, detail="Format image non supporte")

    raw = file.file.read()
    if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=422, detail=f"Image trop volumineuse (max {MAX_UPLOAD_MB} MB)")

    filename = f"shop_{shop_id}_{prefix}_{uuid.uuid4().hex}{ext}"
    path = UPLOADS_DIR / filename
    path.write_bytes(raw)
    return f"/uploads/{filename}"
