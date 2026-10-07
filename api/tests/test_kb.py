import json
import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.pop("LLM_PROVIDER", None)

from app.core import kb, llm  # noqa: E402
from app.main import app  # noqa: E402
from helpers import signed_in  # noqa: E402

c = signed_in(app, "u1")
HOME = {"id": "home", "summary_bn": "হোম", "summary_en": "Home", "actions": []}


def ask(message, **kw):
    r = c.post("/api/agent", json={"message": message, "page": HOME, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def urls(hits):
    return [h["url"] for h in hits]


# ---------- the knowledge base itself ----------
def test_kb_is_built_and_cited():
    info = kb.info()
    assert info["chunks"] > 300 and info["crawled_at"]
    for r in kb.index().records:
        assert r["url"].startswith("https://www.upaybd.com") and r["text"].strip()


def test_retrieval_in_bangla_banglish_and_english():
    assert "pin-reset" in urls(kb.search("how do I reset my PIN", 1))[0]
    assert "upay-account-creation" in urls(kb.search("upay account kivabe khulbo", 1))[0]
    assert "limits-and-charges" in urls(kb.search("send money limit koto", 1))[0]
    assert "limits-and-charges" in urls(kb.search("cash out er charge koto", 1))[0]
    assert any("16268" in h["text"] for h in kb.search("হেল্পলাইন নম্বর কত", 2))


def test_question_detector():
    for q in ("ক্যাশ আউট চার্জ কত?", "send money limit", "pin vule gele ki korbo", "DPS ki"):
        assert kb.is_info_question(q), q
    for q in ("ammu ke 500 pathao", "ড্যাশবোর্ড খোলো", "abar pathao"):
        assert not kb.is_info_question(q), q


def test_extractive_answer_quotes_the_charge_table():
    a = kb.answer("cash out er charge koto")
    assert "Cash Out from Agent" in a["en"] and "1.40%" in a["en"]
    assert a["source"]["url"].endswith("/limits-and-charges")


def test_search_endpoint():
    r = c.get("/api/kb/search", params={"q": "PIN reset"})
    assert r.status_code == 200
    body = r.json()
    assert body["hits"] and body["chunks"] > 300 and "pin" in body["hits"][0]["text"].lower()
    assert c.get("/api/kb/search", params={"q": " "}).status_code == 422


# ---------- the agent, without an LLM ----------
def test_agent_answers_upay_questions_with_a_source():
    res = ask("how do I reset my PIN")
    assert res["actions"] == [] and "*268#" in res["reply_en"]
    assert res["sources"][0]["url"].endswith("/services/details/pin-reset")
    res = ask("হেল্পলাইন নম্বর কত")
    assert "১৬২৬৮" in res["reply_bn"] and res["sources"]


def test_questions_do_not_hijack_commands():
    assert [a["type"] for a in ask("ammu ke 500 taka pathao")["actions"]] == ["start_transfer"]
    assert [a["type"] for a in ask("cash out 500")["actions"]] == ["start_transfer"]
    assert [a["type"] for a in ask("send money e jao")["actions"]] == ["navigate"]
    assert "sources" not in ask("ki korte paro")
    # a PIN is still caught before anything else
    assert ask("pin reset korbo, amar pin 4831")["source"] == "guard"


# ---------- the agent with an LLM: passages in, only real refs out ----------
def test_llm_gets_passages_and_cites_only_given_refs(monkeypatch):
    seen = {}

    def fake(system, user, schema):
        seen["input"] = json.loads(user)
        return schema.model_validate({"reply_bn": "১.৪০%", "reply_en": "1.40%", "actions": [],
                                      "done": True, "sources": [0, 99]})

    monkeypatch.setattr(llm, "enabled", lambda: True)
    monkeypatch.setattr(llm, "structured", fake)
    res = ask("cash out er charge koto")
    passages = seen["input"]["upay_knowledge"]
    assert passages and all({"ref", "url", "text"} <= set(p) for p in passages)
    assert "upay_knowledge" in seen["input"] and res["source"] == "llm"
    assert [s["url"] for s in res["sources"]] == [passages[0]["url"]]  # ref 99 dropped


def test_llm_gets_no_passages_on_observation_turns(monkeypatch):
    seen = {}

    def fake(system, user, schema):
        seen["input"] = json.loads(user)
        return schema.model_validate({"reply_bn": "", "reply_en": "", "actions": [], "done": True})

    monkeypatch.setattr(llm, "enabled", lambda: True)
    monkeypatch.setattr(llm, "structured", fake)
    res = ask("", observation=True)
    assert seen["input"]["upay_knowledge"] == [] and "sources" not in res
