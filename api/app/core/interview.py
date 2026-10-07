"""Adaptive scam interview: which question to ask next.

The first question follows the strongest risk signal of this payment (a
"send it back" claim, a stranger's money being passed on, an active call, an
unusual hour, a cash-out, a new recipient). Each follow-up follows what the
last answers revealed (fake staff -> ask about the OTP; a relative in trouble
-> did you call their old number). The interview stops early once an answer
already settles it (a high-level scam phrase makes the transfer RED) and
never asks more than ``max_questions``. Questions live in data/interview.json.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import scam

DATA = Path(__file__).resolve().parents[3] / "data" / "interview.json"


@lru_cache(maxsize=1)
def bank() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def question(qid: str) -> dict:
    return {"id": qid, **bank()["questions"][qid]}


def first(feats: dict, draft: dict) -> dict:
    facts = {**feats, "is_return_claim": int(bool(draft.get("is_return_claim")))}
    for rule in bank()["first"]:
        if facts.get(rule["if"]):
            return question(rule["ask"])
    return question(bank()["fill"][0])


def next_question(asked: list[str], answers: list[str]) -> dict | None:
    """The next question, or None when the interview is done."""
    b = bank()
    if len(asked) >= b["max_questions"] or len(answers) < len(asked):
        return None
    hits = scam.match_many(answers)["hits"]
    if any(h["level"] == "high" for h in hits):
        return None  # the answers already settle it (a hard rule makes it RED)
    for h in hits:
        qid = b["follow_up"].get(h["category"])
        if qid and qid not in asked:
            return question(qid)
    for qid in b["fill"]:
        if qid not in asked:
            return question(qid)
    return None
