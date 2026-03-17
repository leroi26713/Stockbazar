from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from app.config import AUTH_SECRET, TOKEN_TTL_HOURS
from app.database import engine
from app.models import ShopAccount


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
