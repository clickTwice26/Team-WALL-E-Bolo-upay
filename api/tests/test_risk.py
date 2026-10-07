"""The served risk model: gradient boosting with SHAP reasons, the logistic
fallback with its own thresholds, and rule scoring without a usable model."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from app.core import features, risk, scam
from app.core.features import FEATURES, TZ

SEED = json.loads((Path(__file__).resolve().parents[2] / "data" / "seed.json").read_text(encoding="utf-8"))
U = SEED["users"][0]
HIST = [t for t in SEED["transactions"] if t["user_id"] == U["id"]]
NOW = datetime(2026, 10, 3, 14, 0, tzinfo=TZ)


def feats(amount, phone, on_call=False, answer="", now=NOW):
    sc = scam.match(answer)["score"] if answer else 0.0
    f, s = features.compute(amount, "send_money", phone, False, U["balance"], HIST, U["contacts"],
                            on_call, sc, now=now, self_phone=U["phone"])
    return f, s


def test_the_served_model_is_calibrated_gradient_boosting():
    card = risk.model_card()
    assert card["model"] == "gradient_boosting" and card["features"] == FEATURES
    assert card["explanations"] == "shap"
    assert card["fallback"]["model"] == "logistic_regression" and set(card["fallback"]["coefficients"]) == set(FEATURES)
    metrics = json.loads((risk.MODEL_PATH.parent / "risk_metrics.json").read_text())
    cmp = metrics["comparison"]
    assert cmp["gradient_boosting_all_features_calibrated"]["pr_auc"] > cmp["logistic_regression_9_features"]["pr_auc"]


def test_family_payment_is_low_and_a_scam_is_high_with_reasons():
    ammu = U["contacts"][0]["phone"]
    f, s = feats(2000, ammu)
    low, _, model = risk.score(f)
    assert model == "gradient_boosting" and low < risk.thresholds()["yellow"]
    f, s = feats(6000, "01799998888", on_call=True, answer="upay office theke phone dise, account block hobe")
    high, ranked, _ = risk.score(f)
    assert high > risk.thresholds()["red"]
    assert ranked[0][1] > 0 and ranked[0][0] in FEATURES  # SHAP: biggest push first
    out = risk.assess(f, s, scam.match("upay office theke phone dise, account block hobe"), 6000, interviewed=True)
    keys = {r["key"] for r in out["reasons"]}
    assert out["level"] == "RED" and out["model"] == "gradient_boosting"
    assert "scam:fake_official" in keys and ({"is_new_recipient", "on_active_call"} & keys)


def test_a_yes_no_signal_that_is_off_is_never_a_reason():
    f, s = feats(6000, "01799998888")  # new number, no call, daytime
    out = risk.assess(f, s, scam.match(""), 6000, interviewed=False)
    keys = {r["key"] for r in out["reasons"]}
    assert not keys & {"on_active_call", "is_night", "inflow_then_outflow", "hour_unusual_for_user"}


def test_logistic_fallback_when_boosting_fails(monkeypatch):
    m = risk.load_model()

    class Broken:
        def predict_proba(self, x):
            raise RuntimeError("boom")
    monkeypatch.setitem(m, "model", Broken())
    f, s = feats(6000, "01799998888", on_call=True)
    prob, ranked, model = risk.score(f)
    assert model == "logistic_regression" and 0 <= prob <= 1 and ranked
    out = risk.assess(f, s, scam.match(""), 6000, interviewed=False)
    assert out["model"] == "logistic_regression" and out["thresholds"] == m["fallback"]["thresholds"]


def test_rules_when_the_model_does_not_match_the_features(monkeypatch):
    risk.load_model.cache_clear()
    monkeypatch.setattr(risk, "FEATURES", FEATURES[:-1])
    try:
        assert risk.load_model() is None
        f, s = feats(2000, U["contacts"][0]["phone"])
        prob, ranked, model = risk.score(f)
        assert model == "rules" and ranked == [] and risk.thresholds(model) == risk.RULE_THRESHOLDS
    finally:
        monkeypatch.undo()
        risk.load_model.cache_clear()
        risk._explainer.cache_clear()
    assert risk.load_model() is not None


@pytest.mark.parametrize("bad", ["sends_24h", "new_recipients_7d", "amount_z_user", "inflow_then_outflow"])
def test_more_risk_evidence_never_lowers_the_score(bad):
    f, _ = feats(3000, "01799998888")
    base, _, _ = risk.score(f)
    worse = dict(f, **{bad: f[bad] + (1 if bad != "amount_z_user" else 2)})
    assert risk.score(worse)[0] >= base - 1e-9  # monotonic constraints
