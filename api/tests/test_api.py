import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["HOLD_SECONDS"] = "0"
os.environ.pop("LLM_PROVIDER", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from helpers import signed_in  # noqa: E402

c = TestClient(app)  # anonymous
U = {uid: signed_in(app, uid) for uid in ("u1", "u2", "u3")}
DAY = "2026-10-03T14:00:00+06:00"


def draft(text, uid="u1"):
    p = U[uid].post("/api/parse", json={"text": text}).json()
    phone = (p["recipient"] or {}).get("phone") or p["new_number"]
    return {"intent": p["intent"], "amount": p["amount"], "recipient_phone": phone,
            "is_return_claim": p["is_return_claim"], "command_text": text}


def assess(text, uid="u1", **kw):
    body = {"draft": draft(text, uid), "now": DAY, **kw}
    return U[uid].post("/api/assess", json=body).json()


def test_normal_send_is_green_and_pin_works():
    U["u1"].post("/api/demo/reset")
    a = assess("Ammu ke 2000 taka pathao")
    assert a["level"] == "GREEN" and a["bio_challenge"]
    r = U["u1"].post("/api/execute", json={"assessment_id": a["assessment_id"], "method": "pin", "pin": "1234"})
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
    r = U["u1"].post("/api/execute", json={"assessment_id": a["assessment_id"],
                                     "method": "biometric"})
    assert r.status_code == 403


def test_red_needs_acknowledgement_and_pin():
    a = assess("01799998888 e 2000 taka ferot pathao")
    body = {"assessment_id": a["assessment_id"], "method": "pin", "pin": "1234"}
    assert U["u1"].post("/api/execute", json=body).status_code == 400
    assert U["u1"].post("/api/execute", json={**body, "acknowledged_warning": True, "pin": "0000"}).status_code == 401
    assert U["u1"].post("/api/execute", json={**body, "acknowledged_warning": True}).status_code == 200


def test_cancel_counts_as_protected():
    U["u1"].post("/api/demo/reset")
    a = assess("01799998888 e 2000 taka ferot pathao")
    U["u1"].post("/api/cancel", json={"assessment_id": a["assessment_id"]})
    d = U["u1"].get("/api/dashboard").json()
    assert d["cancelled_after_warning"] == 1 and d["amount_protected"] == 2000


def test_insufficient_balance_blocked():
    a = assess("Ammu ke 50000 taka pathao")
    assert a["level"] == "BLOCKED"


def test_later_no_does_not_cancel_earlier_scam_answer():
    b = assess("01799998888 e 5000 taka pathao", on_active_call=True,
               answers=["হ্যাঁ, উপায় অফিস থেকে ফোন দিয়েছে", "না, কেউ ফোন করেনি", "না"])
    assert b["level"] == "RED"


def test_bangla_negative_verb_is_not_a_hit():
    from app.core import scam
    assert scam.match("কেউ ওটিপি চায়নি")["score"] == 0


def test_scam_warning_before_amount_or_recipient_is_known():
    p = U["u1"].post("/api/parse", json={"text":
               "উপায় অফিস থেকে ফোন দিয়েছে হাজার টাকা পাঠাতে বা পিন নাম্বার বলতে"}).json()
    assert p["status"] == "need_recipient"
    w = p["scam_warning"]
    assert w["category"] == "fake_official" and "16268" in w["en"] and "১৬২৬৮" in w["bn"]
    assert p["question_en"] == "Who should receive it? Say a name or number."


def test_no_early_warning_for_normal_or_refund_commands():
    for text in ("ammu ke 500 taka pathao", "ammu ke taka pathao", "vul kore pathaisi ferot dao"):
        p = U["u1"].post("/api/parse", json={"text": text}).json()
        assert "scam_warning" not in p, text


def test_login_pin():
    r = c.post("/api/login", json={"user_id": "u1", "pin": "1234"})
    assert r.status_code == 200 and r.json()["token"]
    assert c.post("/api/login", json={"user_id": "u1", "pin": "9999"}).status_code == 401
