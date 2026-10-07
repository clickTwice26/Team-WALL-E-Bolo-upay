"""Synthetic wallet timelines for training the risk model.

No real fraud data exists for a hackathon, so we simulate it, and we simulate
whole timelines rather than single rows: each synthetic user gets six months
of ordinary wallet life (family, shops, recharges, salary, cash-outs), then a
month of decision events, the payments the risk model has to score. Most are
honest, some are scams. Each event's features are computed by
api/app/core/features.py from the history up to that moment, the same code
that serves requests, so training and serving cannot drift apart. Every
event joins the history afterwards, so later events see earlier ones
(bursts, new recipients, money passed on).

Scam types follow common Bangladeshi MFS fraud: fake upay staff, PIN/OTP
requests, lottery and allowance fees, job/loan fees, a relative in trouble,
"sent by mistake, send it back", money mules and account takeover.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.core import features, scam
from app.core.features import TZ

START = datetime(2026, 3, 1, tzinfo=TZ)        # history begins
WINDOW = START + timedelta(days=180)           # decision events from here...
WINDOW_DAYS = 30                               # ...for a month

LEGIT_ANSWERS = [
    "na, keu phone kore nai", "ami nijei pathacchi", "ammu chaise tai pathacchi",
    "bari bhara dicchi", "dokaner baki shodh korchi", "না, কেউ ফোন করেনি",
    "আমি নিজেই পাঠাচ্ছি", "বাসা ভাড়া দিচ্ছি", "ammu phone kore bolse bazar er taka lagbe",
    "bhai phone dise, boi kinbe", "keu otp chay nai", "কেউ পিন চায়নি",
    "taratari pathate hobe, bazar korbo", "new landlord ke advance dicchi",
    "notun dokaner malik ke dam dicchi", "friend er birthday gift", "mess er taka",
    "bondhura mile picnic er taka tulsi", "keu commission dibe na, nijer kaj",
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
    "allowance": ["sorkari vata pabo, processing fee lagbe", "উপবৃত্তির টাকা পেতে প্রসেসিং ফি"],
    "job_loan": ["chakrir jonno registration fee", "loan pete age taka din bolse", "double taka hobe bolse"],
    "relative": ["bhai bolse accident hoyeche, notun number theke bolchi", "বিপদে পড়েছি, নতুন নম্বর থেকে বলছি",
                 "police e dhoreche bolse, ekhoni pathan"],
    "sent_by_mistake": ["bolse vul kore taka pathiyeche, ferot din", "ভুল করে টাকা চলে গেছে বলছে, ফেরত দিন",
                        "takata ferot pathan bolse"],
    "mule": ["commission pabo bolse, onno number e pathate hobe", "অনলাইনে কাজ, কমিশন দেবে বলেছে",
             "bolse taka ta forward korte, commission pabo"],
    "takeover": [],  # the attacker answers the questions
}
DEFLECT = ["na emni", "ami nijei", "kichu na", "জানি না", "no, nothing", "family r jonno"]

LEGIT_KINDS = {  # kind: weight
    "known": 42, "known_big": 6, "new_legit": 14, "recharge": 12, "shop_burst": 5,
    "refund": 4, "cash_out": 7, "merchant": 7, "late_legit": 2, "pooled": 1,
}
SCAM_KINDS = {
    "fake_official": 16, "pin_otp": 10, "lottery": 9, "allowance": 6, "job_loan": 8,
    "relative": 12, "sent_by_mistake": 10, "mule": 12, "takeover": 15,
}
ON_CALL = {"fake_official": .75, "pin_otp": .75, "lottery": .7, "allowance": .7, "job_loan": .35,
           "relative": .55, "sent_by_mistake": .5, "mule": .15, "takeover": 0.0}


@dataclass
class User:
    uid: str
    phone: str
    median: float          # typical payment size (Tk)
    center: float          # hour of day this user usually pays
    balance: float         # typical balance
    contacts: list[dict]
    shops: list[str]
    agents: list[str]
    merchants: list[str]
    employer: str
    history: list[dict] = field(default_factory=list)


class Sim:
    def __init__(self, seed: int = 7):
        self.rng = random.Random(seed)
        self._used: set[str] = set()
        self._n = 0

    # ---------------------------------------------------------------- helpers
    def number(self, prefix: str | None = None) -> str:
        while True:
            p = prefix or self.rng.choice(["013", "014", "015", "016", "017", "018", "019"])
            n = f"{p}{self.rng.randrange(10 ** 8):08d}"
            if n not in self._used:
                self._used.add(n)
                return n

    def ln(self, mu: float, sigma: float) -> float:
        return math.exp(self.rng.gauss(mu, sigma))

    def at(self, day: datetime, hour: float) -> datetime:
        h = min(max(hour, 0.0), 23.98)
        return day.replace(hour=int(h), minute=int((h % 1) * 60), second=self.rng.randrange(60))

    def usual_hour(self, u: User) -> float:
        return min(max(self.rng.gauss(u.center, 2.2), 6.5), 23.3)

    def add(self, u: User, kind: str, who: str | None, amount: float, ts: datetime) -> dict:
        self._n += 1
        t = {"id": f"{u.uid}-{self._n}", "user_id": u.uid, "type": kind, "counterparty": who,
             "amount": round(float(amount)), "ts": ts.isoformat()}
        u.history.append(t)
        return t

    # ---------------------------------------------------------------- users
    def user(self, i: int) -> User:
        r = self.rng
        median = self.ln(math.log(900), 0.55)
        contacts = [{"id": f"c{k}", "phone": self.number(), "usual": median * self.ln(0, 0.5),
                     "weight": r.random() + 0.2} for k in range(r.randint(3, 8))]
        u = User(uid=f"s{i}", phone=self.number("017"), median=median, center=r.uniform(9, 20),
                 balance=median * self.ln(math.log(8), 0.5), contacts=contacts,
                 shops=[self.number() for _ in range(r.randint(1, 4))],
                 agents=[self.number("016") for _ in range(r.randint(1, 2))],
                 merchants=[self.number("018") for _ in range(r.randint(1, 3))],
                 employer=self.number())
        self.history(u)
        return u

    def history(self, u: User) -> None:
        """Six months of ordinary wallet life before the decision window."""
        r = self.rng
        day = lambda: START + timedelta(days=r.randrange(180))  # noqa: E731
        for _ in range(int(r.uniform(1, 4) * 26)):
            d = day()
            if r.random() < 0.85:
                c = r.choices(u.contacts, weights=[c["weight"] for c in u.contacts])[0]
                self.add(u, "send_money", c["phone"], c["usual"] * self.ln(0, 0.35), self.at(d, self.usual_hour(u)))
            else:
                self.add(u, "send_money", r.choice(u.shops), u.median * self.ln(-0.3, 0.5),
                         self.at(d, self.usual_hour(u)))
        for _ in range(int(26 * r.uniform(0.4, 1.2))):
            self.add(u, "mobile_recharge", u.phone, r.choice([20, 30, 50, 100, 200, 300]),
                     self.at(day(), self.usual_hour(u)))
        for m in range(6):
            pay = START + timedelta(days=30 * m + r.randrange(1, 5))
            self.add(u, "receive", u.employer, u.median * r.uniform(8, 20), self.at(pay, r.uniform(10, 17)))
            if r.random() < 0.6:
                self.add(u, "cash_out", r.choice(u.agents), u.median * r.uniform(1.5, 6),
                         self.at(pay + timedelta(days=r.randrange(1, 4)), r.uniform(10, 20)))
            if r.random() < 0.3:
                c = r.choice(u.contacts)
                self.add(u, "receive", c["phone"], c["usual"] * self.ln(0, 0.4), self.at(day(), r.uniform(9, 21)))
        for _ in range(r.randint(3, 18)):
            self.add(u, "merchant_payment", r.choice(u.merchants), u.median * self.ln(-0.5, 0.5),
                     self.at(day(), self.usual_hour(u)))

    # ---------------------------------------------------------------- events
    def balance_for(self, u: User, amount: float) -> float:
        b = u.balance * self.ln(0, 0.3)
        return b if b >= amount * 1.02 else amount * self.rng.uniform(1.05, 1.6)

    def answer(self, kind: str, scam_kind: bool) -> str:
        r = self.rng
        if not scam_kind:
            return r.choice(LEGIT_ANSWERS)
        options = SCAM_ANSWERS[kind]
        reveal = {"mule": 0.35}.get(kind, 0.72)
        return r.choice(options) if options and r.random() < reveal else r.choice(DEFLECT)

    def event(self, u: User, ts: datetime, kind: str, label: int, intent: str, phone: str,
              amount: float, on_call: bool, return_claim: bool = False, balance: float | None = None) -> dict:
        """Score one payment: features from the history so far, then it joins the history."""
        balance = balance if balance is not None else self.balance_for(u, amount)
        # the last 20 transactions before this one, for sequence models (ml/compare_sequence.py)
        recent = sorted((t for t in u.history if t["ts"] <= ts.isoformat()), key=lambda t: t["ts"])[-20:]
        answer = self.answer(kind, label == 1)
        sc = scam.match(answer)
        feats, _ = features.compute(amount=amount, intent=intent, phone=phone, is_return_claim=return_claim,
                                    balance=balance, history=u.history, contacts=u.contacts,
                                    on_call=on_call, scam_score=sc["score"], now=ts, self_phone=u.phone)
        self.add(u, intent, phone, amount, ts)
        return {"user": u.uid, "ts": ts, "label": label, "kind": kind, "intent": intent,
                "amount": round(float(amount)), "feats": feats, "answer": answer, "hits": sc["hits"],
                "phone": phone, "contacts": {c["phone"] for c in u.contacts}, "median": u.median,
                "recent": [dict(t) for t in recent]}

    def legit(self, u: User, d: datetime) -> list[dict]:
        r = self.rng
        kind = r.choices(list(LEGIT_KINDS), weights=list(LEGIT_KINDS.values()))[0]
        ts = self.at(d, self.usual_hour(u))
        call = lambda p: r.random() < p  # noqa: E731
        if kind in ("known", "known_big", "late_legit"):
            c = r.choices(u.contacts, weights=[c["weight"] for c in u.contacts])[0]
            amt = c["usual"] * (self.ln(0, 0.35) if kind != "known_big" else r.uniform(2.5, 5))
            if kind == "late_legit":
                ts = self.at(d, r.uniform(0, 4.5))
            return [self.event(u, ts, kind, 0, "send_money", c["phone"], amt, call(0.15 if kind == "known" else 0.25))]
        if kind == "new_legit":
            return [self.event(u, ts, kind, 0, "send_money", self.number(), u.median * self.ln(0.25, 0.85), call(0.25))]
        if kind == "recharge":
            return [self.event(u, ts, kind, 0, "mobile_recharge", u.phone, r.choice([20, 50, 100, 200, 500]), call(0.05))]
        if kind == "shop_burst":
            out = []
            for k in range(r.randint(2, 3)):
                out.append(self.event(u, ts + timedelta(minutes=7 * k), kind, 0, "send_money",
                                      r.choice(u.shops), u.median * self.ln(-0.4, 0.5), False))
            return out
        if kind == "refund":  # money really came from this number; sending it back is honest
            x, amt = self.number(), u.median * r.uniform(0.5, 4)
            self.add(u, "receive", x, amt, ts - timedelta(hours=r.uniform(1, 72)))
            return [self.event(u, ts, kind, 0, "send_money", x, amt, call(0.4), return_claim=True)]
        if kind == "cash_out":
            agent = r.choice(u.agents) if r.random() < 0.85 else self.number("016")
            return [self.event(u, self.at(d, r.uniform(10, 20)), kind, 0, "cash_out", agent,
                               u.median * r.uniform(1.5, 6), False)]
        if kind == "merchant":
            m = r.choice(u.merchants) if r.random() < 0.7 else self.number("018")
            return [self.event(u, ts, kind, 0, "merchant_payment", m, u.median * self.ln(-0.5, 0.5), False)]
        # pooled: friends chip in, and the money goes on to the venue (looks like a mule)
        friend, amt = self.number(), u.median * r.uniform(3, 8)
        self.add(u, "receive", friend, amt, ts - timedelta(minutes=r.uniform(20, 100)))
        return [self.event(u, ts, kind, 0, "send_money", self.number(), amt * r.uniform(0.5, 0.95), call(0.2))]

    def scam(self, u: User, d: datetime) -> list[dict]:
        r = self.rng
        kind = r.choices(list(SCAM_KINDS), weights=list(SCAM_KINDS.values()))[0]
        night = r.random() < 0.12
        ts = self.at(d, r.uniform(0, 5) if night else self.usual_hour(u))
        on_call = r.random() < ON_CALL[kind]
        if kind == "takeover":  # someone else holds the phone: odd hour, drain the balance
            ts = self.at(d, (u.center + r.uniform(8, 14)) % 24)
            to, out = self.number(), []
            bal = u.balance * self.ln(0, 0.3)
            for k in range(1 if r.random() < 0.5 else r.randint(2, 3)):
                amt = bal * r.uniform(0.6, 0.97) if k == 0 else bal * r.uniform(0.5, 0.95)
                out.append(self.event(u, ts + timedelta(minutes=4 * k), kind, 1, "send_money", to if k == 0 else self.number(),
                                      amt, False, balance=bal))
                bal = max(bal - amt, amt * 1.05)
            return out
        if kind == "mule":  # a stranger's money arrives, and the user is told to pass it on
            x, amt = self.number(), u.median * r.uniform(5, 20)
            self.add(u, "receive", x, amt, ts - timedelta(minutes=r.uniform(10, 110)))
            return [self.event(u, ts, kind, 1, "send_money", self.number(), amt * r.uniform(0.5, 0.95), on_call)]
        if kind == "sent_by_mistake":  # a fake "sent by mistake" SMS: no money ever came
            return [self.event(u, ts, kind, 1, "send_money", self.number(), u.median * r.uniform(1, 5), on_call,
                               return_claim=True)]
        to = self.number() if (kind == "relative" or r.random() < 0.9) else r.choice(u.contacts)["phone"]
        out = [self.event(u, ts, kind, 1, "send_money", to, u.median * self.ln(0.9, 0.8), on_call)]
        if kind in ("fake_official", "pin_otp", "lottery", "allowance") and r.random() < 0.3:
            # "it didn't go through, send it again"
            out.append(self.event(u, ts + timedelta(minutes=r.uniform(4, 15)), kind, 1, "send_money", to,
                                  u.median * self.ln(0.7, 0.6), on_call))
        return out


def generate(n_users: int = 650, scam_share: float = 0.24, seed: int = 7) -> list[dict]:
    """Decision events of ``n_users`` synthetic users, in time order."""
    sim = Sim(seed)
    events = []
    for i in range(n_users):
        u = sim.user(i)
        days = sorted(WINDOW + timedelta(days=sim.rng.uniform(0, WINDOW_DAYS)) for _ in range(sim.rng.randint(10, 16)))
        for d in days:
            d = d.replace(hour=0, minute=0, second=0, microsecond=0)
            events += sim.scam(u, d) if sim.rng.random() < scam_share else sim.legit(u, d)
    return sorted(events, key=lambda e: e["ts"])
