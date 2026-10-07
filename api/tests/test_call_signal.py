"""R11: where the "on a call" signal came from (the phone itself or the demo toggle)."""
import json
import logging
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ["HOLD_SECONDS"] = "0"
os.environ.pop("LLM_PROVIDER", None)

import pytest  # noqa: E402

from app import store  # noqa: E402
from app.main import app  # noqa: E402
from helpers import signed_in  # noqa: E402

DAY = "2026-10-03T14:00:00+06:00"


@pytest.fixture
def u1():
    store.reset()
    yield signed_in(app, "u1")
    store.reset()


class Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.events = []

    def emit(self, record):
        self.events.append(json.loads(record.getMessage()))


def assess(c, text, **kw):
    p = c.post("/api/parse", json={"text": text}).json()
    phone = (p["recipient"] or {}).get("phone") or p["new_number"]
    d = {"intent": p["intent"], "amount": p["amount"], "recipient_phone": phone,
         "is_return_claim": p["is_return_claim"], "command_text": text}
    return c.post("/api/assess", json={"draft": d, "now": DAY, **kw})


def test_call_signal_source_is_stored_logged_and_kept_with_the_decision(u1):
    lines = Lines()
    logging.getLogger("bolo.access").addHandler(lines)
    try:
        a = assess(u1, "01799998888 e 5000 taka pathao", on_active_call=True, call_signal_source="native").json()
    finally:
        logging.getLogger("bolo.access").removeHandler(lines)
    saved = store.get_assessment(a["assessment_id"])
    assert saved["draft"]["call_signal_source"] == "native" and saved["draft"]["on_active_call"] is True
    ev = [e for e in lines.events if e.get("event") == "assess"]
    assert ev == [{"event": "assess", "assessment_id": a["assessment_id"], "level": a["level"],
                   "on_call": True, "call_signal_source": "native"}]
    assert "01799998888" not in json.dumps(ev)  # flags only, never the number
    u1.post("/api/cancel", json={"assessment_id": a["assessment_id"]})
    assert store.decisions(1)[0]["call_signal_source"] == "native"


def test_call_signal_source_defaults_to_simulated_and_is_checked(u1):
    a = assess(u1, "Ammu ke 2000 taka pathao").json()  # an older app that does not send it
    assert store.get_assessment(a["assessment_id"])["draft"]["call_signal_source"] == "simulated"
    assert assess(u1, "Ammu ke 2000 taka pathao", call_signal_source="guess").status_code == 422


def test_an_older_database_gets_the_new_column(tmp_path):
    import sqlite3
    old = sqlite3.connect(tmp_path / "old.db")
    old.execute("CREATE TABLE decisions (id TEXT PRIMARY KEY, ts TEXT NOT NULL)")
    store._migrate(old)
    assert "call_signal_source" in {r[1] for r in old.execute("PRAGMA table_info(decisions)")}
    store._migrate(old)  # runs on every start: a second time is a no-op
