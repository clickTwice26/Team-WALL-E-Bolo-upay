"""Scam phrase matcher.

The app never listens to phone calls. These phrases are matched against what
the *user* says: the original command and their answers to the scam
interview questions ("Did someone call you?").
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz

from .text import nfc, normalize

DATA = Path(__file__).resolve().parents[3] / "data" / "scam_phrases.json"

# Spoken answers that clearly deny a scam signal. They stop "otp" in
# "keu otp chay nai" (nobody asked for an OTP) from triggering.
NEGATIONS = ("nai", "nei", "na", "নাই", "নেই", "না", "no", "not", "didn't",
             "didnt", "never")


@lru_cache(maxsize=1)
def lexicon() -> dict:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    for cat in data["categories"]:
        phrases = []
        for lang, items in cat["phrases"].items():
            for p in items:
                phrases.append((normalize(p), lang))
        cat["_norm"] = sorted(set(phrases), key=lambda x: -len(x[0]))
    return data


def _negated(text: str, idx: int, phrase: str) -> bool:
    """True if a negation word follows the phrase within 3 tokens."""
    after = text[idx + len(phrase):].split()[:3]
    return any(w in NEGATIONS for w in after)


def match(text: str) -> dict:
    """Return matched categories, phrases and a 0..1 score."""
    data = lexicon()
    t = normalize(nfc(text or ""))
    hits = []
    for cat in data["categories"]:
        best = None
        for phrase, lang in cat["_norm"]:
            idx = t.find(phrase)
            if idx >= 0:
                # whole-word check for short Latin phrases like "otp"
                left_ok = idx == 0 or not t[idx - 1].isalnum()
                right = idx + len(phrase)
                right_ok = right == len(t) or not t[right].isalnum() or lang == "bn"
                if left_ok and right_ok and not _negated(t, idx, phrase):
                    best = (phrase, 100.0)
                    break
            elif len(phrase) >= 8:
                # tolerate speech-recognition spelling errors in longer phrases
                score = fuzz.partial_ratio(phrase, t)
                if score >= 90 and (best is None or score > best[1]):
                    best = (phrase, score)
        if best:
            hits.append({
                "category": cat["id"],
                "level": cat["level"],
                "phrase": best[0],
                "explain_bn": cat["explain_bn"],
                "explain_en": cat["explain_en"],
                "escalate_if": cat.get("escalate_if"),
            })
    weights = data["levels"]
    score = 0.0
    if hits:
        score = max(weights[h["level"]] for h in hits)
        score = min(1.0, score + 0.15 * (len(hits) - 1))
    return {"score": round(score, 3), "hits": hits}
