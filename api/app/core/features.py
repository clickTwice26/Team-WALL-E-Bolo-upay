"""Risk features computed from the user's own wallet history.

The same function is used to build the training data (ml/train_risk.py) and
at request time, so training and serving can never drift apart.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from statistics import mean, median, pstdev
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Dhaka")

BASE_FEATURES = [
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

# Money leaving the wallet (types the app has now or will have)
OUT_TYPES = ("send_money", "mobile_recharge", "cash_out", "bill_payment", "merchant_payment")

# Sequence and personal-baseline signals: what happened over the last hours
# and days, and how this payment compares with the user's own habits.
SEQUENCE_FEATURES = [
    "sends_24h",              # payments out in the last 24 hours
    "new_recipients_7d",      # numbers paid for the first time in the last 7 days (not contacts)
    "inflow_then_outflow",    # money from a never-seen number in the last 2 hours, and at
                              # least half of it is now going to someone else (mule pattern)
    "amount_z_user",          # this amount against the user's own spread of payments
    "log_recipient_age",      # log(1 + days since the first payment to this number); 0 if never
    "hour_unusual_for_user",  # under 5% of the user's payments were within an hour of now
    "recipient_paid_you_7d",  # this number sent the user money in the last 7 days (refunds)
]

INTENT_FEATURES = ["is_cash_out", "is_payment"]  # cash-out at an agent; bill or merchant payment

# R10 voice guard, measured on the phone: scores and yes/no only, never audio.
# Not measured counts as 0, the lowest value, so it can never lower the risk.
VOICE_FEATURES = [
    "hesitation",      # share of the spoken command spent in long pauses (0..1)
    "speaker_echo",    # in a call with the loudspeaker on (someone talking the user through it)
    "voice_mismatch",  # not the enrolled owner's voice (on-device model, pending)
    "second_voice",    # two different speakers in the command (on-device model, pending)
]

# What the risk model sees, in this order
FEATURES = BASE_FEATURES + SEQUENCE_FEATURES + INTENT_FEATURES + VOICE_FEATURES


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


def _first(txs: list[dict]) -> dict[str, datetime]:
    """Earliest time each counterparty appears in ``txs``."""
    out: dict[str, datetime] = {}
    for t in txs:
        cp, ts = t["counterparty"], _ts(t)
        if cp and (cp not in out or ts < out[cp]):
            out[cp] = ts
    return out


def sequence(amount: float, phone: str | None, history: list[dict], contacts: list[dict],
             now: datetime, self_phone: str | None = None) -> dict:
    """The SEQUENCE_FEATURES, from history strictly up to ``now``."""
    past = [t for t in history if _ts(t) <= now]
    outs = [t for t in past if t["type"] in OUT_TYPES]
    known = {c["phone"] for c in contacts} | ({self_phone} if self_phone else set())
    first_paid = _first(outs)
    first_seen = _first(past)

    new_7d = sum(1 for cp, ts in first_paid.items()
                 if cp not in known and now - ts <= timedelta(days=7))

    mule = 0
    for t in past:
        if t["type"] != "receive" or not timedelta(0) <= now - _ts(t) <= timedelta(hours=2):
            continue
        cp = t["counterparty"]
        never_seen_before = cp not in known and first_seen.get(cp) == _ts(t)
        if never_seen_before and t["amount"] >= 500 and cp != phone and amount >= 0.5 * t["amount"]:
            mule = 1

    # the user's own spread of payments (recharges are small and would skew it)
    logs = [math.log(max(t["amount"], 1)) for t in outs if t["type"] != "mobile_recharge"]
    z = 0.0
    if len(logs) >= 5:
        z = (math.log(max(amount, 1)) - mean(logs)) / max(pstdev(logs), 0.25)
        z = max(-3.0, min(z, 6.0))

    age = 0.0
    if phone in first_paid:
        age = math.log1p(max((now - first_paid[phone]).total_seconds(), 0) / 86400)

    unusual = 0
    if len(outs) >= 10:
        h = now.astimezone(TZ)
        here = h.hour + h.minute / 60

        def dist(t: dict) -> float:
            th = _ts(t).astimezone(TZ)
            d = abs(th.hour + th.minute / 60 - here)
            return min(d, 24 - d)
        unusual = 1 if sum(1 for t in outs if dist(t) <= 1) / len(outs) < 0.05 else 0

    return {
        "sends_24h": min(sum(1 for t in outs if now - _ts(t) <= timedelta(hours=24)), 10),
        "new_recipients_7d": min(new_7d, 5),
        "inflow_then_outflow": mule,
        "amount_z_user": round(z, 4),
        "log_recipient_age": round(age, 4),
        "hour_unusual_for_user": unusual,
        "recipient_paid_you_7d": int(any(t["type"] == "receive" and t["counterparty"] == phone
                                         and now - _ts(t) <= timedelta(days=7) for t in past)),
    }


def compute(amount: float, intent: str, phone: str | None, is_return_claim: bool,
            balance: float, history: list[dict], contacts: list[dict],
            on_call: bool, scam_score: float, now: datetime | None = None,
            self_phone: str | None = None, voice: dict | None = None) -> tuple[dict, dict]:
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
        "is_cash_out": 1 if intent == "cash_out" else 0,
        "is_payment": 1 if intent in ("bill_payment", "merchant_payment") else 0,
    }
    feats.update(sequence(amount, phone, history, contacts, now, self_phone))
    v = voice or {}  # None or missing = not measured
    feats.update({"hesitation": round(min(max(float(v.get("hesitation") or 0.0), 0.0), 1.0), 3),
                  **{k: 1 if v.get(k) else 0 for k in ("speaker_echo", "voice_mismatch", "second_voice")}})
    return feats, s


def vector(feats: dict) -> list[float]:
    return [float(feats[f]) for f in FEATURES]
