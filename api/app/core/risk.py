"""Risk engine: ML score + hard rules + mistake guard -> GREEN / YELLOW / RED.

The model (gradient boosting, monotonic and calibrated, trained by
ml/train_risk.py on simulated wallet timelines) gives a scam probability, and
SHAP values say which features pushed it up for this payment. Logistic
regression in the same bundle is the fallback, with its own thresholds. Hard
rules override the model where the evidence is unambiguous. Every decision
carries its reasons in Bangla and English so the user and upay's ops team
can see why.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

import numpy as np

from .features import FEATURES, vector

log = logging.getLogger("bolo.risk")

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
    "sends_24h": ("গত ২৪ ঘণ্টায় আপনি অনেকবার টাকা পাঠিয়েছেন।",
                  "You have sent money many times in the last 24 hours."),
    "new_recipients_7d": ("গত ৭ দিনে আপনি কয়েকটি নতুন নম্বরে টাকা পাঠিয়েছেন।",
                          "You have paid several new numbers in the last 7 days."),
    "inflow_then_outflow": ("অচেনা নম্বর থেকে সদ্য টাকা এসেছে, আর এখন তার বড় অংশ অন্য নম্বরে যাচ্ছে।",
                            "Money just came from an unknown number and most of it is now going to another number."),
    "amount_z_user": ("এই পরিমাণ আপনার সাধারণ লেনদেনের তুলনায় অস্বাভাবিক।",
                      "This amount is unusual for you."),
    "hour_unusual_for_user": ("এই সময়ে আপনি সাধারণত টাকা পাঠান না।",
                              "You don't usually send money at this time of day."),
    "hesitation": ("টাকা পাঠানোর কথা বলার সময় আপনি অনেকবার থেমেছেন, যেন কেউ বলে দিচ্ছে।",
                   "You paused a lot while giving the command, as if someone was telling you what to say."),
    "speaker_echo": ("আপনি লাউডস্পিকারে কলে আছেন। প্রতারকেরা প্রায়ই এভাবে ধাপে ধাপে টাকা পাঠাতে বলে।",
                     "You are on a call on the loudspeaker. Scammers often talk people through a payment like this."),
    "voice_mismatch": ("কণ্ঠটি এই অ্যাকাউন্টের মালিকের সাথে মেলেনি, তাই পিন লাগবে।",
                       "The voice did not match the account owner's, so the PIN is needed."),
    "second_voice": ("কথার সময় আরেকজনের কণ্ঠ শোনা গেছে, তাই পিন লাগবে।",
                     "A second voice was heard during the command, so the PIN is needed."),
    "cash_out_night_new_agent": ("গভীর রাতে নতুন এজেন্টের কাছে ব্যালেন্সের বেশিরভাগ ক্যাশ আউট হচ্ছে।",
                                 "Most of your balance is being cashed out late at night at an agent you have never used."),
}
# yes/no features: only a reason when they are actually on
BINARY = ("is_night", "on_active_call", "is_new_recipient", "return_claim_no_inflow",
          "inflow_then_outflow", "hour_unusual_for_user", "speaker_echo", "voice_mismatch", "second_voice")
VOICE_PIN = ("voice_mismatch", "second_voice")  # GREEN -> at least YELLOW (PIN), never RED on their own
REASON_MIN = 0.35  # how much a feature must push the score (log-odds) to be named

ADVICE = {
    "RED": ("লেনদেনটি সাময়িক আটকে রাখা হয়েছে। উপায় কখনো ফোন করে পিন, ওটিপি বা টাকা চায় না। "
            "সন্দেহ হলে ফোন কেটে দিন এবং ১৬২৬৮ নম্বরে কল করুন।",
            "This transfer is on hold. upay never calls to ask for your PIN, OTP or money. "
            "If in doubt, hang up and call 16268."),
    "YELLOW": ("পাঠানোর আগে আরেকবার নিশ্চিত হোন।", "Please double-check before sending."),
    "GREEN": ("সব ঠিক আছে বলে মনে হচ্ছে।", "Everything looks normal."),
}


def _bn(n: int) -> str:
    return f"{n:,}".translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))


@lru_cache(maxsize=1)
def load_model():
    """The trained bundle, or None (then transparent rules score instead)."""
    if not MODEL_PATH.exists():
        return None
    import joblib
    try:
        m = joblib.load(MODEL_PATH)
    except Exception as e:  # unreadable file or a library version it was not saved with
        log.error("risk model could not be loaded (%s): using rule scoring", e)
        return None
    if m.get("features") != FEATURES:
        log.error("risk model was trained on other features: using rule scoring; run ml/train_risk.py")
        return None
    return m


@lru_cache(maxsize=1)
def _explainer():
    """SHAP explainer for the boosting model, or None (reasons then fall back)."""
    m = load_model()
    try:
        import shap
        return shap.TreeExplainer(m["gb"])
    except Exception as e:
        log.warning("SHAP explanations unavailable (%s)", e)
        return None


def _fallback_prob(f: dict) -> float:
    """Transparent rules used only if the trained model file is missing."""
    z = (-3.0 + 1.6 * f["is_new_recipient"] + 0.7 * max(f["log_recipient_ratio"], 0)
         + 1.2 * f["on_active_call"] + 0.8 * f["is_night"] + 3.5 * f["scam_score"]
         + 0.4 * f["recent_sends_30m"] + 1.0 * f["balance_fraction"]
         + 1.5 * f.get("hesitation", 0) + 0.8 * f.get("speaker_echo", 0)
         + 0.8 * f.get("voice_mismatch", 0) + 0.8 * f.get("second_voice", 0))
    return float(1 / (1 + np.exp(-z)))


RULE_THRESHOLDS = {"yellow": 0.3, "red": 0.7}


def score(feats: dict) -> tuple[float, list[tuple[str, float]], str]:
    """(probability, [(feature, contribution), ...] by impact, model used).

    gradient boosting with SHAP contributions; if it fails, the logistic
    fallback (coefficient x scaled value); without a model, transparent rules.
    """
    m = load_model()
    if m is None:
        return _fallback_prob(feats), [], "rules"
    x = np.array([vector(feats)])
    try:
        prob = float(m["model"].predict_proba(x)[0, 1])
        ranked: list[tuple[str, float]] = []
        ex = _explainer()
        if ex is not None:
            contrib = np.asarray(ex.shap_values(x)).reshape(-1)[: len(FEATURES)]
            ranked = sorted(zip(FEATURES, contrib.tolist()), key=lambda kv: -kv[1])
        return prob, ranked, "gradient_boosting"
    except Exception as e:
        log.error("gradient boosting failed (%s): using the logistic fallback", e)
    fb = m["fallback"]
    xs = fb["scaler"].transform(x)
    prob = float(fb["model"].predict_proba(xs)[0, 1])
    contrib = xs[0] * fb["model"].coef_[0]
    return prob, sorted(zip(FEATURES, contrib.tolist()), key=lambda kv: -kv[1]), "logistic_regression"


def thresholds(model: str = "gradient_boosting") -> dict:
    m = load_model()
    if m is None or model == "rules":
        return RULE_THRESHOLDS
    return m["fallback"]["thresholds"] if model == "logistic_regression" else m["thresholds"]


def assess(feats: dict, summary: dict, scam: dict, amount: float,
           interviewed: bool) -> dict:
    prob, ranked, model = score(feats)
    th = thresholds(model)
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
    # cashing out most of the balance at night at an agent never used before
    if (feats.get("is_cash_out") and feats["is_night"] and feats["is_new_recipient"]
            and feats["balance_fraction"] >= 0.5):
        rules.append("cash_out_night_new_agent")
    if rules:
        level = "RED"

    # mistake guard: known recipient, amount ~10x what they usually get
    mistake = None
    rec_med = summary.get("recipient_median")
    if rec_med and amount >= 5 * rec_med:
        suggestion = amount / 10
        if 0.4 * rec_med <= suggestion <= 2.5 * rec_med:
            mistake = {"usual": int(rec_med), "suggested": int(suggestion),
                       "bn": f"আপনি সাধারণত এই ব্যক্তিকে প্রায় ৳{_bn(int(rec_med))} পাঠান। "
                             f"আপনি কি ৳{_bn(int(suggestion))} বোঝাতে চেয়েছেন?",
                       "en": f"You usually send this person about ৳{int(rec_med):,}. "
                             f"Did you mean ৳{int(suggestion):,}?"}
            if level == "GREEN":
                level = "YELLOW"

    # voice guard: a different or second voice is worth a PIN, never a hold; a matching
    # voice lowers nothing (voices can be cloned), so only a warning sign is acted on
    voice_pin = [k for k in VOICE_PIN if feats.get(k)]
    if voice_pin and level == "GREEN":
        level = "YELLOW"

    reasons = []
    for r in voice_pin:
        bn, en = REASONS[r]
        reasons.append({"key": r, "bn": bn, "en": en, "hard": True})
    for r in rules:
        if r in ("return_claim_no_inflow", "cash_out_night_new_agent"):
            bn, en = REASONS[r]
            reasons.append({"key": r, "bn": bn, "en": en, "hard": True})
    for h in scam["hits"]:
        reasons.append({"key": f"scam:{h['category']}", "bn": h["explain_bn"],
                        "en": h["explain_en"], "phrase": h["phrase"], "hard": h["level"] == "high"})
    for feat, c in ranked:
        if c > REASON_MIN and feat in REASONS and feat not in ("scam_score", "return_claim_no_inflow"):
            if feat in BINARY and not feats[feat]:
                continue
            bn, en = REASONS[feat]
            reasons.append({"key": feat, "bn": bn, "en": en, "weight": round(c, 2)})
    if not ranked:  # no per-feature contributions: list the active yes/no signals
        for feat in ("is_new_recipient", "on_active_call", "is_night", "inflow_then_outflow",
                     "hour_unusual_for_user", "speaker_echo"):
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
        "model": model,
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
    fb = m["fallback"]
    return {"model": m["name"], "features": FEATURES, "thresholds": m["thresholds"],
            "explanations": "shap" if _explainer() is not None else "none",
            "fallback": {"model": "logistic_regression", "thresholds": fb["thresholds"],
                         "coefficients": dict(zip(FEATURES, [round(c, 3) for c in fb["model"].coef_[0].tolist()]))},
            "trained_at": m.get("trained_at")}


def metrics() -> dict:
    p = MODEL_PATH.parent / "metrics.json"
    return json.loads(p.read_text()) if p.exists() else {}
