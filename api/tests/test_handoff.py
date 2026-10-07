import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["HOLD_SECONDS"] = "0"
os.environ.pop("LLM_PROVIDER", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from helpers import signed_in, staff  # noqa: E402

c = TestClient(app)  # anonymous
U = {uid: signed_in(app, uid) for uid in ("u1", "u2", "u3")}
MITU, RAFI = staff(app, "Mitu"), staff(app, "Rafi")
HOME = {"id": "home", "summary_en": "Home", "actions": []}
DAY = "2026-10-03T14:00:00+06:00"


def ask(message, page=HOME, history=()):
    r = U["u1"].post("/api/agent", json={"message": message, "page": page, "history": list(history)})
    return r.json()


def connect(res):
    a = [x for x in res["actions"] if x["type"] == "connect_human"]
    return a[0]["category"] if a else None


def send_money(step, content=None, actions=()):
    return {"id": "assistant", "step": step, "content": content or {}, "actions": list(actions)}


# ---------- when the agent hands off ----------
def test_asking_for_a_person_in_bangla_and_english():
    for text in ("মানুষের সাথে কথা বলতে চাই", "talk to a person", "connect me", "manusher sathe kotha bolte chai"):
        r = ask(text)
        assert connect(r) == "talk_to_human", text
        assert "PIN" in r["reply_en"]


def test_problem_reports_have_categories():
    assert connect(ask("আমাকে প্রতারণা করেছে")) == "scam"
    assert connect(ask("amar taka chole geche")) == "money_lost"
    assert connect(ask("vul number e chole gese, abhijog korbo")) == "dispute"


def test_ferot_pathao_with_amount_still_goes_to_the_risk_check():
    r = ask("01799998888 e 2000 taka ferot pathao")
    assert [a["type"] for a in r["actions"]] == ["start_transfer"]


def test_scam_words_in_the_interview_stay_answers_but_a_request_is_urgent():
    page = send_money("interview", {}, ["answer_interview", "cancel_transfer", "repeat"])
    r = ask("ha, amake thokiyeche mone hoy", page)
    assert r["actions"][0]["type"] == "answer_interview"
    assert connect(ask("talk to a person", page)) == "scam"
    red = send_money("review", {"level": "RED"}, ["cancel_transfer", "repeat"])
    assert connect(ask("মানুষের সাথে কথা বলতে চাই", red)) == "scam"
    assert "talk to a person" in ask("yes", red)["reply_en"]


def test_second_miss_offers_a_person_and_yes_connects():
    first = ask("blorp zzz")
    assert connect(first) is None
    second = ask("glarb", history=[{"role": "user", "text": "blorp zzz"}, {"role": "agent", "text": first["reply_en"]}])
    assert "talk to a person" in second["reply_en"] and not second["actions"]
    yes = ask("হ্যাঁ", history=[{"role": "agent", "text": second["reply_bn"]}])
    assert connect(yes) == "not_understood"


# ---------- handoff API ----------
def start(uid="u1", category="talk_to_human", page=None):
    return U[uid].post("/api/handoff", json={"category": category, "reason": "help",
                                        "page": page or HOME, "transcript": [{"role": "user", "text": "help"}]}).json()


def test_start_resume_message_poll_and_privacy():
    U["u1"].post("/api/demo/reset")
    h = start()
    assert h["status"] == "waiting" and h["queue_position"] == 1
    assert "PIN" in h["messages"][0]["text"]  # nobody from upay asks for a PIN
    assert start()["id"] == h["id"]  # resumes the open chat
    U["u1"].post(f"/api/handoff/{h['id']}/messages", json={"text": "hello"})
    p = U["u1"].get(f"/api/handoff/{h['id']}", params={"after": h["messages"][-1]["id"]}).json()
    assert [m["text"] for m in p["messages"]] == ["hello"]
    assert U["u2"].get(f"/api/handoff/{h['id']}").status_code == 404


def test_pin_is_masked_and_hidden_from_the_console():
    U["u1"].post("/api/demo/reset")
    h = start()
    U["u1"].post(f"/api/handoff/{h['id']}/messages", json={"text": "amar pin 4321"})
    msgs = U["u1"].get(f"/api/handoff/{h['id']}").json()["messages"]
    assert "4321" not in str(msgs) and "••••" in msgs[-2]["text"] and msgs[-1]["sender"] == "system"
    detail = MITU.get(f"/api/console/handoffs/{h['id']}").json()
    assert "4321" not in str(detail)


def test_priority_and_queue_order():
    U["u1"].post("/api/demo/reset")
    normal = start("u1")
    urgent = start("u2", "scam")
    red_page = start("u3", "talk_to_human", {"id": "assistant", "step": "review", "content": {"level": "RED"}})
    assert (normal["priority"], urgent["priority"], red_page["priority"]) == ("normal", "urgent", "urgent")
    rows = MITU.get("/api/console/handoffs").json()
    assert [r["id"] for r in rows["handoffs"]] == [urgent["id"], red_page["id"], normal["id"]]
    assert rows["counts"]["waiting"] == 3 and rows["counts"]["urgent"] == 2
    assert U["u1"].get(f"/api/handoff/{normal['id']}").json()["queue_position"] == 3


def test_console_needs_a_staff_sign_in():
    assert c.get("/api/console/handoffs").status_code == 401
    assert c.get("/api/console/handoffs", headers={"X-Console-Token": "support-demo"}).status_code == 401
    assert c.post("/api/console/login", json={"name": "Mitu", "token": "nope"}).status_code == 401
    assert c.post("/api/console/login", json={"name": "Mitu", "token": "support-demo"}).status_code == 200
    # a customer's token is not a staff token
    assert U["u1"].get("/api/console/handoffs").status_code == 401


def test_claim_chat_close_and_a_new_chat_after_close():
    U["u1"].post("/api/demo/reset")
    h = start()
    url = f"/api/console/handoffs/{h['id']}"
    assert MITU.post(url + "/claim").status_code == 200
    assert RAFI.post(url + "/claim").status_code == 409
    assert RAFI.post(url + "/messages", json={"text": "hi"}).status_code == 409
    # the name comes from the sign-in, not from the request
    assert RAFI.post(url + "/messages", json={"agent": "Mitu", "text": "hi"}).status_code == 409
    assert MITU.post(url + "/messages", json={"text": "আপনার টাকা নিরাপদ"}).status_code == 200
    p = U["u1"].get(f"/api/handoff/{h['id']}").json()
    assert p["status"] == "active" and p["agent_name"] == "Mitu"
    assert p["messages"][-1] == {**p["messages"][-1], "sender": "agent", "name": "Mitu"}
    assert MITU.post(url + "/close", json={"resolution": "Explained"}).status_code == 200
    assert U["u1"].post(f"/api/handoff/{h['id']}/messages", json={"text": "x"}).status_code == 409
    assert start()["id"] != h["id"]


def test_staff_stops_a_pending_transfer():
    U["u1"].post("/api/demo/reset")
    p = U["u1"].post("/api/parse", json={"text": "01799998888 e 2000 taka ferot pathao"}).json()
    draft = {"intent": p["intent"], "amount": p["amount"], "recipient_phone": p["new_number"],
             "is_return_claim": True, "command_text": "01799998888 e 2000 taka ferot pathao"}
    a = U["u1"].post("/api/assess", json={"draft": draft, "now": DAY}).json()
    assert a["level"] == "RED"
    h = start(category="scam")
    detail = MITU.get(f"/api/console/handoffs/{h['id']}").json()
    check = detail["customer"]["assessments"][0]
    assert check["id"] == a["assessment_id"] and check["can_cancel"] and check["level"] == "RED"
    url = f"/api/console/handoffs/{h['id']}/cancel-transfer"
    other = start("u2")  # another customer's chat cannot touch u1's transfer
    assert MITU.post(f"/api/console/handoffs/{other['id']}/cancel-transfer",
                     json={"assessment_id": a["assessment_id"]}).status_code == 404
    assert MITU.post(url, json={"assessment_id": a["assessment_id"]}).status_code == 200
    msgs = U["u1"].get(f"/api/handoff/{h['id']}").json()["messages"]
    assert "still in your account" in msgs[-1]["text"]
    r = U["u1"].post("/api/execute", json={"assessment_id": a["assessment_id"], "method": "pin",
                                     "pin": "1234", "acknowledged_warning": True})
    assert r.status_code == 409


def test_no_console_route_moves_money_or_touches_a_pin():
    paths = [p for p in app.openapi()["paths"] if p.startswith("/api/console")]
    assert paths and not any(w in p for p in paths for w in ("execute", "approve", "pin", "send"))
