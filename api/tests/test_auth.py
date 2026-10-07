"""Sessions, the PIN guard, device-signed biometrics, demo mode and the console."""
import base64
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ["HOLD_SECONDS"] = "0"
os.environ.pop("LLM_PROVIDER", None)

import bcrypt  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth, store  # noqa: E402
from app.main import app  # noqa: E402
from helpers import signed_in, staff  # noqa: E402

anon = TestClient(app)
DAY = "2026-10-03T14:00:00+06:00"
GREEN_CMD = "Ammu ke 2000 taka pathao"
RED_CMD = "01799998888 e 2000 taka ferot pathao"


def _draft(c, text):
    p = c.post("/api/parse", json={"text": text}).json()
    phone = (p["recipient"] or {}).get("phone") or p["new_number"]
    return {"intent": p["intent"], "amount": p["amount"], "recipient_phone": phone,
            "is_return_claim": p["is_return_claim"], "command_text": text}


def _assess(c, text):
    return c.post("/api/assess", json={"draft": _draft(c, text), "now": DAY}).json()


@pytest.fixture
def u1():
    store.reset()  # also clears PIN locks left by an earlier test
    yield signed_in(app, "u1")
    store.reset()


# ---------- sessions ----------
def test_every_customer_route_needs_a_session():
    calls = [("get", "/api/me", None), ("post", "/api/parse", {"text": "x"}),
             ("post", "/api/assess", {"draft": {}}), ("post", "/api/execute", {}),
             ("post", "/api/cancel", {}), ("post", "/api/agent", {"page": {"id": "home"}}),
             ("post", "/api/handoff", {}), ("get", "/api/handoff/abc", None),
             ("post", "/api/tts", {"text": "hi"}), ("post", "/api/devices", {"public_key": "x" * 60})]
    for method, path, body in calls:
        r = getattr(anon, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 401, (path, r.status_code)
        assert r.json()["detail"]["code"] == "login_required"


def test_tampered_or_expired_tokens_are_refused():
    tok = auth.issue("u1")
    body, sig = tok.split(".")
    forged = auth._b64(b'{"sub":"u2","role":"user","amr":"pin","iat":0,"exp":9999999999}') + "." + sig
    assert auth.verify(tok)["sub"] == "u1"
    assert auth.verify(forged) is None
    assert auth.verify(auth.issue("u1", minutes=-1)) is None
    r = anon.get("/api/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_the_user_comes_from_the_token_not_the_body(u1):
    me = u1.get("/api/me").json()
    assert me["id"] == "u1" and me["recent"]
    # an old client sending another user's id still acts as itself
    p = u1.post("/api/parse", json={"user_id": "u2", "text": "ammu ke 500 taka pathao"}).json()
    assert p["recipient"]["phone"] == next(c["phone"] for c in me["contacts"] if c["id"] == "c1")


def test_one_user_cannot_touch_another_users_transfer(u1):
    a = _assess(u1, GREEN_CMD)
    u2 = signed_in(app, "u2")
    body = {"assessment_id": a["assessment_id"], "method": "pin", "pin": "1234"}
    assert u2.post("/api/execute", json=body).status_code == 404
    assert u2.post("/api/cancel", json={"assessment_id": a["assessment_id"]}).status_code == 404
    assert u1.post("/api/execute", json=body).status_code == 200


# ---------- PIN guard ----------
def test_wrong_pins_lock_the_account_across_login_and_payment(u1):
    for left in (4, 3, 2, 1):
        r = anon.post("/api/login", json={"user_id": "u1", "pin": "0000"})
        assert r.status_code == 401 and r.json()["detail"]["account_attempts_left"] == left
    r = anon.post("/api/login", json={"user_id": "u1", "pin": "0000"})
    assert r.status_code == 423 and r.json()["detail"]["retry_after"] > 14 * 60
    # locked: the right PIN, a new transfer and biometrics are all refused
    assert anon.post("/api/login", json={"user_id": "u1", "pin": "1234"}).status_code == 423
    a = _assess(u1, GREEN_CMD)
    assert u1.post("/api/execute", json={"assessment_id": a["assessment_id"], "method": "pin",
                                         "pin": "1234"}).status_code == 423
    assert u1.post("/api/execute", json={"assessment_id": a["assessment_id"],
                                         "method": "biometric"}).status_code == 423


def test_a_new_transfer_does_not_reset_the_count(u1):
    for _ in range(2):
        a = _assess(u1, GREEN_CMD)
        for _ in range(2):
            r = u1.post("/api/execute", json={"assessment_id": a["assessment_id"], "method": "pin", "pin": "0000"})
            assert r.status_code == 401
    a = _assess(u1, GREEN_CMD)
    r = u1.post("/api/execute", json={"assessment_id": a["assessment_id"], "method": "pin", "pin": "0000"})
    assert r.status_code == 423


def test_a_right_pin_clears_the_count(u1):
    for _ in range(4):
        anon.post("/api/login", json={"user_id": "u1", "pin": "0000"})
    assert anon.post("/api/login", json={"user_id": "u1", "pin": "1234"}).status_code == 200
    r = anon.post("/api/login", json={"user_id": "u1", "pin": "0000"})
    assert r.json()["detail"]["account_attempts_left"] == 4


# ---------- device-signed biometrics ----------
def _device():
    key = ec.generate_private_key(ec.SECP256R1())
    der = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return key, base64.b64encode(der).decode()


def _sign(key, payload):
    return base64.b64encode(key.sign(payload.encode(), ec.ECDSA(hashes.SHA256()))).decode()


def test_biometric_needs_a_signature_from_a_registered_device(u1):
    key, pub = _device()
    a = _assess(u1, GREEN_CMD)
    payload = auth.biometric_payload(a["assessment_id"], a["bio_challenge"])
    body = {"assessment_id": a["assessment_id"], "method": "biometric"}
    r = u1.post("/api/execute", json=body)  # "biometric: ok" with no proof
    assert r.status_code == 403 and r.json()["detail"]["code"] == "biometric_proof_required"
    r = u1.post("/api/execute", json={**body, "public_key": pub, "signature": _sign(key, payload)})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "device_not_registered"
    assert u1.post("/api/devices", json={"public_key": pub}).json()["key_id"] == auth.key_id(pub)
    wrong = _sign(key, auth.biometric_payload("another-transfer", a["bio_challenge"]))
    r = u1.post("/api/execute", json={**body, "public_key": pub, "signature": wrong})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "bad_signature"
    other_key, _ = _device()  # right public key, signed by another key
    r = u1.post("/api/execute", json={**body, "public_key": pub, "signature": _sign(other_key, payload)})
    assert r.json()["detail"]["code"] == "bad_signature"
    r = u1.post("/api/execute", json={**body, "public_key": pub, "signature": _sign(key, payload)})
    assert r.status_code == 200 and r.json()["ok"]


def test_a_device_key_is_per_user_and_biometric_stays_green_only(u1):
    key, pub = _device()
    u1.post("/api/devices", json={"public_key": pub})
    u2 = signed_in(app, "u2")
    a = _assess(u2, "shafiq bhai ke 300 taka pathao")
    if a["level"] == "GREEN":
        sig = _sign(key, auth.biometric_payload(a["assessment_id"], a["bio_challenge"]))
        r = u2.post("/api/execute", json={"assessment_id": a["assessment_id"], "method": "biometric",
                                          "public_key": pub, "signature": sig})
        assert r.json()["detail"]["code"] == "device_not_registered"
    red = _assess(u1, RED_CMD)
    assert "bio_challenge" not in red
    r = u1.post("/api/execute", json={"assessment_id": red["assessment_id"], "method": "biometric",
                                      "public_key": pub, "signature": "AAAA"})
    assert r.status_code == 403


def test_only_a_pin_session_can_register_a_device(u1, monkeypatch):
    _, pub = _device()
    switched = TestClient(app)
    tok = u1.post("/api/demo/switch", json={"user_id": "u2"}).json()["token"]
    switched.headers["Authorization"] = f"Bearer {tok}"
    r = switched.post("/api/devices", json={"public_key": pub})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "pin_login_required"
    rsa_like = base64.b64encode(b"not a key" * 8).decode()
    assert u1.post("/api/devices", json={"public_key": rsa_like}).status_code == 422


# ---------- demo mode off (a real site) ----------
def test_demo_controls_are_off_without_demo_mode(u1, monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert anon.get("/api/users").status_code == 404
    assert u1.post("/api/demo/switch", json={"user_id": "u2"}).status_code == 404
    assert u1.get("/api/dashboard").status_code == 403
    assert u1.post("/api/demo/reset").status_code == 403
    monkeypatch.setenv("ADMIN_TOKEN", "a-long-admin-secret")
    admin = {"X-Admin-Token": "a-long-admin-secret"}
    assert anon.get("/api/dashboard", headers=admin).status_code == 200
    assert anon.get("/api/dashboard", headers={"X-Admin-Token": "guess"}).status_code == 403


def test_simulated_time_of_day_only_on_a_demo_site(u1, monkeypatch):
    night = "2026-10-03T02:30:00+06:00"
    d = _draft(u1, GREEN_CMD)
    assert u1.post("/api/assess", json={"draft": d, "now": night}).json()["features"]["is_night"] == 1
    monkeypatch.delenv("DEMO_MODE", raising=False)
    feats = u1.post("/api/assess", json={"draft": d, "now": night}).json()["features"]
    assert feats["is_night"] == (1 if store.now().hour < 5 else 0)  # the server's clock, not the request


def test_agent_has_no_demo_controls_on_a_real_site(u1, monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    home = {"id": "home", "summary_en": "Home", "actions": []}
    for text in ("switch to nusrat", "ডেমো রিসেট করো"):
        r = u1.post("/api/agent", json={"message": text, "page": home}).json()
        assert not [a for a in r["actions"] if a["type"] in ("switch_user", "reset_demo")], text


# ---------- support console ----------
def test_default_console_code_only_on_a_demo_site(monkeypatch):
    monkeypatch.delenv("CONSOLE_TOKEN", raising=False)
    monkeypatch.delenv("CONSOLE_STAFF", raising=False)
    assert anon.post("/api/console/login", json={"name": "Mitu", "token": "support-demo"}).status_code == 200
    monkeypatch.delenv("DEMO_MODE", raising=False)
    r = anon.post("/api/console/login", json={"name": "Mitu", "token": "support-demo"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "console_not_configured"
    monkeypatch.setenv("CONSOLE_TOKEN", "a-real-shared-code")
    assert anon.post("/api/console/login", json={"name": "Mitu", "token": "a-real-shared-code"}).status_code == 200


def test_named_staff_accounts_with_bcrypt(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    h = bcrypt.hashpw(b"rafi-pass", bcrypt.gensalt(4)).decode()
    monkeypatch.setenv("CONSOLE_STAFF", f"Mitu:mitu-pass, Rafi:{h}")
    ok = lambda n, p: anon.post("/api/console/login", json={"name": n, "token": p}).status_code  # noqa: E731
    assert ok("Mitu", "mitu-pass") == 200 and ok("Rafi", "rafi-pass") == 200
    assert ok("Rafi", "mitu-pass") == 401 and ok("Nobody", "mitu-pass") == 401
    assert ok("Mitu", "support-demo") == 401
    rafi = staff(app, "Rafi", "rafi-pass")
    assert rafi.get("/api/console/handoffs").status_code == 200
