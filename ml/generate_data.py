"""Generate the synthetic demo data for Bolo upay.

Writes data/seed.json: demo users, their contacts and 6 months of wallet
history. Everything is synthetic. Phone numbers use the 0170000xxxx /
0180000xxxx ranges and no real person is represented.

Run:  python ml/generate_data.py
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Dhaka")
RNG = random.Random(2026)
NOW = datetime(2026, 10, 3, 18, 0, tzinfo=TZ)


def phone(prefix: str, n: int) -> str:
    return f"{prefix}{n:04d}"


USERS = [
    {
        "id": "u1", "name": "Rahima Begum", "name_bn": "রহিমা বেগম",
        "phone": phone("0170000", 1), "persona": "Garment worker, Gazipur",
        "balance": 8450,
        "contacts": [
            {"id": "c1", "name": "Ammu", "name_bn": "আম্মু", "relation": "mother",
             "phone": phone("0170000", 101), "aliases": ["ammu", "আম্মু", "amma", "আম্মা", "ma", "মা", "maa"],
             "usual": 2000, "freq": 6},
            {"id": "c2", "name": "Rahim Uddin", "name_bn": "রহিম উদ্দিন", "relation": "brother",
             "phone": phone("0170000", 102), "aliases": ["rahim bhai", "রহিম ভাই", "rahim", "রহিম", "bhaiya", "ভাইয়া"],
             "usual": 1000, "freq": 3},
            {"id": "c3", "name": "Rahim Store", "name_bn": "রহিম স্টোর", "relation": "shop",
             "phone": phone("0170000", 103), "aliases": ["rahim store", "রহিম স্টোর", "rahim dokan", "রহিম দোকান", "rahim"],
             "usual": 350, "freq": 5},
            {"id": "c4", "name": "Salma Apa", "name_bn": "সালমা আপা", "relation": "sister",
             "phone": phone("0170000", 104), "aliases": ["salma", "সালমা", "salma apa", "সালমা আপা", "apa", "আপা"],
             "usual": 500, "freq": 2},
            {"id": "c5", "name": "Karim Landlord", "name_bn": "করিম বাড়িওয়ালা", "relation": "landlord",
             "phone": phone("0170000", 105), "aliases": ["karim", "করিম", "bariwala", "বাড়িওয়ালা", "landlord"],
             "usual": 4500, "freq": 1},
        ],
    },
    {
        "id": "u2", "name": "Karim Mia", "name_bn": "করিম মিয়া",
        "phone": phone("0170000", 2), "persona": "Grocery shop owner, Mirpur",
        "balance": 23600,
        "contacts": [
            {"id": "c6", "name": "Abbu", "name_bn": "আব্বু", "relation": "father",
             "phone": phone("0170000", 201), "aliases": ["abbu", "আব্বু", "abba", "আব্বা", "baba", "বাবা"],
             "usual": 3000, "freq": 4},
            {"id": "c7", "name": "Jamal Supplier", "name_bn": "জামাল সাপ্লায়ার", "relation": "supplier",
             "phone": phone("0170000", 202), "aliases": ["jamal", "জামাল", "supplier", "সাপ্লায়ার"],
             "usual": 6000, "freq": 4},
            {"id": "c8", "name": "Nasrin", "name_bn": "নাসরিন", "relation": "wife",
             "phone": phone("0170000", 203), "aliases": ["nasrin", "নাসরিন", "bou", "বউ"],
             "usual": 1500, "freq": 4},
            {"id": "c9", "name": "Shafiq Bhai", "name_bn": "শফিক ভাই", "relation": "friend",
             "phone": phone("0170000", 204), "aliases": ["shafiq", "শফিক", "shafiq bhai", "শফিক ভাই"],
             "usual": 800, "freq": 1},
        ],
    },
    {
        "id": "u3", "name": "Nusrat Jahan", "name_bn": "নুসরাত জাহান",
        "phone": phone("0170000", 3), "persona": "University student, Dhaka",
        "balance": 3120,
        "contacts": [
            {"id": "c10", "name": "Abbu", "name_bn": "আব্বু", "relation": "father",
             "phone": phone("0170000", 301), "aliases": ["abbu", "আব্বু", "baba", "বাবা"],
             "usual": 0, "freq": 0},
            {"id": "c11", "name": "Mess Manager Tanvir", "name_bn": "তানভীর", "relation": "mess",
             "phone": phone("0170000", 302), "aliases": ["tanvir", "তানভীর", "mess", "মেস", "manager"],
             "usual": 2500, "freq": 1},
            {"id": "c12", "name": "Riya", "name_bn": "রিয়া", "relation": "friend",
             "phone": phone("0170000", 303), "aliases": ["riya", "রিয়া", "ria"],
             "usual": 200, "freq": 3},
        ],
    },
]


def history(user: dict) -> list[dict]:
    """Six months of outgoing sends, recharges and incoming money."""
    tx = []
    start = NOW - timedelta(days=180)
    tid = 0

    def add(kind, counterparty, amount, when):
        nonlocal tid
        tid += 1
        tx.append({"id": f"{user['id']}-t{tid}", "user_id": user["id"], "type": kind,
                   "counterparty": counterparty, "amount": int(amount),
                   "ts": when.isoformat()})

    for c in user["contacts"]:
        if not c["freq"]:
            continue
        for _ in range(c["freq"] * 6):
            when = start + timedelta(days=RNG.uniform(0, 179), hours=RNG.uniform(8, 22))
            when = when.replace(hour=RNG.randint(8, 21))
            amount = max(20, round(RNG.lognormvariate(0, 0.25) * c["usual"] / 10) * 10)
            add("send_money", c["phone"], amount, when)
    # recharges to own number
    for _ in range(24):
        when = start + timedelta(days=RNG.uniform(0, 179))
        when = when.replace(hour=RNG.randint(8, 22))
        add("mobile_recharge", user["phone"], RNG.choice([20, 30, 50, 50, 100]), when)
    # incoming money (salary / family / sales)
    for _ in range(12):
        when = start + timedelta(days=RNG.uniform(0, 179))
        add("receive", phone("0180000", RNG.randint(1, 50)), RNG.choice([5000, 8000, 10000, 12000]), when)
    # one genuine "sent by mistake" from a contact, so returning it is legitimate
    if user["id"] == "u2":
        add("receive", user["contacts"][3]["phone"], 1000, NOW - timedelta(hours=3))
    return sorted(tx, key=lambda t: t["ts"])


def main() -> None:
    users = []
    txs = []
    for u in USERS:
        u = dict(u)
        u["contacts"] = [{k: v for k, v in c.items() if k not in ("usual", "freq")}
                         for c in u["contacts"]]
        users.append(u)
        txs.extend(history(next(x for x in USERS if x["id"] == u["id"])))
    out = {"generated_at": NOW.isoformat(), "demo_pin": "1234",
           "note": "Synthetic data. No real customers, numbers or transactions.",
           "users": users, "transactions": txs}
    path = ROOT / "data" / "seed.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {path} : {len(users)} users, {len(txs)} transactions")


if __name__ == "__main__":
    main()
