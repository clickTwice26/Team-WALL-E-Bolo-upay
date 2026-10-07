"""Real-audio evaluation (R1): the study script endpoint and ml/evaluate_audio.py."""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.pop("LLM_PROVIDER", None)

from app.main import app  # noqa: E402
from helpers import signed_in  # noqa: E402

pytest.importorskip("jiwer")  # ml/requirements.txt (CI installs it)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
import evaluate_audio as ea  # noqa: E402

SAMPLE = ROOT / "data" / "eval_sample" / "audio_log_SAMPLE.json"


def test_prompts_cover_every_test_command_in_bangla_script_plus_free_tasks():
    r = signed_in(app, "u1").get("/api/eval/prompts")
    assert r.status_code == 200
    ps = r.json()["prompts"]
    read = [p for p in ps if p["kind"] == "read"]
    n_cmds = len(json.loads((ROOT / "data" / "test_commands.json").read_text(encoding="utf-8"))["commands"]) if isinstance(json.loads((ROOT / "data" / "test_commands.json").read_text(encoding="utf-8")), dict) else len(json.loads((ROOT / "data" / "test_commands.json").read_text(encoding="utf-8")))
    assert len(read) == n_cmds and len([p for p in ps if p["kind"] == "free"]) == 10
    assert len({p["id"] for p in ps}) == len(ps)
    # bn-BD speech recognition writes Bangla script, so every reference must be in it
    # (bill-payment commands added later still need a Bangla reading in audio_eval_prompts.json)
    spoken = json.loads((ROOT / "data" / "audio_eval_prompts.json").read_text(encoding="utf-8"))["spoken_bn"]
    assert all(re.search("[ঀ-৿]", p["text"]) for p in read if p["id"][1:] in spoken or p["text"] == p["typed"] and re.search("[ঀ-৿]", p["typed"]))
    assert all(p["expected"]["intent"] for p in ps)


def test_prompts_need_a_session_and_a_demo_site(monkeypatch):
    from fastapi.testclient import TestClient
    assert TestClient(app).get("/api/eval/prompts").status_code == 401
    c = signed_in(app, "u1")
    monkeypatch.setenv("DEMO_MODE", "false")
    assert c.get("/api/eval/prompts").status_code == 404


def _row(**kw):
    base = {"participant": "P1", "condition": "quiet", "prompt_id": "C1", "reference": "আম্মুকে ৫০০ টাকা পাঠাও",
            "transcript": "আম্মুকে ৫০০ টাকা পাঠাও", "expected": {"intent": "send_money", "amount": 500, "recipient": "c1"},
            "parse": {"status": "ok", "intent": "send_money", "amount": 500, "recipient": "c1"}, "unsure": False}
    return {**base, **kw}


def test_silent_wrong_amount_unless_the_app_asked_or_stt_was_unsure():
    wrong = {"status": "ok", "intent": "send_money", "amount": 50, "recipient": "c1"}
    assert ea.judge(_row(parse=wrong))["silent_wrong_amount"] is True
    assert ea.judge(_row(parse=wrong, unsure=True))["silent_wrong_amount"] is False  # user must check the words
    asked = {"status": "clarify_amount", "intent": "send_money", "amount": None, "recipient": "c1"}
    j = ea.judge(_row(parse=asked))
    assert not j["silent_wrong_amount"] and j["asked"] and not j["amount_ok"]
    # it had to ask ("500, na 1000") but picked one: that is silent too
    must_ask = _row(expected={"intent": "send_money", "amount": None, "recipient": "c4"},
                    parse={"status": "ok", "intent": "send_money", "amount": 1000, "recipient": "c4"})
    assert ea.judge(must_ask)["silent_wrong_amount"] is True


def test_recipient_rules_ask_and_spoken_fuzzy_names():
    ask = {"intent": "send_money", "amount": 500, "recipient": "ask"}
    j = ea.judge(_row(expected=ask, parse={"status": "clarify_recipient", "intent": "send_money", "amount": 500, "recipient": None}))
    assert j["recipient_ok"] and not j["silent_wrong_recipient"]
    j = ea.judge(_row(expected=ask, parse={"status": "ok", "intent": "send_money", "amount": 500, "recipient": "c3"}))
    assert not j["recipient_ok"] and j["silent_wrong_recipient"]
    # "rohim bhai" typed is fuzzy, but spoken it may come back as the exact name
    j = ea.judge(_row(expected={"intent": "send_money", "amount": 500, "recipient": "c2?"},
                      parse={"status": "ok", "intent": "send_money", "amount": 500, "recipient": "c2"}))
    assert j["recipient_ok"] and not j["silent_wrong_recipient"]


def test_normalize_compares_words_not_digit_scripts_or_commas():
    assert ea.normalize("আম্মুকে ১,৫০০ টাকা।") == ea.normalize("আম্মুকে 1500 টাকা")


def test_last_attempt_counts_and_typed_rows_are_left_out(tmp_path):
    rec = _row()
    log = {"sessions": [{"participant": "P1", "condition": "quiet", "records": [
        {**rec, "attempt": 1, "transcript": "ভুল পড়া"}, {**rec, "attempt": 2},
        {**rec, "prompt_id": "C2", "input": "typed"}, {**rec, "prompt_id": "C3", "skipped": True}]}]}
    p = tmp_path / "log.json"
    p.write_text(json.dumps(log, ensure_ascii=False))
    rows, sample = ea.load([p])
    assert len(rows) == 1 and rows[0]["transcript"] == rec["transcript"] and not sample
    m = ea.main([p], tmp_path / "out.json")
    assert m["overall"]["wer"] == 0 and m["overall"]["silent_wrong_amount_rate"] == 0 and m["target"]["met"]


def test_sample_log_runs_end_to_end_and_stays_labelled_a_sample(tmp_path):
    out = tmp_path / "audio_metrics.json"
    m = ea.main([SAMPLE], out)
    assert m["sample"] is True and "not real" in m["note"].lower()
    assert json.loads(out.read_text())["overall"]["utterances"] == m["overall"]["utterances"] > 100
    assert set(m["by_condition"]) == {"quiet", "street", "bus_tv"} and len(m["by_dialect"]) >= 4
    assert m["design"]["meets_design"] is False  # 4 made-up speakers, not 12
    o = m["overall"]
    assert 0 <= o["wer"] <= 1 and 0 <= o["silent_wrong_amount_rate"] <= o["wrong_amount_rate"] <= 1
    assert m["by_condition"]["quiet"]["wer"] < m["by_condition"]["bus_tv"]["wer"]


def test_reparse_runs_the_current_rule_parser_on_logged_transcripts(tmp_path):
    rows, _ = ea.load([SAMPLE])
    ea.reparse(rows)
    assert all(r["parse"]["llm_used"] is False and r["parse"]["status"] for r in rows)
