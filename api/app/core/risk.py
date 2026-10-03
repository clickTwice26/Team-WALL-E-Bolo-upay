"""Risk engine: ML score + hard rules + mistake guard -> GREEN / YELLOW / RED.

The model (logistic regression, trained by ml/train_risk.py on synthetic
labelled scenarios) gives a scam probability. Hard rules override it for
cases where the evidence is unambiguous. Every decision carries its reasons
in Bangla and English so the user and upay's ops team can see why.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from .features import FEATURES, vector

MODEL_PATH = Path(__file__).resolve().parents[3] / "model" / "risk_model.joblib"

REASONS = {
    "is_new_recipient": ("এই নম্বরে আপনি আগে কখনো টাকা পাঠাননি।",
                         "You have never sent money to this number."),
    "log_recipient_ratio": ("এই পরিমাণ আপনার সাধারণ লেনদেনের চেয়ে অনেক বেশি।",
                            "This amount is much higher than you usually send."),
    "is_night": ("গভীর রাতে লেনদেন হচ্ছে।", "This is happening late at night."),
    "recent_sends_30m": ("গত ৩০ মিনিটে আপনি কয়েকবার টাকা পাঠিয়েছেন।",
                         "You have sent money several times in the last 30 minutes."),
    "balance_fraction": ("আপনার ব্যালেন্সের বড় অংশ পাঠানো হচ্ছে।",
                         "A large share of your balance is being sent."),
    "on_active_call": ("আপনি এখন একটি ফোন কলে আছেন।", "You are on a phone call right now."),
    "return_claim_no_inflow": ("এই নম্বর থেকে আপনার অ্যাকাউন্টে কোনো টাকা আসেনি।",
                               "No money was received from this number."),
    "scam_score": ("আপনার কথায় প্রতারণার সাধারণ লক্ষণ পাওয়া গেছে।",
                   "What you said matches common scam patterns."),
}

ADVICE = {
    "RED": ("লেনদেনটি সাময়িক আটকে রাখা হয়েছে। উপায় কখনো ফোন করে পিন, ওটিপি বা টাকা চায় না। "
            "সন্দেহ হলে ফোন কেটে দিন এবং ১৬২৬৮ নম্বরে কল করুন।",
            "This transfer is on hold. upay never calls to ask for your PIN, OTP or money. "
            "If in doubt, hang up and call 16268."),
    "YELLOW": ("পাঠানোর আগে আরেকবার নিশ্চিত হোন।", "Please double-check before sending."),
    "GREEN": ("সব ঠিক আছে বলে মনে হচ্ছে।", "Everything looks normal."),
}


@lru_cache(maxsize=1)
def load_model():
    if not MODEL_PATH.exists():
        return None
    import joblib
    return joblib.load(MODEL_PATH)


def _fallback_prob(f: dict) -> float:
    """Transparent rules used only if the trained model file is missing."""
    z = (-3.0 + 1.6 * f["is_new_recipient"] + 0.7 * max(f["log_recipient_ratio"], 0)
         + 1.2 * f["on_active_call"] + 0.8 * f["is_night"] + 3.5 * f["scam_score"]
         + 0.4 * f["recent_sends_30m"] + 1.0 * f["balance_fraction"])
    return float(1 / (1 + np.exp(-z)))


def score(feats: dict) -> tuple[float, list[tuple[str, float]]]:
    """Return (probability, [(feature, contribution), ...]) sorted by impact."""
    m = load_model()
    if m is None:
        return _fallback_prob(feats), []
    x = np.array([vector(feats)])
    xs = m["scaler"].transform(x)
    prob = float(m["model"].predict_proba(xs)[0, 1])
    contrib = xs[0] * m["model"].coef_[0]
    ranked = sorted(zip(FEATURES, contrib.tolist()), key=lambda kv: -kv[1])
    return prob, ranked


def thresholds() -> dict:
    m = load_model()
    return m["thresholds"] if m else {"yellow": 0.3, "red": 0.7}


def assess(feats: dict, summary: dict, scam: dict, amount: float,
           interviewed: bool) -> dict:
    prob, ranked = score(feats)
    th = thresholds()
    level = "RED" if prob >= th["red"] else "YELLOW" if prob >= th["yellow"] else "GREEN"
    rules: list[str] = []

    # hard rules: unambiguous evidence overrides the model
    # "sent by mistake, send it back" is judged on evidence (did money actually
    # arrive from that number?), not on the words: an honest refund says them too
    high_hits = [h for h in scam["hits"] if h["level"] == "high"
                 and h["category"] != "sent_by_mistake"]
    if high_hits:
        rules.append("scam_phrase_high")
    if feats["return_claim_no_inflow"]:
        rules.append("return_claim_no_inflow")
    if any(h.get("escalate_if") == "new_recipient" for h in scam["hits"]) and feats["is_new_recipient"]:
        rules.append("relative_in_trouble_new_number")
    if rules:
        level = "RED"

    # mistake guard: known recipient, amount ~10x what they usually get
    mistake = None
    rec_med = summary.get("recipient_median")
    if rec_med and amount >= 5 * rec_med:
        suggestion = amount / 10
        if 0.4 * rec_med <= suggestion <= 2.5 * rec_med:
            mistake = {"usual": int(rec_med), "suggested": int(suggestion),
                       "bn": f"আপনি সাধারণত এই ব্যক্তিকে প্রায় ৳{int(rec_med):,} পাঠান। "
                             f"আপনি কি ৳{int(suggestion):,} বোঝাতে চেয়েছেন?",
                       "en": f"You usually send this person about ৳{int(rec_med):,}. "
                             f"Did you mean ৳{int(suggestion):,}?"}
            if level == "GREEN":
                level = "YELLOW"

    reasons = []
    for r in rules:
        if r == "return_claim_no_inflow":
            bn, en = REASONS["return_claim_no_inflow"]
            reasons.append({"key": r, "bn": bn, "en": en, "hard": True})
    for h in scam["hits"]:
        reasons.append({"key": f"scam:{h['category']}", "bn": h["explain_bn"],
                        "en": h["explain_en"], "phrase": h["phrase"], "hard": h["level"] == "high"})
    for feat, c in ranked:
        if c > 0.35 and feat in REASONS and feat not in ("scam_score", "return_claim_no_inflow"):
            if feat in ("is_night", "on_active_call", "is_new_recipient", "return_claim_no_inflow") and not feats[feat]:
                continue
            bn, en = REASONS[feat]
            reasons.append({"key": feat, "bn": bn, "en": en, "weight": round(c, 2)})
    if not ranked:  # fallback model: list the active binary signals
        for feat in ("is_new_recipient", "on_active_call", "is_night"):
            if feats[feat]:
                bn, en = REASONS[feat]
                reasons.append({"key": feat, "bn": bn, "en": en})
    if mistake:
        reasons.append({"key": "mistake_amount", "bn": mistake["bn"], "en": mistake["en"]})
    seen, unique = set(), []
    for r in reasons:
        if r["en"] not in seen:
            seen.add(r["en"])
            unique.append(r)
    reasons = unique

    # interview when the model is unsure; skip it when a hard rule already
    # decided (RED is final) or when the only issue is a likely typo
    needs_interview = (level in ("YELLOW", "RED") and not interviewed and not rules
                       and not (mistake and prob < th["yellow"]))
    adv_bn, adv_en = ADVICE[level]
    return {
        "level": level,
        "probability": round(prob, 4),
        "thresholds": th,
        "hard_rules": rules,
        "reasons": reasons[:6],
        "mistake": mistake,
        "needs_interview": needs_interview,
        "advice_bn": adv_bn,
        "advice_en": adv_en,
        "auth_required": {"GREEN": "biometric_or_pin", "YELLOW": "pin",
                          "RED": "hold_then_pin"}[level],
    }


def model_card() -> dict:
    m = load_model()
    if not m:
        return {"model": "fallback-rules"}
    return {"model": "logistic_regression", "features": FEATURES,
            "thresholds": m["thresholds"],
            "coefficients": dict(zip(FEATURES, [round(c, 3) for c in m["model"].coef_[0].tolist()])),
            "trained_at": m.get("trained_at")}


def metrics() -> dict:
    p = MODEL_PATH.parent / "metrics.json"
    return json.loads(p.read_text()) if p.exists() else {}
