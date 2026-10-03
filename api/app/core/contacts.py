"""Recipient resolution: "Rahim bhai" / "আম্মুকে" / "01712345678" -> contact.

Exact alias matches are trusted. Fuzzy matches (speech-recognition spelling
errors such as "rohim") are returned with match="fuzzy" so the UI always asks
"Did you mean ...?". Two contacts matching the same words -> ambiguous, the
user picks. Money never goes to a guessed person.
"""
from __future__ import annotations

from rapidfuzz import fuzz

from .numbers import is_number_token
from .text import nfc, normalize

# Case markers glued to names: আম্মুকে, rahimke, রহিমের, karim-re ...
SUFFIXES = sorted(["কে", "রে", "এর", "ের", "র", "ে", "তে", "য়ে", "কেও",
                   "ke", "k", "re", "er", "r", "ko", "ki", "e", "te"],
                  key=len, reverse=True)
SUFFIXES = [nfc(x) for x in SUFFIXES]

STOPWORDS = {
    "taka", "tk", "টাকা", "pathao", "pathan", "pathai", "পাঠাও", "পাঠান",
    "পাঠাই", "send", "dao", "দাও", "den", "দেন", "recharge", "রিচার্জ",
    "kore", "করে", "koro", "করো", "amar", "আমার", "ke", "কে", "e", "এ", "te",
    "তে", "to", "the", "please", "plz", "একটু", "ektu", "number", "নম্বর",
    "নাম্বার", "nombor", "nombore", "নম্বরে", "<phone>", "ferot", "ফেরত",
    "mobile", "মোবাইল", "balance", "ব্যালেন্স",
}


def _bases(tok: str) -> set[str]:
    out = {tok}
    for suf in SUFFIXES:
        if tok.endswith(suf) and len(tok) - len(suf) >= 2:
            out.add(nfc(tok[: -len(suf)]))
    return out


def _alias_index(contacts: list[dict]) -> list[tuple[str, dict]]:
    idx = []
    for c in contacts:
        for a in [c["name"], *c.get("aliases", [])]:
            idx.append((normalize(a), c))
    return idx


def resolve(text_tokens: list[str], phones: list[str], contacts: list[dict],
            self_phone: str | None = None) -> dict:
    """Return {"status": found|ambiguous|new_number|none, ...}."""
    by_phone = {c["phone"]: c for c in contacts}
    if phones:
        if len(set(phones)) > 1:
            return {"status": "ambiguous", "candidates": [
                by_phone.get(p, {"name": None, "phone": p}) for p in dict.fromkeys(phones)]}
        p = phones[0]
        if p in by_phone:
            return {"status": "found", "contact": by_phone[p], "match": "phone"}
        if self_phone and p == self_phone:
            return {"status": "self", "phone": p}
        return {"status": "new_number", "phone": p}

    words = [t for t in text_tokens if t not in STOPWORDS and not is_number_token(t)]
    grams: list[set[str]] = []
    for i, w in enumerate(words):
        grams.append(_bases(w))
        if i + 1 < len(words):
            grams.append({f"{w} {b}" for b in _bases(words[i + 1])} | {
                f"{a} {words[i + 1]}" for a in _bases(w)})
    index = _alias_index(contacts)

    # exact matches; the longest matching alias wins ("rahim bhai" beats a
    # plain "rahim" that two contacts share)
    exact: dict[str, tuple[int, dict]] = {}
    for alias, c in index:
        for g in grams:
            if alias in g and len(alias) > exact.get(c["id"], (0, None))[0]:
                exact[c["id"]] = (len(alias), c)
    if exact:
        top = max(n for n, _ in exact.values())
        best = [c for n, c in exact.values() if n == top]
        if len(best) == 1:
            return {"status": "found", "contact": best[0], "match": "exact"}
        return {"status": "ambiguous", "candidates": best}

    fuzzy: dict[str, tuple[float, dict]] = {}
    for alias, c in index:
        if len(alias) < 4:
            continue
        for g in grams:
            for cand in g:
                if len(cand) < 4:
                    continue
                s = fuzz.ratio(alias, cand)
                if s >= 85 and s > fuzzy.get(c["id"], (0, None))[0]:
                    fuzzy[c["id"]] = (s, c)
    if len(fuzzy) == 1:
        return {"status": "found", "contact": next(iter(fuzzy.values()))[1], "match": "fuzzy"}
    if len(fuzzy) > 1:
        ranked = sorted(fuzzy.values(), key=lambda x: -x[0])
        return {"status": "ambiguous", "candidates": [c for _, c in ranked]}
    return {"status": "none"}
