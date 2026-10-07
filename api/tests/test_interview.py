"""Adaptive scam interview, and cash-out / merchant payment through the same checks."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ["HOLD_SECONDS"] = "0"
os.environ.pop("LLM_PROVIDER", None)

import pytest  # noqa: E402

from app import store  # noqa: E402
from app.core import interview  # noqa: E402
from app.main import app  # noqa: E402
from helpers import signed_in  # noqa: E402

DAY, NIGHT = "2026-10-03T14:00:00+06:00", "2026-10-03T02:30:00+06:00"


@pytest.fixture
def u1():
    store.reset()
    yield signed_in(app, "u1")
    store.reset()


def assess(c, text, now=DAY, **kw):
    p = c.post("/api/parse", json={"text": text}).json()
    phone = (p["recipient"] or {}).get("phone") or p["new_number"]
    d = {"intent": p["intent"], "amount": p["amount"], "recipient_phone": phone,
         "is_return_claim": p["is_return_claim"], "command_text": text}
    return p, c.post("/api/assess", json={"draft": d, "now": now, **kw}).json()


def test_first_question_follows_the_strongest_signal():
    base = {"inflow_then_outflow": 0, "on_active_call": 0, "hour_unusual_for_user": 0,
            "is_cash_out": 0, "is_new_recipient": 0}
    assert interview.first(base, {"is_return_claim": True})["id"] == "money_arrived"
    assert interview.first(dict(base, inflow_then_outflow=1), {})["id"] == "pass_on"
    assert interview.first(dict(base, on_active_call=1, is_new_recipient=1), {})["id"] == "on_call"
    assert interview.first(dict(base, is_new_recipient=1), {})["id"] == "how_know"
    assert interview.first(base, {})["id"] == "who"


def test_follow_ups_depend_on_the_answers():
    nxt = interview.next_question
    assert nxt(["how_know"], ["bhai bolse accident hoyeche, notun number theke bolchi"])["id"] == "relative_check"
    assert nxt(["how_know"], ["commission pabo bolse, onno number e pathate hobe"])["id"] == "commission"
    assert nxt(["how_know"], ["na, ami nijei pathacchi"])["id"] == "who"
    assert nxt(["on_call"], ["upay office theke phone dise"]) is None  # already settled: RED
    assert nxt(["who", "official", "otp"], ["a", "b", "c"]) is None  # at most 3
    assert nxt(["who"], []) is None  # the question was not answered yet


def test_api_asks_adaptively_and_scores_the_answers(u1):
    _, a = assess(u1, "01799998888 e 5000 taka pathao", on_active_call=True)
    assert a["needs_interview"] and a["interview_mode"] == "adaptive" and a["interview_max"] == 3
    assert [q["id"] for q in a["interview"]] == ["on_call"]
    r = u1.post("/api/interview/next", json={"assessment_id": a["assessment_id"], "asked": ["on_call"],
                                             "answers": ["amar bhai, bolse bipode porse"]}).json()
    assert r["done"] is False and r["question"]["id"] in ("relative_check", "who")
    r = u1.post("/api/interview/next", json={"assessment_id": a["assessment_id"], "asked": ["on_call"],
                                             "answers": ["customer care theke bolse kyc update korte hobe"]}).json()
    assert r == {"done": True, "question": None}
    u2 = signed_in(app, "u2")
    assert u2.post("/api/interview/next", json={"assessment_id": a["assessment_id"]}).status_code == 404
    _, b = assess(u1, "01799998888 e 5000 taka pathao", on_active_call=True,
                  answers=["customer care theke bolse kyc update korte hobe"])
    assert b["level"] == "RED"


def test_cash_out_and_merchant_payment_are_understood(u1):
    p, _ = assess(u1, "01612345678 e 2000 taka cash out korbo")
    assert p["intent"] == "cash_out" and p["new_number"] == "01612345678"
    p = u1.post("/api/parse", json={"text": "500 taka cash out korbo"}).json()
    assert p["status"] == "need_recipient" and "agent" in p["question_en"]
    p = u1.post("/api/parse", json={"text": "01812345678 e 300 taka payment koro"}).json()
    assert p["intent"] == "merchant_payment" and p["status"] == "ok"


def test_night_cash_out_of_most_of_the_balance_at_a_new_agent_is_red(u1):
    _, a = assess(u1, "01612345678 e 6000 taka cash out korbo", now=NIGHT)
    assert a["level"] == "RED" and "cash_out_night_new_agent" in a["hard_rules"]
    assert any(r["key"] == "cash_out_night_new_agent" for r in a["reasons"])
    _, day = assess(u1, "01612345678 e 6000 taka cash out korbo")
    assert "cash_out_night_new_agent" not in day["hard_rules"]


def test_a_cash_out_runs_through_execute(u1):
    _, a = assess(u1, "01612345678 e 500 taka cash out korbo")
    body = {"assessment_id": a["assessment_id"], "method": "pin", "pin": "1234", "acknowledged_warning": True}
    r = u1.post("/api/execute", json=body)
    assert r.status_code == 200 and r.json()["transaction"]["balance"] < 8450
    assert u1.get("/api/me").json()["recent"][0]["type"] == "cash_out"
