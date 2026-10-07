"""Model health for upay's ops team: is the scam shield still behaving?

Compares recent risk checks with what the model saw in training and with
what users and outcomes say:
  drift      PSI of every input against its training distribution
             (PSI > 0.2 means the input has shifted; review the thresholds)
  level mix  GREEN / YELLOW / RED share now vs in training
  overrides  RED transfers the user still sent after the hold and PIN
  feedback   warnings users reported as wrong ("This warning seems wrong?")
  support    human handoffs by reason, and how long people waited
No phone numbers or answers leave this module, only counts and rates.
"""
from __future__ import annotations

import bisect
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from statistics import median

from . import store
from .core import risk

PSI_ALERT = 0.2
MIN_CHECKS = 30           # fewer recent checks than this: too little data to judge drift
WRONG_WARNING_ALERT = 0.2
RED_OVERRIDE_ALERT = 0.3
LEVELS = ("GREEN", "YELLOW", "RED")


def _reference() -> dict:
    p = risk.MODEL_PATH.parent / "risk_metrics.json"
    return json.loads(p.read_text()).get("reference", {}) if p.exists() else {}


def psi(edges: list[float], expected: list[float], values: list[float]) -> float:
    """Population stability index of ``values`` against the training shares."""
    counts = Counter(bisect.bisect_right(edges, v) for v in values)
    total = len(values)
    out = 0.0
    for i, e in enumerate(expected):
        a = max(counts.get(i, 0) / total, 1e-4)
        e = max(e, 1e-4)
        out += (a - e) * math.log(a / e)
    return round(out, 4)


def report(days: int = 14) -> dict:
    since = (store.now() - timedelta(days=days)).isoformat()
    checks = [a for a in store.assessments_since(since) if a["result"].get("level") in LEVELS]
    ref = _reference()
    alerts: list[str] = []

    by_day: dict[str, Counter] = {}
    for a in checks:
        by_day.setdefault(a["created_at"][:10], Counter())[a["result"]["level"]] += 1
    mix = Counter(a["result"]["level"] for a in checks)
    n = len(checks)
    level_mix = {lv: round(mix[lv] / n, 4) if n else 0.0 for lv in LEVELS}

    hist = [0] * 10
    for a in checks:
        p = a["result"].get("probability")
        if p is not None:
            hist[min(int(p * 10), 9)] += 1

    drift = {}
    if n >= MIN_CHECKS and ref.get("features"):
        for f, r in ref["features"].items():
            vals = [a["result"]["features"][f] for a in checks if f in (a["result"].get("features") or {})]
            if len(vals) >= MIN_CHECKS:
                drift[f] = psi(r["edges"], r["share"], vals)
        drift = dict(sorted(drift.items(), key=lambda kv: -kv[1]))
        shifted = [f for f, v in drift.items() if v > PSI_ALERT]
        if shifted:
            alerts.append(f"Inputs have shifted since training (PSI > {PSI_ALERT}): {', '.join(shifted)}. "
                          "Review the thresholds and consider retraining.")

    red = [a for a in checks if a["result"]["level"] == "RED"]
    red_sent = sum(a["status"] == "executed" for a in red)
    override = round(red_sent / len(red), 4) if red else 0.0
    if len(red) >= 10 and override > RED_OVERRIDE_ALERT:
        alerts.append(f"{override:.0%} of RED transfers were still sent: check whether RED is too strict "
                      "or whether people are being talked past the warning.")

    warned = [a for a in checks if a["result"]["level"] in ("YELLOW", "RED")]
    wrong = store.feedback_since(since)
    wrong_rate = round(len(wrong) / len(warned), 4) if warned else 0.0
    if len(warned) >= 10 and wrong_rate > WRONG_WARNING_ALERT:
        alerts.append(f"Users reported {wrong_rate:.0%} of warnings as wrong: review the YELLOW threshold.")

    hs = [h for h in store.list_handoffs() if h["created_at"] >= since]
    waits = []
    for h in hs:
        first = next((m for m in store.handoff_messages(h["id"]) if m["sender"] == "agent"), None)
        if first:
            waits.append((datetime.fromisoformat(first["ts"]) - datetime.fromisoformat(h["created_at"])).total_seconds() / 60)

    if n < MIN_CHECKS:
        alerts.append(f"Only {n} risk checks in the last {days} days: too few to judge drift yet.")
    return {
        "window_days": days,
        "checks": n,
        "level_mix": level_mix,
        "level_mix_training": ref.get("level_mix", {}),
        "by_day": {d: {lv: c[lv] for lv in LEVELS} for d, c in sorted(by_day.items())},
        "score_histogram": hist,
        "drift_psi": drift,
        "red_override_rate": override,
        "wrong_warning_reports": len(wrong),
        "wrong_warning_rate": wrong_rate,
        "handoffs": {"total": len(hs), "by_reason": dict(Counter(h["context"].get("category") for h in hs)),
                     "waiting_now": sum(h["status"] == "waiting" for h in hs),
                     "median_wait_minutes": round(median(waits), 1) if waits else None},
        "model": risk.model_card().get("model"),
        "alerts": alerts,
        "thresholds": {"psi": PSI_ALERT, "wrong_warning_rate": WRONG_WARNING_ALERT,
                       "red_override_rate": RED_OVERRIDE_ALERT, "min_checks": MIN_CHECKS},
    }
