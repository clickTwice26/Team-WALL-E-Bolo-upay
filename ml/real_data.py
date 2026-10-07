"""Load real wallet data (from upay, see docs/DATA_REQUEST.md) as training events.

Schema: one CSV row per wallet transaction, oldest first per user:
  user_id, ts (ISO 8601 with offset), type (send_money | mobile_recharge |
  cash_out | merchant_payment | bill_payment | receive), counterparty
  (hashed phone or merchant id), amount, balance_before, label (1 = a
  confirmed fraud report, 0 = not; empty for incoming money)

Every outgoing row becomes one event whose features are computed from that
user's earlier rows with the same code the API serves with, so training on
real data can never drift from serving. Signals the data cannot carry (an
active call, scam words in what the user said) are 0.
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from app.core.features import OUT_TYPES, compute  # noqa: E402

REQUIRED = ("user_id", "ts", "type", "counterparty", "amount", "balance_before", "label")
TYPES = set(OUT_TYPES) | {"receive"}


class SchemaError(ValueError):
    pass


def load(path: str | Path) -> list[dict]:
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    if not rows:
        raise SchemaError(f"{path}: no rows")
    missing = [c for c in REQUIRED if c not in rows[0]]
    if missing:
        raise SchemaError(f"{path}: missing columns {missing}; expected {list(REQUIRED)} (docs/DATA_REQUEST.md)")
    by_user: dict[str, list[dict]] = defaultdict(list)
    for i, r in enumerate(rows, start=2):
        try:
            t = {"type": r["type"], "counterparty": r["counterparty"], "amount": float(r["amount"]),
                 "ts": datetime.fromisoformat(r["ts"]).isoformat(), "balance": float(r["balance_before"]),
                 "label": r["label"].strip()}
        except ValueError as e:
            raise SchemaError(f"{path} line {i}: {e}") from e
        if t["type"] not in TYPES:
            raise SchemaError(f"{path} line {i}: unknown type {t['type']!r}; one of {sorted(TYPES)}")
        if t["type"] != "receive" and t["label"] not in ("0", "1"):
            raise SchemaError(f"{path} line {i}: label must be 0 or 1 for outgoing money")
        by_user[r["user_id"]].append(t)
    events = []
    for uid, txs in by_user.items():
        txs.sort(key=lambda t: t["ts"])
        for k, t in enumerate(txs):
            if t["type"] == "receive":
                continue
            feats, _ = compute(amount=t["amount"], intent=t["type"], phone=t["counterparty"],
                               is_return_claim=False, balance=t["balance"], history=txs[:k],
                               contacts=[], on_call=False, scam_score=0.0,
                               now=datetime.fromisoformat(t["ts"]))
            events.append({"feats": feats, "label": int(t["label"]), "hits": [], "amount": t["amount"],
                           "kind": "fraud" if t["label"] == "1" else "honest", "ts": t["ts"]})
    events.sort(key=lambda e: e["ts"])  # the split is by time
    return events
