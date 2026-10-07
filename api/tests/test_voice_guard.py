"""R10 voice guard: scores and yes/no from the phone, which can only raise the risk."""
import json
import logging
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ["HOLD_SECONDS"] = "0"
os.environ.pop("LLM_PROVIDER", None)

import pytest  # noqa: E402

from app import store  # noqa: E402
from app.core import features, risk  # noqa: E402
from app.core.features import FEATURES, VOICE_FEATURES  # noqa: E402
from app.main import app  # noqa: E402
from helpers import signed_in  # noqa: E402

DAY = "2026-10-03T14:00:00+06:00"
FAMILY = "Ammu ke 2000 taka pathao"  # GREEN for u1


@pytest.fixture
def u1():
    store.reset()
    yield signed_in(app, "u1")
    store.reset()


def assess(c, text, **kw):
    p = c.post("/api/parse", json={"text": text}).json()
    phone = (p["recipient"] or {}).get("phone") or p["new_number"]
    d = {"intent": p["intent"], "amount": p["amount"], "recipient_phone": phone,
         "is_return_claim": p["is_return_claim"], "command_text": text}
    return c.post("/api/assess", json={"draft": d, "now": DAY, **kw})


def test_voice_features_are_model_inputs_and_not_measured_is_zero(u1):
    assert FEATURES[-len(VOICE_FEATURES):] == VOICE_FEATURES
    assert risk.load_model() is not None  # the model was retrained on these features
    a = assess(u1, FAMILY).json()
    assert {f: a["features"][f] for f in VOICE_FEATURES} == dict.fromkeys(VOICE_FEATURES, 0)
    b = assess(u1, FAMILY, voice_signals={"hesitation": None, "speaker_echo": None}).json()
    assert {f: b["features"][f] for f in VOICE_FEATURES} == dict.fromkeys(VOICE_FEATURES, 0)
    c = assess(u1, FAMILY, voice_signals={"hesitation": 0.42, "speaker_echo": True}).json()
    assert c["features"]["hesitation"] == 0.42 and c["features"]["speaker_echo"] == 1


def test_bad_voice_signals_are_refused(u1):
    assert assess(u1, FAMILY, voice_signals={"hesitation": 1.5}).status_code == 422
    assert assess(u1, FAMILY, voice_signals={"voice_mismatch": "maybe"}).status_code == 422


@pytest.mark.parametrize("flag", ["voice_mismatch", "second_voice"])
def test_mismatch_or_second_voice_moves_green_to_yellow_and_needs_the_pin(u1, flag):
    assert assess(u1, FAMILY).json()["level"] == "GREEN"
    a = assess(u1, FAMILY, voice_signals={flag: True}).json()
    assert a["level"] == "YELLOW" and a["auth_required"] == "pin"
    assert any(r["key"] == flag and r["bn"] and r["en"] for r in a["reasons"])
    r = u1.post("/api/execute", json={"assessment_id": a["assessment_id"], "method": "biometric"})
    assert r.status_code == 403  # a fingerprint is not enough any more
    # still YELLOW after a clean interview: the PIN is required either way
    b = assess(u1, FAMILY, voice_signals={flag: True}, answers=["ami nijei pathacchi"]).json()
    assert b["level"] == "YELLOW"


def test_a_matching_voice_never_lowers_anything(u1):
    for text in (FAMILY, "01799998888 e 5000 taka pathao"):
        base = assess(u1, text, on_active_call=True).json()
        match = assess(u1, text, on_active_call=True,
                       voice_signals={"voice_mismatch": False, "second_voice": False}).json()
        assert (match["level"], match["probability"]) == (base["level"], base["probability"])


def test_voice_signals_can_only_raise_the_score():
    seed = json.loads((risk.MODEL_PATH.parents[1] / "data" / "seed.json").read_text(encoding="utf-8"))
    u = seed["users"][0]
    hist = [t for t in seed["transactions"] if t["user_id"] == u["id"]]
    for amount, phone in ((2000, u["contacts"][0]["phone"]), (6000, "01799998888")):
        def prob(voice):
            f, _ = features.compute(amount, "send_money", phone, False, u["balance"], hist, u["contacts"],
                                    False, 0.0, self_phone=u["phone"], voice=voice)
            return risk.score(f)[0]
        base = prob(None)
        for v in ({"hesitation": 0.5}, {"speaker_echo": True}, {"voice_mismatch": True},
                  {"second_voice": True}, {"hesitation": 0.6, "speaker_echo": True, "second_voice": True}):
            assert prob(v) >= base - 1e-9, v


def test_voice_signals_are_stored_and_logged_without_audio(u1):
    lines = []

    class H(logging.Handler):
        def emit(self, record):
            lines.append(json.loads(record.getMessage()))
    h = H()
    logging.getLogger("bolo.access").addHandler(h)
    try:
        a = assess(u1, FAMILY, voice_signals={"hesitation": 0.31, "speaker_echo": False}).json()
    finally:
        logging.getLogger("bolo.access").removeHandler(h)
    ev = [e for e in lines if e.get("event") == "assess"][0]
    assert ev["voice"] == {"hesitation": 0.31, "speaker_echo": False}  # only what was measured
    assert store.get_assessment(a["assessment_id"])["draft"]["voice_signals"] == ev["voice"]
