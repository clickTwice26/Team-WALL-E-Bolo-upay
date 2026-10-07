"""Failure policy and model health: wrong-warning reports, the monitor, request ids."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ["HOLD_SECONDS"] = "0"
os.environ.pop("LLM_PROVIDER", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import monitor, store  # noqa: E402
from app.main import app  # noqa: E402
from helpers import signed_in  # noqa: E402

DAY = "2026-10-03T14:00:00+06:00"
anon = TestClient(app)


def check(c, text):
    p = c.post("/api/parse", json={"text": text}).json()
    phone = (p["recipient"] or {}).get("phone") or p["new_number"]
    d = {"intent": p["intent"], "amount": p["amount"], "recipient_phone": phone,
         "is_return_claim": p["is_return_claim"], "command_text": text}
    return c.post("/api/assess", json={"draft": d, "now": DAY}).json()


@pytest.fixture
def u1():
    store.reset()
    yield signed_in(app, "u1")
    store.reset()


def test_wrong_warning_report_only_for_own_warnings(u1):
    red = check(u1, "01799998888 e 2000 taka ferot pathao")
    green = check(u1, "Ammu ke 500 taka pathao")
    assert u1.post("/api/feedback", json={"assessment_id": red["assessment_id"], "kind": "wrong_warning"}).json()["ok"]
    r = u1.post("/api/feedback", json={"assessment_id": green["assessment_id"], "kind": "wrong_warning"})
    assert r.status_code == 409  # GREEN was not a warning
    u2 = signed_in(app, "u2")
    assert u2.post("/api/feedback", json={"assessment_id": red["assessment_id"], "kind": "wrong_warning"}).status_code == 404
    assert anon.post("/api/feedback", json={"assessment_id": red["assessment_id"], "kind": "wrong_warning"}).status_code == 401


def test_monitor_reports_mix_overrides_feedback_and_access(u1, monkeypatch):
    red = check(u1, "01799998888 e 2000 taka ferot pathao")
    check(u1, "Ammu ke 500 taka pathao")
    u1.post("/api/feedback", json={"assessment_id": red["assessment_id"], "kind": "wrong_warning"})
    r = u1.post("/api/execute", json={"assessment_id": red["assessment_id"], "method": "pin", "pin": "1234",
                                      "acknowledged_warning": True})
    assert r.status_code == 200
    m = u1.get("/api/admin/monitor").json()
    assert m["checks"] == 2 and m["level_mix"]["RED"] == 0.5 and m["level_mix"]["GREEN"] == 0.5
    assert m["red_override_rate"] == 1.0 and m["wrong_warning_reports"] == 1
    assert sum(m["score_histogram"]) == 2 and m["model"] == "gradient_boosting"
    assert any("too few to judge drift" in a for a in m["alerts"]) and m["drift_psi"] == {}
    assert anon.get("/api/admin/monitor").status_code == 401
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert u1.get("/api/admin/monitor").status_code == 403  # a real site: ops only


def test_psi_flags_a_shifted_input():
    edges, share = [1.0, 2.0], [0.5, 0.3, 0.2]
    same = [0.5] * 50 + [1.5] * 30 + [2.5] * 20
    shifted = [2.5] * 90 + [0.5] * 10
    assert monitor.psi(edges, share, same) < 0.01
    assert monitor.psi(edges, share, shifted) > monitor.PSI_ALERT


def test_drift_alert_with_enough_checks(u1, monkeypatch):
    for _ in range(monitor.MIN_CHECKS):
        check(u1, "Ammu ke 500 taka pathao")
    # pretend training never saw a payment to a known contact
    ref = monitor._reference()
    ref["features"]["log_recipient_age"] = {"edges": [0.5], "share": [0.99, 0.01]}
    monkeypatch.setattr(monitor, "_reference", lambda: ref)
    m = monitor.report()
    assert m["drift_psi"]["log_recipient_age"] > monitor.PSI_ALERT
    assert any("log_recipient_age" in a for a in m["alerts"])


def test_every_api_response_has_a_request_id():
    r = anon.get("/api/health")
    assert len(r.headers["X-Request-ID"]) == 12
    assert anon.get("/api/health", headers={"X-Request-ID": "abc123"}).headers["X-Request-ID"] == "abc123"
