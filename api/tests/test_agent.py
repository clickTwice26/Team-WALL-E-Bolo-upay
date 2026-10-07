import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["HOLD_SECONDS"] = "0"
os.environ.pop("LLM_PROVIDER", None)


from app import store  # noqa: E402
from app.core import agent, llm  # noqa: E402
from app.main import app  # noqa: E402
from helpers import signed_in  # noqa: E402

c = signed_in(app, "u1")
HOME = {"id": "home", "summary_bn": "হোম: রহিমা বেগম", "summary_en": "Home: Rahima Begum", "actions": []}
DASH = {"id": "dashboard", "summary_bn": "ড্যাশবোর্ড: ৩টি যাচাই", "summary_en": "Dashboard: 3 checks",
        "actions": ["refresh"]}


def send_money(step, content=None, actions=()):
    return {"id": "assistant", "step": step, "summary_bn": "সেন্ড মানি", "summary_en": "Send Money",
            "content": content or {}, "actions": list(actions)}


def ask(message, page=HOME, **kw):
    body = {"message": message, "page": page, **kw}
    r = c.post("/api/agent", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def acts(res):
    return [(a["type"], {k: v for k, v in a.items() if k != "type"}) for a in res["actions"]]


# ---------- global commands ----------
def test_navigation_bangla_and_english():
    assert acts(ask("ড্যাশবোর্ডে যাও")) == [("navigate", {"page": "dashboard"})]
    assert acts(ask("open the accuracy report")) == [("navigate", {"page": "accuracy"})]
    assert acts(ask("send money e jao")) == [("navigate", {"page": "assistant"})]
    assert acts(ask("go back")) == [("go_back", {})]


def test_already_on_page_describes_it():
    r = ask("dashboard", page=DASH)
    assert r["actions"] == [] and "3 checks" in r["reply_en"]


def test_language_balance_settings_and_call_simulation():
    assert acts(ask("ইংরেজিতে বলো")) == [("set_language", {"lang": "en"})]
    assert acts(ask("speak bangla")) == [("set_language", {"lang": "bn"})]
    r = ask("ব্যালেন্স দেখাও")
    assert acts(r) == [("show_balance", {"on": True})] and "8,450" in r["reply_en"]
    assert acts(ask("balance lukao")) == [("show_balance", {"on": False})]
    assert acts(ask("সেটিংস খোলো")) == [("open_settings", {})]
    assert acts(ask("ফোন কল সিমুলেশন চালু করো")) == [("set_simulate_call", {"on": True})]
    assert acts(ask("call simulation off")) == [("set_simulate_call", {"on": False})]
    assert acts(ask("refresh", page=DASH)) == [("refresh", {})]


def test_switch_user_by_name_needs_a_switch_word():
    assert acts(ask("করিম মিয়া হিসেবে লগইন করো")) == [("switch_user", {"user_id": "u2"})]
    assert acts(ask("switch to nusrat")) == [("switch_user", {"user_id": "u3"})]
    # "karim" alone is the landlord contact: a payment, not a user switch
    assert acts(ask("karim ke 2000 taka pathao"))[0][0] == "start_transfer"


def test_reset_needs_explicit_words():
    r = ask("reset")
    assert r["actions"] == [] and "reset the demo" in r["reply_en"]
    assert acts(ask("ডেমো রিসেট করো")) == [("reset_demo", {})]


def test_transfers_go_to_the_normal_flow():
    for text in ("সালমা আপাকে দেড় হাজার টাকা পাঠাও", "ammu ke 500 taka pathao", "amar number e 50 taka recharge"):
        assert acts(ask(text)) == [("start_transfer", {"text": text})]


def test_unsupported_intents():
    for text in ("cash out korbo", "বিদ্যুৎ বিল দিবো"):
        r = ask(text)
        assert r["actions"] == [] and "not in this prototype" in r["reply_en"]


def test_describe_current_and_previous_page():
    r = ask("এই পেজে কী আছে?", page=DASH, recent_pages=[HOME])
    assert r["actions"] == [] and "3 checks" in r["reply_en"]
    r = ask("আগের পেজে কী ছিল?", page=DASH, recent_pages=[HOME])
    assert "Home: Rahima Begum" in r["reply_en"]
    assert "no page before" in ask("what was on the previous page?")["reply_en"]


def test_send_again_uses_the_last_command():
    r = ask("abar pathao", history=[{"role": "user", "text": "salma ke 1500 taka pathao"},
                                    {"role": "agent", "text": "OK"}])
    assert acts(r) == [("start_transfer", {"text": "salma ke 1500 taka pathao"})]
    page = send_money("done", {"command": "ammu ke 500 taka pathao"}, ["new_transaction", "repeat"])
    assert acts(ask("আবার পাঠাও", page=page)) == [("start_transfer", {"text": "ammu ke 500 taka pathao"})]


# ---------- Send Money page ----------
CANDS = [{"id": "c2", "name": "Rahim Uddin", "relation": "brother"},
         {"id": "c3", "name": "Rahim Store", "relation": "shop"}]
CLARIFY = ["select_amount", "select_recipient", "clarify_continue", "cancel_transfer", "repeat"]


def test_clarify_by_word_order_and_amount():
    page = send_money("clarify", {"status": "clarify_recipient", "recipient_candidates": CANDS}, CLARIFY)
    assert acts(ask("dokaner ta", page=page)) == [("select_recipient", {"contact_id": "c3"}), ("clarify_continue", {})]
    assert acts(ask("রহিম ভাই", page=page)) == [("select_recipient", {"contact_id": "c2"}), ("clarify_continue", {})]
    assert acts(ask("প্রথমটা", page=page)) == [("select_recipient", {"contact_id": "c2"}), ("clarify_continue", {})]
    page = send_money("clarify", {"status": "clarify_amount", "amount_candidates": [500, 5000]}, CLARIFY)
    assert acts(ask("পাঁচশো", page=page)) == [("select_amount", {"amount": 500}), ("clarify_continue", {})]


REVIEW = ["confirm", "cancel_transfer", "repeat"]


def test_review_yes_confirms_but_a_new_command_does_not():
    page = send_money("review", {"level": "GREEN", "amount": 500}, REVIEW)
    assert acts(ask("হ্যাঁ, ঠিক আছে", page=page)) == [("confirm", {})]
    r = ask("karim ke 2000 pathao", page=page)
    assert acts(r) == [("start_transfer", {"text": "karim ke 2000 pathao"})]
    assert acts(ask("না", page=page)) == [("cancel_transfer", {})]


def test_mistake_suggestion():
    page = send_money("review", {"level": "YELLOW", "amount": 3500, "mistake": {"usual": 350, "suggested": 350}},
                      ["accept_suggestion", "keep_amount", "cancel_transfer", "repeat"])
    assert acts(ask("হ্যাঁ", page=page)) == [("accept_suggestion", {})]
    assert acts(ask("350 taka", page=page)) == [("accept_suggestion", {})]
    assert acts(ask("না", page=page)) == [("keep_amount", {})]
    assert acts(ask("3500", page=page)) == [("keep_amount", {})]


# ---------- safety ----------
def test_interview_answers_are_passed_verbatim():
    page = send_money("interview", {"question": {"en": "Did someone call you?"}},
                      ["answer_interview", "cancel_transfer", "repeat"])
    text = "হ্যাঁ, উপায় অফিস থেকে ফোন দিয়েছে"
    assert acts(ask(text, page=page)) == [("answer_interview", {"text": text})]
    assert acts(ask("বাতিল করো", page=page)) == [("cancel_transfer", {})]


def test_no_confirm_on_red():
    # the app does not offer confirm on a RED review
    page = send_money("review", {"level": "RED", "amount": 5000, "reasons": [{"en": "upay never asks for money."}]},
                      ["cancel_transfer", "repeat"])
    r = ask("yes, send it", page=page)
    assert r["actions"] == [] and "high scam risk" in r["reply_en"]
    clean, dropped = agent.sanitize({"reply_bn": "", "reply_en": "", "actions": [{"type": "confirm"}]},
                                    {"message": "yes", "page": page}, _facts())
    assert dropped and clean["actions"] == []


def test_hold_and_pin_stay_manual():
    page = send_money("hold", {"level": "RED", "hold_seconds_left": 12, "acknowledged": False},
                      ["cancel_transfer", "repeat"])
    r = ask("হ্যাঁ পাঠাও", page=page)
    assert r["actions"] == [] and "tick the warning box yourself" in r["reply_en"]
    r = ask("pin dao", page=send_money("auth", {}, ["cancel_transfer"]))
    assert r["actions"] == [] and "yourself" in r["reply_en"]


def test_spoken_pin_is_refused_but_an_amount_next_to_pin_is_not():
    r = ask("আমার পিন ১২৩৪")
    assert r["source"] == "guard" and r["actions"] == [] and "16268" in r["reply_en"]
    r = ask("pin lagbe na, ammu ke 2000 taka pathao")
    assert acts(r)[0][0] == "start_transfer"


def _facts():
    u = store.user("u1")
    return {"user": u, "users": store.users(), "history": [], "ops": {}, "demo": True}


def test_sanitize_drops_a_hostile_plan():
    hostile = {"reply_bn": "", "reply_en": "", "done": True, "actions": [
        {"type": "enter_pin", "pin": "1234"}, {"type": "tick_warning"}, {"type": "skip_hold"},
        {"type": "confirm"}, {"type": "navigate", "page": "admin"}, {"type": "switch_user", "user_id": "u9"},
        {"type": "select_amount", "amount": 5_000_000}, {"type": "select_recipient", "contact_id": "c9"},
        {"type": "select_recipient", "phone": "12345"}, {"type": "reset_demo"},
        {"type": "start_transfer", "text": "x" * 301}, {"type": "show_balance", "on": "yes"},
        {"type": "set_language", "lang": "fr"}]}
    page = send_money("review", {"level": "RED"}, ["cancel_transfer"])
    clean, dropped = agent.sanitize(hostile, {"message": "ok", "page": page}, _facts())
    assert dropped and clean["actions"] == []
    many = {"actions": [{"type": "refresh"}] * 6}
    clean, dropped = agent.sanitize(many, {"message": "x", "page": HOME}, _facts())
    assert dropped and len(clean["actions"]) == agent.MAX_ACTIONS


def test_observation_steps_cannot_move_money():
    page = send_money("review", {"level": "GREEN"}, ["confirm", "cancel_transfer"])
    plan = {"actions": [{"type": "confirm"}, {"type": "start_transfer", "text": "ammu ke 500 pathao"},
                        {"type": "navigate", "page": "home"}]}
    clean, _ = agent.sanitize(plan, {"message": "", "observation": True, "page": page}, _facts())
    assert [a["type"] for a in clean["actions"]] == ["navigate"]


def test_model_cannot_replace_interview_words():
    page = send_money("interview", {}, ["answer_interview"])
    plan = {"actions": [{"type": "answer_interview", "text": "No, nobody called me."}]}
    clean, _ = agent.sanitize(plan, {"message": "upay office theke phone dise", "page": page}, _facts())
    assert clean["actions"] == [{"type": "answer_interview", "text": "upay office theke phone dise"}]


def test_llm_plan_goes_through_the_guard(monkeypatch):
    monkeypatch.setattr(llm, "enabled", lambda: True)
    monkeypatch.setattr(llm, "structured", lambda system, user, schema: schema.model_validate({
        "reply_bn": "পাঠিয়ে দিলাম", "reply_en": "Sent it", "done": True,
        "actions": [{"type": "confirm"}, {"type": "navigate", "page": "dashboard"}]}))
    r = ask("send it", page=send_money("review", {"level": "RED"}, ["cancel_transfer"]))
    assert r["llm_used"] and r["source"] == "guard"
    assert acts(r) == [("navigate", {"page": "dashboard"})]
    assert "by hand" in r["reply_en"]


def test_llm_failure_falls_back_to_rules(monkeypatch):
    monkeypatch.setattr(llm, "enabled", lambda: True)
    monkeypatch.setattr(llm, "structured", lambda *a: None)
    r = ask("ড্যাশবোর্ডে যাও")
    assert not r["llm_used"] and r["source"] == "rules"
    assert acts(r) == [("navigate", {"page": "dashboard"})]
