import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["HOLD_SECONDS"] = "0"
os.environ.pop("LLM_PROVIDER", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

c = TestClient(app)
DAY = "2026-10-03T14:00:00+06:00"


def draft(text, uid="u1"):
    p = c.post("/api/parse", json={"user_id": uid, "text": text}).json()
    phone = (p["recipient"] or {}).get("phone") or p["new_number"]
    return {"intent": p["intent"], "amount": p["amount"], "recipient_phone": phone,
            "is_return_claim": p["is_return_claim"], "command_text": text}


def assess(text, uid="u1", **kw):
    body = {"user_id": uid, "draft": draft(text, uid), "now": DAY, **kw}
    return c.post("/api/assess", json=body).json()


def test_normal_send_is_green_and_biometric_works():
    c.post("/api/demo/reset")
    a = assess("Ammu ke 2000 taka pathao")
    assert a["level"] == "GREEN"
    r = c.post("/api/execute", json={"user_id": "u1", "assessment_id": a["assessment_id"],
                                     "method": "biometric"})
    assert r.status_code == 200 and r.json()["ok"]


def test_fake_official_call_goes_red_after_interview():
    a = assess("01799998888 e 5000 taka pathao", on_active_call=True)
    assert a["level"] in ("YELLOW", "RED") and a["needs_interview"]
    b = assess("01799998888 e 5000 taka pathao", on_active_call=True,
               answers=["upay office theke phone dise, bolse account block hobe"])
    assert b["level"] == "RED"
    assert any(r["key"] == "scam:fake_official" for r in b["reasons"])


def test_return_claim_without_inflow_is_red():
    a = assess("01799998888 e 2000 taka ferot pathao")
    assert a["level"] == "RED" and "return_claim_no_inflow" in a["hard_rules"]


def test_genuine_refund_is_not_red():
    a = assess("shafiq bhai ke 1000 taka ferot dao", uid="u2")
    assert a["level"] != "RED"


def test_extra_zero_triggers_mistake_check():
    a = assess("rahim store ke 3500 taka")
    assert a["mistake"] and a["mistake"]["suggested"] == 350


def test_biometric_refused_for_risky_transfer():
    a = assess("01799998888 e 2000 taka ferot pathao")
    r = c.post("/api/execute", json={"user_id": "u1", "assessment_id": a["assessment_id"],
                                     "method": "biometric"})
    assert r.status_code == 403


def test_red_needs_acknowledgement_and_pin():
    a = assess("01799998888 e 2000 taka ferot pathao")
    body = {"user_id": "u1", "assessment_id": a["assessment_id"], "method": "pin", "pin": "1234"}
    assert c.post("/api/execute", json=body).status_code == 400
    assert c.post("/api/execute", json={**body, "acknowledged_warning": True, "pin": "0000"}).status_code == 401
    assert c.post("/api/execute", json={**body, "acknowledged_warning": True}).status_code == 200


def test_cancel_counts_as_protected():
    c.post("/api/demo/reset")
    a = assess("01799998888 e 2000 taka ferot pathao")
    c.post("/api/cancel", json={"user_id": "u1", "assessment_id": a["assessment_id"]})
    d = c.get("/api/dashboard").json()
    assert d["cancelled_after_warning"] == 1 and d["amount_protected"] == 2000


def test_insufficient_balance_blocked():
    a = assess("Ammu ke 50000 taka pathao")
    assert a["level"] == "BLOCKED"
