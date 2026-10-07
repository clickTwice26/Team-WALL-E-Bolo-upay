"""Signed-in test clients."""
from fastapi.testclient import TestClient


def signed_in(app, uid: str, pin: str = "1234") -> TestClient:
    """A client that carries ``uid``'s session token on every request."""
    c = TestClient(app)
    r = c.post("/api/login", json={"user_id": uid, "pin": pin})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return c


def staff(app, name: str = "Mitu", code: str = "support-demo") -> TestClient:
    """A support-console client signed in as ``name``."""
    c = TestClient(app)
    r = c.post("/api/console/login", json={"name": name, "token": code})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return c
