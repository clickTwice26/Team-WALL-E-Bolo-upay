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
    """True if a negation follows the phrase within 3 tokens of the same answer:
    a negation word ("na", "nai", "না") or a Bangla verb with the negative
    suffix -নি ("চায়নি", "করেনি", "দেয়নি")."""
    after = text[idx + len(phrase):].split()[:3]
    return any(w in NEGATIONS or (len(w) > 3 and w.endswith("নি")) for w in after)


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
                # tolerate speech-recognition spelling errors in longer phrases,
                # with the same negation check as an exact match
                al = fuzz.partial_ratio_alignment(phrase, t)
                if (al is not None and al.score >= 90 and (best is None or al.score > best[1])
                        and not _negated(t, al.dest_start, t[al.dest_start:al.dest_end])):
                    best = (phrase, al.score)
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


def match_many(texts: list[str]) -> dict:
    """Match each utterance separately (so "no" in one answer cannot cancel a
    scam phrase in another) and merge the hits."""
    hits: dict[str, dict] = {}
    for t in texts:
        if not t or not t.strip():
            continue
        for h in match(t)["hits"]:
            hits.setdefault(h["category"], h)
    merged = list(hits.values())
    weights = lexicon()["levels"]
    score = 0.0
    if merged:
        score = min(1.0, max(weights[h["level"]] for h in merged) + 0.15 * (len(merged) - 1))
    return {"score": round(score, 3), "hits": merged}
