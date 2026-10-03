"""Risk features computed from the user's own wallet history.

The same function is used to build the training data (ml/train_risk.py) and
at request time, so training and serving can never drift apart.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Dhaka")

FEATURES = [
    "is_new_recipient",       # never sent to, not in contacts
    "log_recipient_ratio",    # log2(amount / usual amount to this recipient,
                              #       or the user's median send if new)
    "is_night",               # 00:00-05:00 Dhaka time
    "recent_sends_30m",       # sends in the last 30 minutes
    "balance_fraction",       # share of balance being sent
    "on_active_call",         # native app signal (simulated in the prototype)
    "return_claim_no_inflow", # "send it back" but nothing came from that number
    "scam_score",             # scam phrases in the command / interview answers
    "is_recharge",
]


def _ts(t: dict) -> datetime:
    return datetime.fromisoformat(t["ts"])


def summarize(history: list[dict], contacts: list[dict], phone: str | None,
              now: datetime) -> dict:
    sends = [t for t in history if t["type"] in ("send_money", "mobile_recharge")]
    send_money = [t for t in history if t["type"] == "send_money"]
    to_rec = [t["amount"] for t in send_money if t["counterparty"] == phone]
    inflow = [t for t in history if t["type"] == "receive" and t["counterparty"] == phone
              and now - _ts(t) <= timedelta(days=7)]
    return {
        "median_send": median([t["amount"] for t in send_money]) if send_money else 500.0,
        "recipient_median": median(to_rec) if to_rec else None,
        "recipient_count": len(to_rec),
        "in_contacts": any(c["phone"] == phone for c in contacts),
        "recent_sends_30m": sum(1 for t in sends if timedelta(0) <= now - _ts(t) <= timedelta(minutes=30)),
        "has_recent_inflow": bool(inflow),
    }


def compute(amount: float, intent: str, phone: str | None, is_return_claim: bool,
            balance: float, history: list[dict], contacts: list[dict],
            on_call: bool, scam_score: float, now: datetime | None = None,
            self_phone: str | None = None) -> tuple[dict, dict]:
    now = now or datetime.now(TZ)
    s = summarize(history, contacts, phone, now)
    is_self = self_phone is not None and phone == self_phone
    is_new = 0 if (is_self or s["in_contacts"] or s["recipient_count"] > 0) else 1
    ratio_user = math.log2(max(amount, 1) / max(s["median_send"], 1))
    base = s["recipient_median"] if s["recipient_median"] else s["median_send"]
    ratio_rec = math.log2(max(amount, 1) / max(base, 1))
    hour = now.astimezone(TZ).hour
    feats = {
        "is_new_recipient": is_new,
        "log_amount_ratio": round(ratio_user, 4),
        "log_recipient_ratio": round(ratio_rec, 4),
        "is_night": 1 if hour < 5 else 0,
        "recent_sends_30m": min(s["recent_sends_30m"], 5),
        "balance_fraction": round(min(amount / balance, 1.5), 4) if balance > 0 else 1.5,
        "on_active_call": 1 if on_call else 0,
        "return_claim_no_inflow": 1 if (is_return_claim and not s["has_recent_inflow"]) else 0,
        "scam_score": float(scam_score),
        "is_recharge": 1 if intent == "mobile_recharge" else 0,
    }
    return feats, s


def vector(feats: dict) -> list[float]:
    return [float(feats[f]) for f in FEATURES]
