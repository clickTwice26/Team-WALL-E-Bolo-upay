"""Impact simulator: what the scam shield would mean per N transfers.

Simulation, not real results. The detection rates come from the simulated
test split (model/risk_metrics.json); they are per scam and per honest
payment, so they can be rescaled to any scam prevalence. Everything else is
an explicit assumption with a low / mid / high value
(data/impact_assumptions.json), shown next to the numbers.
"""
from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

from . import store
from .core import risk

ROOT = Path(__file__).resolve().parents[2]
CASES = ("low", "mid", "high")
MODELS = {"bolo_upay": "ml_plus_interview_plus_rules", "previous_model": "previous_model_9_features",
          "rules_only": "baseline_rules_only"}


@lru_cache(maxsize=1)
def assumptions() -> dict:
    return json.loads((ROOT / "data" / "impact_assumptions.json").read_text(encoding="utf-8"))


def _metrics() -> dict:
    p = risk.MODEL_PATH.parent / "risk_metrics.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _shield(rates: dict, base: dict, transfers: int, prevalence: float, a: dict, case: str) -> dict:
    scams = transfers * prevalence
    honest = transfers - scams
    held = scams * rates["scam_red_rate"]
    yellow = scams * (rates["scam_flagged_rate"] - rates["scam_red_rate"])
    stopped = held * a["stop_rate_red"][case] + yellow * a["stop_rate_yellow"][case]
    protected = (held * a["stop_rate_red"][case] * base.get("scam_amount_mean_red", 0)
                 + yellow * a["stop_rate_yellow"][case] * base.get("scam_amount_mean_yellow", 0))
    warned = honest * rates["legit_flagged_rate"]
    return {
        "scams": round(scams, 1),
        "scams_flagged": round(scams * rates["scam_flagged_rate"], 1),
        "scams_held_red": round(held, 1),
        "scams_stopped": round(stopped, 1),
        "tk_protected": round(protected),
        "honest_warned": round(warned, 1),
        "honest_held_red": round(honest * rates["legit_red_rate"], 1),
        "honest_minutes_spent": round(warned * a["seconds_per_warning"][case] / 60, 1),
        "honest_payments_abandoned": round(warned * a["abandon_rate_after_warning"][case], 1),
    }


def _disputes(a: dict, case: str) -> dict:
    mistakes = (a["mfs_disputes_per_year"][case] * a["upay_share_of_disputes"][case]
                * a["share_disputes_wrong_number_or_amount"][case])
    avoided = mistakes * a["mistake_guard_catch_rate"][case]
    return {"upay_mistake_disputes_per_year": round(mistakes), "avoided_per_year": round(avoided),
            "cost_saved_tk_per_year": round(avoided * a["cost_per_dispute_tk"][case])}


def simulate(transfers: int, prevalence: float) -> dict:
    m = _metrics()
    tp, base, a = m.get("test_pipeline", {}), m.get("impact_base", {}), assumptions()
    shield = {name: {case: _shield(tp[key], base, transfers, prevalence, a, case) for case in CASES}
              for name, key in MODELS.items() if key in tp}
    hs = store.list_handoffs()
    return {
        "label": "Simulation on synthetic data, not real results",
        "transfers": transfers,
        "prevalence": prevalence,
        "shield": shield,
        "disputes": {case: _disputes(a, case) for case in CASES},
        "support": {"handoffs": len(hs), "by_reason": dict(Counter(h["context"].get("category") for h in hs))},
        "rates_from": "model/risk_metrics.json test split (simulated)",
        "assumptions": {k: v for k, v in a.items() if k != "note"},
    }
