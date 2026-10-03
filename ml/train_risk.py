"""Train and evaluate the scam-risk model on synthetic labelled scenarios.

Scenarios are simulated (no real data exists for a hackathon), but the
scam_score feature is produced by running the real scam phrase matcher on
simulated interview answers, so that part of the pipeline is tested end to end.

The evaluation is two-stage, like the app:
  stage 1: command only (no interview answers yet)
  stage 2: if stage 1 is YELLOW/RED, the user answers the interview questions
Split: 70% train / 15% validation (threshold tuning) / 15% test (reported).

Run:  python ml/train_risk.py
Writes model/risk_model.joblib and model/risk_metrics.json
"""
from __future__ import annotations

import json
import math
import random
import sys
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from app.core import scam  # noqa: E402
from app.core.features import FEATURES, vector  # noqa: E402

RNG = random.Random(7)
N = 8000

LEGIT_ANSWERS = [
    "na, keu phone kore nai", "ami nijei pathacchi", "ammu chaise tai pathacchi",
    "bari bhara dicchi", "dokaner baki shodh korchi", "না, কেউ ফোন করেনি",
    "আমি নিজেই পাঠাচ্ছি", "বাসা ভাড়া দিচ্ছি", "ammu phone kore bolse bazar er taka lagbe",
    "bhai phone dise, boi kinbe", "keu otp chay nai", "কেউ পিন চায়নি",
    "taratari pathate hobe, bazar korbo", "new landlord ke advance dicchi",
    "notun dokaner malik ke dam dicchi", "friend er birthday gift", "mess er taka",
]
SCAM_ANSWERS = {
    "fake_official": ["upay office theke phone dise, bolse account block hobe",
                      "উপায় অফিস থেকে বলছে অ্যাকাউন্ট বন্ধ হয়ে যাবে",
                      "customer care theke bolse kyc update korte hobe",
                      "bolse account verify korte hobe, na hole lock"],
    "pin_otp": ["otp ta chaise", "ওটিপি কোড চেয়েছে", "pin number din bolse",
                "message e je code gese ta bolte bolse"],
    "lottery": ["bolse lottery jitechen, age processing fee", "পুরস্কার পেয়েছেন বলেছে, আগে টাকা দিতে হবে",
                "cashback pete age taka pathan bolse"],
    "sent_by_mistake": ["bolse vul kore taka pathiyeche, ferot din", "ভুল করে টাকা চলে গেছে বলছে, ফেরত দিন",
                        "takata ferot pathan bolse"],
    "allowance": ["sorkari vata pabo, processing fee lagbe", "উপবৃত্তির টাকা পেতে প্রসেসিং ফি"],
    "relative": ["bhai bolse accident hoyeche, notun number theke bolchi", "বিপদে পড়েছি, নতুন নম্বর থেকে বলছি",
                 "police e dhoreche bolse, ekhoni pathan"],
    "job_loan": ["chakrir jonno registration fee", "loan pete age taka din bolse", "double taka hobe bolse"],
}
DEFLECT = ["na emni", "ami nijei", "kichu na", "জানি না", "no, nothing", "family r jonno"]


def lognorm(mu: float, sigma: float) -> float:
    return math.log2(math.exp(RNG.gauss(mu, sigma)))


def scenario(label: int) -> tuple[dict, dict, str]:
    """Return (stage-2 features, meta, answer text)."""
    recharge = RNG.random() < (0.15 if not label else 0.08)
    if not label:
        new = 1 if RNG.random() < 0.18 else 0
        ratio = lognorm(0.25 if new else 0.0, 0.85 if new else 0.6)
        rec_ratio = ratio if new else lognorm(0.0, 0.35)
        night = RNG.random() < (0.04 if new else 0.03)
        call = RNG.random() < (0.25 if new else 0.15)
        recent = min(np.random.poisson(0.2), 5)
        bal_frac = min(2 ** ratio * RNG.uniform(0.03, 0.25), 1.5)
        no_inflow = 1 if (RNG.random() < 0.01) else 0
        answer = RNG.choice(LEGIT_ANSWERS)
        cat = "legit"
    else:
        cat = RNG.choice(list(SCAM_ANSWERS))
        new = 1 if RNG.random() < 0.9 else 0
        ratio = lognorm(0.9, 0.8)
        rec_ratio = ratio if new else lognorm(1.0, 0.8)
        night = RNG.random() < 0.12
        call = RNG.random() < 0.65
        recent = min(np.random.poisson(0.7), 5)
        bal_frac = min(2 ** ratio * RNG.uniform(0.08, 0.45), 1.5)
        no_inflow = 1 if cat == "sent_by_mistake" else 0
        answer = RNG.choice(SCAM_ANSWERS[cat]) if RNG.random() < 0.72 else RNG.choice(DEFLECT)
    sc = scam.match(answer)
    feats = {
        "is_new_recipient": new, "log_recipient_ratio": round(rec_ratio, 4), "is_night": int(night),
        "recent_sends_30m": int(recent), "balance_fraction": round(bal_frac, 4),
        "on_active_call": int(call), "return_claim_no_inflow": no_inflow,
        "scam_score": sc["score"], "is_recharge": int(recharge),
    }
    return feats, {"category": cat, "hits": sc["hits"]}, answer


def build(n: int):
    rows, metas, ys = [], [], []
    for _ in range(n):
        y = 1 if RNG.random() < 0.28 else 0
        f, m, _ = scenario(y)
        rows.append(f); metas.append(m); ys.append(y)
    return rows, metas, np.array(ys)


def hard_red(feats: dict, hits: list) -> bool:
    """Same hard rules as api/app/core/risk.py."""
    return bool(feats["return_claim_no_inflow"]
                or any(h["level"] == "high" and h["category"] != "sent_by_mistake" for h in hits)
                or (any(h.get("escalate_if") == "new_recipient" for h in hits)
                    and feats["is_new_recipient"]))


def levels(p1, p2, h1, h2, th):
    """Two-stage decision: stage 1 = command only; stage 2 (interview) only
    when stage 1 is YELLOW or RED."""
    lv1 = np.where(h1 | (p1 >= th["red"]), 2, np.where(p1 >= th["yellow"], 1, 0))
    lv2 = np.where(h2 | (p2 >= th["red"]), 2, np.where(p2 >= th["yellow"], 1, 0))
    return np.where(lv1 > 0, lv2, 0)


def rates(lv, y):
    scam, legit = y == 1, y == 0
    return {
        "scam_flagged_rate": round(float(np.mean(lv[scam] > 0)), 4),
        "scam_red_rate": round(float(np.mean(lv[scam] == 2)), 4),
        "legit_red_rate": round(float(np.mean(lv[legit] == 2)), 4),
        "legit_flagged_rate": round(float(np.mean(lv[legit] > 0)), 4),
        "n_scam": int(scam.sum()), "n_legit": int(legit.sum()),
    }


def main() -> None:
    np.random.seed(7)
    rows, metas, y = build(N)
    X2 = np.array([vector(r) for r in rows])                       # with answers
    X1 = np.array([vector(dict(r, scam_score=0.0)) for r in rows])  # command only
    h2 = np.array([hard_red(r, m["hits"]) for r, m in zip(rows, metas)])
    h1 = np.array([bool(r["return_claim_no_inflow"]) for r in rows])
    idx = np.arange(N)
    np.random.shuffle(idx)
    tr, va, te = idx[: int(.7 * N)], idx[int(.7 * N): int(.85 * N)], idx[int(.85 * N):]

    scaler = StandardScaler().fit(X2[tr])
    lr = LogisticRegression(max_iter=2000, C=1.0).fit(scaler.transform(X2[tr]), y[tr])
    gb = HistGradientBoostingClassifier(max_iter=200, random_state=7).fit(X2[tr], y[tr])
    p1 = lr.predict_proba(scaler.transform(X1))[:, 1]
    p2 = lr.predict_proba(scaler.transform(X2))[:, 1]

    # thresholds tuned on the validation split only: keep legit RED <= 2%,
    # then catch as many scams as possible while bothering few honest users
    best = None
    for red in np.arange(0.4, 0.96, 0.02):
        for yel in np.arange(0.05, red, 0.01):
            th = {"yellow": round(float(yel), 3), "red": round(float(red), 3)}
            r = rates(levels(p1[va], p2[va], h1[va], h2[va], th), y[va])
            if r["legit_red_rate"] > 0.02:
                continue
            obj = r["scam_flagged_rate"] + 0.5 * r["scam_red_rate"] - 1.0 * r["legit_flagged_rate"]
            if best is None or obj > best[0]:
                best = (obj, th)
    th = best[1]

    # baseline: simple hand rules, no ML and no interview
    def baseline(f):
        if f["is_new_recipient"] and f["log_recipient_ratio"] > 2 and f["on_active_call"]:
            return 2
        if f["is_new_recipient"] and f["log_recipient_ratio"] > 1:
            return 1
        return 0

    test_ml = rates(levels(p1[te], p2[te], h1[te], h2[te], th), y[te])
    test_base = rates(np.array([baseline(rows[i]) for i in te]), y[te])
    metrics = {
        "dataset": {"total": N, "train": len(tr), "validation": len(va), "test": len(te),
                    "scam_share": round(float(y.mean()), 3),
                    "note": "Synthetic scenarios. Numbers show the pipeline works as designed; "
                            "they are not real-world fraud results."},
        "thresholds": th,
        "test_auc": {
            "logistic_regression": round(float(roc_auc_score(y[te], p2[te])), 4),
            "gradient_boosting": round(float(roc_auc_score(y[te], gb.predict_proba(X2[te])[:, 1])), 4),
        },
        "test_pipeline": {"ml_plus_interview_plus_rules": test_ml,
                          "baseline_rules_only": test_base},
        "model_choice": "Logistic regression: AUC close to gradient boosting and every "
                        "warning can be explained feature by feature.",
        "coefficients": dict(zip(FEATURES, [round(c, 3) for c in lr.coef_[0].tolist()])),
        "trained_at": datetime.now().isoformat(timespec="seconds"),
    }
    (ROOT / "model").mkdir(exist_ok=True)
    joblib.dump({"scaler": scaler, "model": lr, "thresholds": th, "features": FEATURES,
                 "trained_at": metrics["trained_at"]}, ROOT / "model" / "risk_model.joblib")
    (ROOT / "model" / "risk_metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
