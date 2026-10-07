"""Sequence and personal-baseline features (features.sequence)."""
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

from app.core import features
from app.core.features import SEQUENCE_FEATURES, TZ

NOW = datetime(2026, 10, 3, 11, 0, tzinfo=TZ)
ME = "01700000001"
AMMU = {"phone": "01700000101"}
CONTACTS = [AMMU]


def tx(kind, who, amount, ago, i=[0]):
    i[0] += 1
    return {"id": f"t{i[0]}", "user_id": "u1", "type": kind, "counterparty": who,
            "amount": amount, "ts": (NOW - ago).isoformat()}


def seq(amount, phone, history, now=NOW):
    return features.sequence(amount, phone, history, CONTACTS, now, self_phone=ME)


def habits(n=20):
    """n payments to Ammu around 10-12 o'clock over the last two months."""
    return [tx("send_money", AMMU["phone"], 1000 + 50 * (k % 5), timedelta(days=3 * k + 3, hours=k % 3 - 1))
            for k in range(n)]


def test_all_sequence_features_are_returned():
    assert set(seq(500, AMMU["phone"], habits())) == set(SEQUENCE_FEATURES)


def test_sends_24h_counts_only_money_out_in_the_last_day():
    h = [tx("send_money", "01811111111", 100, timedelta(hours=2)),
         tx("mobile_recharge", ME, 50, timedelta(hours=20)),
         tx("receive", "01822222222", 900, timedelta(hours=1)),       # money in: not counted
         tx("send_money", "01811111111", 100, timedelta(hours=30))]   # too old
    assert seq(100, AMMU["phone"], h)["sends_24h"] == 2


def test_new_recipients_7d_ignores_contacts_and_old_recipients():
    h = [tx("send_money", "01811111111", 100, timedelta(days=1)),
         tx("send_money", "01822222222", 100, timedelta(days=6)),
         tx("send_money", "01833333333", 100, timedelta(days=40)),    # first paid long ago
         tx("send_money", "01833333333", 100, timedelta(days=2)),
         tx("send_money", AMMU["phone"], 100, timedelta(days=1))]     # a contact
    assert seq(100, AMMU["phone"], h)["new_recipients_7d"] == 2


def test_inflow_then_outflow_is_the_mule_pattern():
    stranger, other = "01899999999", "01977777777"
    h = habits() + [tx("receive", stranger, 10000, timedelta(minutes=40))]
    assert seq(6000, other, h)["inflow_then_outflow"] == 1
    assert seq(2000, other, h)["inflow_then_outflow"] == 0      # under half of what arrived
    assert seq(10000, stranger, h)["inflow_then_outflow"] == 0  # sending it back is a refund
    later = NOW + timedelta(hours=3)
    assert seq(6000, other, h, now=later)["inflow_then_outflow"] == 0  # more than 2 hours ago
    known = h + [tx("receive", stranger, 500, timedelta(days=20))]  # this number paid before
    assert seq(6000, other, known)["inflow_then_outflow"] == 0


def test_amount_z_user_compares_with_the_users_own_spread():
    h = habits()
    assert abs(seq(1100, AMMU["phone"], h)["amount_z_user"]) < 1
    assert seq(11000, AMMU["phone"], h)["amount_z_user"] >= 5
    assert seq(11000, AMMU["phone"], h[:3])["amount_z_user"] == 0  # too little history


def test_log_recipient_age():
    h = habits()
    first = max((NOW - features._ts(t)).total_seconds() for t in h) / 86400
    assert math.isclose(seq(500, AMMU["phone"], h)["log_recipient_age"], round(math.log1p(first), 4))
    assert seq(500, "01899999999", h)["log_recipient_age"] == 0


def test_hour_unusual_for_user():
    h = habits()
    night = NOW.replace(hour=3)
    assert seq(1000, AMMU["phone"], h, now=night)["hour_unusual_for_user"] == 1
    assert seq(1000, AMMU["phone"], h)["hour_unusual_for_user"] == 0
    assert seq(1000, AMMU["phone"], h[:5], now=night)["hour_unusual_for_user"] == 0  # too few


def test_recipient_paid_you_7d():
    friend = "01899999999"
    h = habits() + [tx("receive", friend, 1000, timedelta(days=2))]
    assert seq(1000, friend, h)["recipient_paid_you_7d"] == 1
    assert seq(1000, "01977777777", h)["recipient_paid_you_7d"] == 0
    assert seq(1000, friend, h, now=NOW + timedelta(days=6))["recipient_paid_you_7d"] == 0


def test_future_transactions_are_ignored():
    h = [tx("send_money", "01811111111", 100, timedelta(hours=-1))]  # one hour after "now"
    assert seq(100, AMMU["phone"], h)["sends_24h"] == 0


def test_seed_users_get_the_new_features_from_compute():
    seed = json.loads((Path(__file__).resolve().parents[2] / "data" / "seed.json").read_text(encoding="utf-8"))
    u = seed["users"][0]
    hist = [t for t in seed["transactions"] if t["user_id"] == u["id"]]
    feats, _ = features.compute(2000, "send_money", u["contacts"][0]["phone"], False, u["balance"],
                                hist, u["contacts"], False, 0.0, now=NOW, self_phone=u["phone"])
    assert set(SEQUENCE_FEATURES) <= set(feats)
    assert feats["log_recipient_age"] > 0 and feats["inflow_then_outflow"] == 0
    assert len(features.vector(feats)) == len(features.FEATURES)  # the model's inputs are unchanged
