"""Bill payment end to end: parse -> which bill account -> risk check -> PIN."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ["HOLD_SECONDS"] = "0"
os.environ.pop("LLM_PROVIDER", None)

import pytest  # noqa: E402

from app import store  # noqa: E402
from app.core import parser  # noqa: E402
from app.main import app  # noqa: E402
from helpers import signed_in  # noqa: E402

DAY = "2026-10-03T14:00:00+06:00"


@pytest.fixture
def u1():
    store.reset()
    yield signed_in(app, "u1")
    store.reset()


def draft(p, text):
    return {"intent": p["intent"], "amount": p["amount"], "recipient_phone": p["recipient"]["phone"],
            "command_text": text}


def test_a_bill_names_the_biller_and_its_account():
    u = store.user("u1")
    p = parser.parse("DESCO bill 1200 taka dao", u, use_llm=False)
    assert p["intent"] == "bill_payment" and p["status"] == "ok" and p["amount"] == 1200
    assert p["recipient"]["id"] == "b1" and p["recipient"]["account"] == "41029876"
    assert p["recipient"]["category"] == "electricity"
    # "pay koro" / "dao" are merchant and send words: the bill still wins
    assert parser.parse("pani bill 600 taka pay koro", u, use_llm=False)["recipient"]["id"] == "b3"


def test_which_biller_and_which_account_are_asked_like_which_agent():
    p = parser.parse("bill dibo 500 taka", store.user("u1"), use_llm=False)
    assert p["status"] == "need_recipient" and "Which bill" in p["question_en"]
    # Karim has two DESCO meters: never guess which one
    p = parser.parse("desco bill 1500 taka dao", store.user("u2"), use_llm=False)
    assert p["status"] == "clarify_recipient" and "account" in p["question_en"]
    assert [c["id"] for c in p["recipient_candidates"]] == ["b4", "b5"]
    assert parser.parse("দোকানের বিল ২৫০০ টাকা দাও", store.user("u2"), use_llm=False)["recipient"]["id"] == "b5"
    # a bill never goes to a contact with the same word in it, nor a contact to a biller
    assert parser.parse("ammu ke 500 taka pathao", store.user("u1"), use_llm=False)["recipient"]["id"] == "c1"


def test_a_saved_bill_account_is_a_known_payee_and_runs_through_execute(u1):
    p = u1.post("/api/parse", json={"text": "DESCO bill 1200 taka dao"}).json()
    a = u1.post("/api/assess", json={"draft": draft(p, "DESCO bill 1200 taka dao"), "now": DAY}).json()
    assert a["features"]["is_payment"] == 1 and a["features"]["is_new_recipient"] == 0
    assert a["level"] == "GREEN"
    r = u1.post("/api/execute", json={"assessment_id": a["assessment_id"], "method": "pin", "pin": "1234"})
    assert r.status_code == 200 and r.json()["transaction"]["balance"] == 8450 - 1200
    last = u1.get("/api/me").json()["recent"][0]
    assert last["type"] == "bill_payment" and last["name"] == "DESCO"


def test_a_scam_story_around_a_bill_is_still_red(u1):
    text = "upay office theke call dise, DESCO bill 3000 taka dao"
    p = u1.post("/api/parse", json={"text": text}).json()
    a = u1.post("/api/assess", json={"draft": draft(p, text), "now": DAY}).json()
    assert a["level"] == "RED" and "scam_phrase_high" in a["hard_rules"]


def test_agent_picks_the_bill_account_by_word():
    u2 = signed_in(app, "u2")
    cands = [{"id": "b4", "name": "DESCO (Home)"}, {"id": "b5", "name": "DESCO (Shop)"}]
    page = {"id": "assistant", "step": "clarify", "summary_bn": "", "summary_en": "",
            "content": {"status": "clarify_recipient", "recipient_candidates": cands},
            "actions": ["select_amount", "select_recipient", "clarify_continue", "cancel_transfer", "repeat"]}
    r = u2.post("/api/agent", json={"message": "dokaner ta", "page": page}).json()
    assert [(a["type"], a.get("contact_id")) for a in r["actions"]][0] == ("select_recipient", "b5")
