"""Train and evaluate the scam-risk model on simulated wallet timelines.

The data comes from ml/simulate.py: synthetic users with six months of
history, then a month of payments to score (honest ones and nine kinds of
scam). Features are computed by the API's own feature code from the history
up to each payment, and the scam_score feature comes from running the real
scam phrase matcher on simulated interview answers.

The evaluation is two-stage, like the app:
  stage 1: command only (no interview answers yet)
  stage 2: if stage 1 is YELLOW/RED, the user answers the interview questions

Split by time, so the model is always tested on later payments than it
learned from: 60% train, 10% calibration, 15% threshold tuning, 15% test.

Four models are compared on the same split:
  logistic regression, original 9 features   (the previous model)
  gradient boosting,   original 9 features
  logistic regression, all features           (kept as the fallback)
  gradient boosting,   all features, monotonic and calibrated  (served)

Calibration is sigmoid (Platt): isotonic made ties that cost PR-AUC, sigmoid
keeps the ranking. The boosting settings were picked on the tuning split.

Run:  python ml/train_risk.py
Writes model/risk_model.joblib, model/risk_metrics.json and, when matplotlib
is installed, docs/img/calibration.png
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "ml"))
from app.core.features import BASE_FEATURES, FEATURES, vector  # noqa: E402
import simulate  # noqa: E402

# +1: more of this can only raise the risk; -1: can only lower it
MONOTONIC = {
    "is_new_recipient": 1, "log_recipient_ratio": 1, "is_night": 1, "recent_sends_30m": 1,
    "balance_fraction": 1, "on_active_call": 1, "return_claim_no_inflow": 1, "scam_score": 1,
    "sends_24h": 1, "new_recipients_7d": 1, "inflow_then_outflow": 1, "amount_z_user": 1,
    "log_recipient_age": -1, "hour_unusual_for_user": 1, "recipient_paid_you_7d": -1,
}
BASE_IDX = [FEATURES.index(f) for f in BASE_FEATURES]


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


MAX_HONEST_RED = 0.02   # honest payments held at RED
MAX_HONEST_WARNED = 0.12  # honest payments that see any warning (about 1 in 8)


def tune(p1, p2, h1, h2, y):
    """Thresholds from the tuning split only: hold at most 2% of honest payments
    and warn at most 12%, then catch as many scams as possible."""
    best = None
    for red in np.arange(0.30, 0.97, 0.02):
        for yel in np.arange(0.02, red, 0.01):
            th = {"yellow": round(float(yel), 3), "red": round(float(red), 3)}
            r = rates(levels(p1, p2, h1, h2, th), y)
            if r["legit_red_rate"] > MAX_HONEST_RED or r["legit_flagged_rate"] > MAX_HONEST_WARNED:
                continue
            obj = r["scam_flagged_rate"] + 0.5 * r["scam_red_rate"]
            if best is None or obj > best[0]:
                best = (obj, th)
    return best[1]


def baseline(f: dict) -> int:
    """Simple hand rules, no ML and no interview."""
    if f["is_new_recipient"] and f["log_recipient_ratio"] > 2 and f["on_active_call"]:
        return 2
    if f["is_new_recipient"] and f["log_recipient_ratio"] > 1:
        return 1
    return 0


def scores(y, p):
    return {"roc_auc": round(float(roc_auc_score(y, p)), 4),
            "pr_auc": round(float(average_precision_score(y, p)), 4),
            "brier": round(float(brier_score_loss(y, p)), 4)}


def by_kind(events, lv):
    """Share flagged (YELLOW or RED) for each scam kind and each honest kind."""
    out: dict[str, list] = defaultdict(list)
    for e, level in zip(events, lv):
        out[e["kind"]].append(int(level > 0))
    return {k: {"n": len(v), "flagged_rate": round(sum(v) / len(v), 3)} for k, v in sorted(out.items())}


def _choice(c: dict) -> str:
    """Why this model, from the numbers measured on this run's test split."""
    gb, lr, old = (c["gradient_boosting_all_features_calibrated"], c["logistic_regression_all_features"],
                   c["logistic_regression_9_features"])
    return (f"Gradient boosting on all features, monotonic and sigmoid-calibrated. Test PR-AUC "
            f"{gb['pr_auc']} (logistic regression on the same features {lr['pr_auc']}, previous 9-feature "
            f"model {old['pr_auc']}); Brier score {gb['brier']} ({lr['brier']}, {old['brier']}). Monotonic "
            f"constraints mean more risk evidence can never lower the score, calibration makes the "
            f"probability mean what it says, and SHAP values explain each decision. Logistic regression "
            f"on all features stays in the bundle as the fallback.")


def plot_calibration(curves: dict, path: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    fig, ax = plt.subplots(figsize=(4.6, 4.2), dpi=150)
    ax.plot([0, 1], [0, 1], color="#9aa5b8", lw=1, ls="--", label="perfectly calibrated")
    for (name, c), color in zip(curves.items(), ("#0b4ea8", "#e0a100")):
        ax.plot(c["predicted"], c["observed"], marker="o", ms=3.5, lw=1.6, color=color, label=name)
    ax.set_xlabel("predicted scam probability")
    ax.set_ylabel("observed share of scams")
    ax.set_title("Calibration on the test split", fontsize=10)
    ax.legend(fontsize=7, frameon=False, loc="upper left")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    return True


def main() -> None:
    events = simulate.generate()  # time order
    n = len(events)
    y = np.array([e["label"] for e in events])
    X2 = np.array([vector(e["feats"]) for e in events])                      # with answers
    X1 = np.array([vector(dict(e["feats"], scam_score=0.0)) for e in events])  # command only
    h2 = np.array([hard_red(e["feats"], e["hits"]) for e in events])
    h1 = np.array([bool(e["feats"]["return_claim_no_inflow"]) for e in events])
    cut = [int(n * q) for q in (0.60, 0.70, 0.85)]
    tr, ca, va, te = (np.arange(0, cut[0]), np.arange(cut[0], cut[1]),
                      np.arange(cut[1], cut[2]), np.arange(cut[2], n))
    fit = np.concatenate([tr, ca])  # models without a calibration step learn from both

    def lr_model(cols):
        sc = StandardScaler().fit(X2[fit][:, cols])
        m = LogisticRegression(max_iter=3000, C=1.0).fit(sc.transform(X2[fit][:, cols]), y[fit])
        return sc, m, (lambda X: m.predict_proba(sc.transform(X[:, cols]))[:, 1])

    _, _, lr_base = lr_model(BASE_IDX)
    gb_base_m = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06, random_state=7)
    gb_base_m.fit(X2[fit][:, BASE_IDX], y[fit])
    gb_base = lambda X: gb_base_m.predict_proba(X[:, BASE_IDX])[:, 1]  # noqa: E731
    lr_scaler, lr_all_m, lr_all = lr_model(list(range(len(FEATURES))))

    gb = HistGradientBoostingClassifier(max_iter=600, learning_rate=0.03, max_leaf_nodes=31,
                                        l2_regularization=2.0, min_samples_leaf=40, random_state=7,
                                        monotonic_cst=[MONOTONIC.get(f, 0) for f in FEATURES])
    gb.fit(X2[tr], y[tr])
    calibrated = CalibratedClassifierCV(FrozenEstimator(gb), method="sigmoid").fit(X2[ca], y[ca])
    served = lambda X: calibrated.predict_proba(X)[:, 1]  # noqa: E731

    models = {"logistic_regression_9_features": lr_base, "gradient_boosting_9_features": gb_base,
              "logistic_regression_all_features": lr_all, "gradient_boosting_all_features_calibrated": served}
    comparison = {name: scores(y[te], f(X2[te])) for name, f in models.items()}

    # thresholds and test pipeline for the served model, the fallback and the old model
    def pipeline(f):
        p1, p2 = f(X1), f(X2)
        th = tune(p1[va], p2[va], h1[va], h2[va], y[va])
        lv = levels(p1[te], p2[te], h1[te], h2[te], th)
        return th, lv

    th, lv = pipeline(served)
    th_fallback, lv_fallback = pipeline(lr_all)
    _, lv_old = pipeline(lr_base)
    lv_base = np.array([baseline(events[i]["feats"]) for i in te])

    curves = {}
    for name, p in (("gradient boosting, calibrated (served)", served(X2[te])),
                    ("gradient boosting, raw", gb.predict_proba(X2[te])[:, 1])):
        obs, pred = calibration_curve(y[te], p, n_bins=10, strategy="quantile")
        curves[name] = {"predicted": [round(float(v), 4) for v in pred], "observed": [round(float(v), 4) for v in obs]}
    plotted = plot_calibration(curves, ROOT / "docs" / "img" / "calibration.png")

    importance = {}
    try:
        import shap
        sv = np.asarray(shap.TreeExplainer(gb).shap_values(X2[te]))
        importance = dict(sorted(((f, round(float(v), 4)) for f, v in zip(FEATURES, np.abs(sv).mean(axis=0))),
                                 key=lambda kv: -kv[1]))
    except ImportError:
        print("shap is not installed: skipping feature importance")

    trained_at = datetime.now().isoformat(timespec="seconds")
    test_events = [events[i] for i in te]
    metrics = {
        "dataset": {"total": n, "train": len(tr), "calibration": len(ca), "validation": len(va), "test": len(te),
                    "scam_share": round(float(y.mean()), 3), "split": "by time",
                    "kinds": dict(sorted({k: sum(e["kind"] == k for e in events)
                                          for k in {e["kind"] for e in events}}.items())),
                    "note": "Simulated wallet timelines. Numbers show the pipeline works as designed; "
                            "they are not real-world fraud results."},
        "model": "gradient_boosting",
        "features": FEATURES,
        "thresholds": th,
        "threshold_rules": {"max_honest_red": MAX_HONEST_RED, "max_honest_warned": MAX_HONEST_WARNED},
        "comparison": comparison,
        "test_auc": {"logistic_regression": comparison["logistic_regression_9_features"]["roc_auc"],
                     "gradient_boosting": comparison["gradient_boosting_all_features_calibrated"]["roc_auc"]},
        "test_pipeline": {"ml_plus_interview_plus_rules": rates(lv, y[te]),
                          "previous_model_9_features": rates(lv_old, y[te]),
                          "fallback_logistic_regression": rates(lv_fallback, y[te]),
                          "baseline_rules_only": rates(lv_base, y[te])},
        "test_by_kind": by_kind(test_events, lv),
        "calibration": curves,
        "feature_importance": importance,
        "fallback": {"model": "logistic_regression", "thresholds": th_fallback,
                     "coefficients": dict(zip(FEATURES, [round(c, 3) for c in lr_all_m.coef_[0].tolist()]))},
        "model_choice": _choice(comparison),
        "trained_at": trained_at,
    }
    (ROOT / "model").mkdir(exist_ok=True)
    joblib.dump({"name": "gradient_boosting", "model": calibrated, "gb": gb, "features": FEATURES,
                 "thresholds": th, "trained_at": trained_at,
                 "fallback": {"scaler": lr_scaler, "model": lr_all_m, "thresholds": th_fallback}},
                ROOT / "model" / "risk_model.joblib", compress=3)
    (ROOT / "model" / "risk_metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: metrics[k] for k in ("comparison", "thresholds", "test_pipeline")}, indent=2))
    print("calibration plot:", "docs/img/calibration.png" if plotted else "skipped (matplotlib not installed)")


if __name__ == "__main__":
    main()
