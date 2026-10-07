"""Sessions, demo mode, admin access, the PIN guard and device keys.

/api/login checks the PIN and issues a short-lived signed token. Every user
endpoint takes the user from that token, never from the request body.

DEMO_MODE=true turns on what only a public demo needs: the persona picker,
switching demo users, resetting the demo data, simulating the time of day and
the default support-console code. It is off unless set.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from datetime import timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import store

log = logging.getLogger("bolo.auth")

SESSION_MINUTES = int(os.getenv("SESSION_MINUTES", "30"))
MAX_PIN_TRIES = 5      # wrong PINs before the account locks
LOCK_MINUTES = 15      # first lock; doubles with every further wrong PIN

_secret_env = os.getenv("AUTH_SECRET")
if not _secret_env:
    log.warning("AUTH_SECRET is not set: using a random key, so sessions end when the server restarts")
_SECRET = (_secret_env or secrets.token_hex(32)).encode()


def demo_mode() -> bool:
    return (os.getenv("DEMO_MODE") or "").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------- tokens
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue(sub: str, role: str = "user", amr: str = "pin", minutes: int | None = None) -> str:
    """A signed token: base64(claims).base64(HMAC-SHA256)."""
    now = int(time.time())
    claims = {"sub": sub, "role": role, "amr": amr, "iat": now,
              "exp": now + 60 * (minutes or SESSION_MINUTES)}
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_SECRET, body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify(token: str) -> dict | None:
    try:
        body, sig = token.split(".")
        good = _b64(hmac.new(_SECRET, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        claims = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    return claims if claims.get("exp", 0) > time.time() else None


_bearer = HTTPBearer(auto_error=False)


@dataclass
class Session:
    user: dict
    claims: dict


def _claims(creds: HTTPAuthorizationCredentials | None, role: str) -> dict:
    claims = verify(creds.credentials) if creds else None
    if not claims or claims.get("role") != role:
        raise HTTPException(401, {"code": "login_required"})
    return claims


def current(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Session:
    """The signed-in customer. 401 {"code": "login_required"} without a valid token."""
    claims = _claims(creds, "user")
    u = store.user(claims["sub"])
    if not u:
        raise HTTPException(401, {"code": "login_required"})
    return Session(u, claims)


def staff(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """The signed-in support agent's name (from the token, not the request)."""
    return _claims(creds, "staff")["sub"]


def _admin_ok(token: str) -> bool:
    expected = os.getenv("ADMIN_TOKEN") or ""
    return bool(expected) and hmac.compare_digest(token.encode(), expected.encode())


def demo_user_or_admin(x_admin_token: str = Header(default=""),
                       creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    """Ops data and demo controls: any signed-in user on a demo site, otherwise
    only a request carrying ADMIN_TOKEN in the X-Admin-Token header."""
    if _admin_ok(x_admin_token):
        return
    if demo_mode():
        _claims(creds, "user")
        return
    raise HTTPException(403, {"code": "admin_only"})


def admin_only(x_admin_token: str = Header(default="")) -> None:
    if not _admin_ok(x_admin_token):
        raise HTTPException(403, {"code": "admin_only"})


# ---------------------------------------------------------------- PIN guard
def ensure_unlocked(uid: str) -> None:
    """423 while the account is locked: no payment, not even with biometrics."""
    now = store.now()
    _, locked_until = store.pin_state(uid)
    if locked_until and locked_until > now:
        raise HTTPException(423, {"code": "locked", "retry_after": int((locked_until - now).total_seconds()) + 1})


def check_pin(uid: str, pin: str | None) -> None:
    """Raise 423 while the account is locked, 401 for a wrong PIN.

    Wrong PINs count per account across login and payment, so starting a new
    transfer does not reset the count. After MAX_PIN_TRIES the account locks
    for LOCK_MINUTES, doubling with every further wrong PIN.
    """
    ensure_unlocked(uid)
    now = store.now()
    failures, _ = store.pin_state(uid)
    if pin and store.check_pin(uid, pin):
        if failures:
            store.set_pin_state(uid, 0, None)
        return
    failures += 1
    over = failures - MAX_PIN_TRIES
    if over >= 0:
        until = now + timedelta(minutes=LOCK_MINUTES * 2 ** over)
        store.set_pin_state(uid, failures, until)
        log.warning("account %s locked after %d wrong PINs", uid, failures)
        raise HTTPException(423, {"code": "locked", "retry_after": int((until - now).total_seconds())})
    store.set_pin_state(uid, failures, None)
    raise HTTPException(401, {"code": "wrong_pin", "account_attempts_left": MAX_PIN_TRIES - failures})


# ---------------------------------------------------------------- device keys
def key_id(public_key_b64: str) -> str:
    return hashlib.sha256(base64.b64decode(public_key_b64)).hexdigest()[:16]


def load_device_key(public_key_b64: str) -> ec.EllipticCurvePublicKey:
    """A P-256 public key (base64 DER SubjectPublicKeyInfo), or ValueError."""
    try:
        key = serialization.load_der_public_key(base64.b64decode(public_key_b64, validate=True))
    except Exception as e:  # bad base64 or not a key
        raise ValueError("not a public key") from e
    if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1":
        raise ValueError("not a P-256 key")
    return key


def biometric_payload(assessment_id: str, challenge: str) -> str:
    """What the phone signs: tied to one transfer and one server challenge."""
    return f"bolo-upay:{assessment_id}:{challenge}"


def verify_device_signature(uid: str, public_key_b64: str, payload: str, signature_b64: str) -> str:
    """Check a biometric approval. Returns '' when valid, else an error code."""
    try:
        registered = store.device_registered(uid, key_id(public_key_b64))
    except ValueError:  # not base64
        return "bad_signature"
    if not registered:
        return "device_not_registered"
    try:
        key = load_device_key(public_key_b64)
        key.verify(base64.b64decode(signature_b64, validate=True), payload.encode(), ec.ECDSA(hashes.SHA256()))
    except (ValueError, InvalidSignature):
        return "bad_signature"
    return ""
