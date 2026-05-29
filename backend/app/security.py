from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import AUTH_SECRET, SENSITIVE_APPROVAL_TTL_MINUTES, TOKEN_TTL_HOURS
from app.database import engine
from app.models import ShopAccount, ShopUser


@dataclass
class AuthContext:
    shop: ShopAccount
    role: str
    actor_type: str
    actor_id: int
    actor_name: str
    email: str


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


def _sign_payload(payload: dict) -> str:
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(AUTH_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64url_encode(sig)}"


def create_token(
    shop_id: int,
    email: str,
    role: str = "owner",
    actor_type: str = "shop",
    actor_id: int | None = None,
    actor_name: str = "",
) -> str:
    payload = {
        "sub": shop_id,
        "email": email,
        "role": role,
        "actor_type": actor_type,
        "actor_id": actor_id if actor_id is not None else shop_id,
        "actor_name": actor_name,
        "exp": int(time.time()) + TOKEN_TTL_HOURS * 3600,
    }
    return _sign_payload(payload)


def create_sensitive_approval(shop_id: int, actor_type: str, actor_id: int, role: str) -> tuple[str, int]:
    expires_in = SENSITIVE_APPROVAL_TTL_MINUTES * 60
    payload = {
        "type": "sensitive_approval",
        "sub": shop_id,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "role": role,
        "exp": int(time.time()) + expires_in,
    }
    return _sign_payload(payload), expires_in


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


def current_auth(authorization: str | None = Header(default=None)) -> AuthContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization Bearer requis")

    token = authorization.split(" ", 1)[1].strip()
    payload = parse_token(token)
    shop_id = int(payload.get("sub", 0))

    with Session(engine) as session:
        shop = session.get(ShopAccount, shop_id)
        if not shop:
            raise HTTPException(status_code=401, detail="Compte introuvable")

        role = str(payload.get("role") or "owner")
        actor_type = str(payload.get("actor_type") or "shop")
        actor_id = int(payload.get("actor_id") or shop.id)
        actor_name = str(payload.get("actor_name") or shop.shop_name)

        if actor_type == "staff":
            staff = session.get(ShopUser, actor_id)
            if not staff or not staff.is_active or staff.shop_id != shop.id:
                raise HTTPException(status_code=401, detail="Utilisateur interne introuvable")

        return AuthContext(
            shop=shop,
            role=role,
            actor_type=actor_type,
            actor_id=actor_id,
            actor_name=actor_name,
            email=str(payload.get("email") or shop.email),
        )


def current_shop(auth: AuthContext = Depends(current_auth)) -> ShopAccount:
    return auth.shop


def require_roles(auth: AuthContext, *roles: str) -> None:
    if auth.role not in roles:
        raise HTTPException(status_code=403, detail="Role insuffisant pour cette action")


def verify_actor_password(auth: AuthContext, password: str) -> None:
    with Session(engine) as session:
        if auth.actor_type == "shop":
            shop = session.get(ShopAccount, auth.shop.id)
            if not shop:
                raise HTTPException(status_code=401, detail="Compte introuvable")
            if not verify_password(password, shop.password_hash):
                raise HTTPException(status_code=403, detail="Mot de passe invalide")
            return

        staff = session.get(ShopUser, auth.actor_id)
        if not staff or not staff.is_active or staff.shop_id != auth.shop.id:
            raise HTTPException(status_code=401, detail="Utilisateur interne introuvable")
        if not verify_password(password, staff.password_hash):
            raise HTTPException(status_code=403, detail="Mot de passe invalide")


def require_sensitive_approval(auth: AuthContext, approval_token: str | None) -> None:
    if not approval_token:
        raise HTTPException(status_code=403, detail="Reconfirmation requise")

    payload = parse_token(approval_token)
    if payload.get("type") != "sensitive_approval":
        raise HTTPException(status_code=403, detail="Jeton de reconfirmation invalide")
    if int(payload.get("sub", 0)) != auth.shop.id:
        raise HTTPException(status_code=403, detail="Jeton de reconfirmation invalide")
    if str(payload.get("role") or "") not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Jeton de reconfirmation invalide")
    if str(payload.get("actor_type") or "") != auth.actor_type:
        raise HTTPException(status_code=403, detail="Jeton de reconfirmation invalide")
    if int(payload.get("actor_id") or 0) != auth.actor_id:
        raise HTTPException(status_code=403, detail="Jeton de reconfirmation invalide")
