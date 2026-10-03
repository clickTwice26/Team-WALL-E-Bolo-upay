"""Deterministic amount parser for Bangla, Banglish and English.

This is the rule-based half of the "two independent paths" design: the LLM
and this parser must agree on the amount, otherwise the app asks the user.

Handles: 500, ৫০০, 1,500, 5k, 1.5k, পাঁচশো, দেড় হাজার, আড়াইশো, সাড়ে তিন হাজার,
পৌনে দুই হাজার, এক লাখ বিশ হাজার, pach hazar, der hajar, sare tin hajar,
two thousand five hundred ...
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .text import nfc

_BN_WORDS = {
    "এক": 1, "দুই": 2, "দুই": 2, "দু": 2, "তিন": 3, "চার": 4, "পাঁচ": 5,
    "ছয়": 6, "ছয়": 6, "ছ": 6, "সাত": 7, "আট": 8, "নয়": 9, "নয়": 9, "দশ": 10,
    "এগারো": 11, "এগার": 11, "বারো": 12, "বার": 12, "তেরো": 13, "তের": 13,
    "চৌদ্দ": 14, "পনেরো": 15, "পনের": 15, "ষোলো": 16, "ষোল": 16,
    "সতেরো": 17, "সতের": 17, "আঠারো": 18, "আঠার": 18, "উনিশ": 19,
    "বিশ": 20, "কুড়ি": 20, "একুশ": 21, "বাইশ": 22, "তেইশ": 23, "চব্বিশ": 24,
    "পঁচিশ": 25, "ছাব্বিশ": 26, "সাতাশ": 27, "আঠাশ": 28, "উনত্রিশ": 29,
    "ঊনত্রিশ": 29, "ত্রিশ": 30, "তিরিশ": 30, "একত্রিশ": 31, "বত্রিশ": 32,
    "তেত্রিশ": 33, "চৌত্রিশ": 34, "পঁয়ত্রিশ": 35, "ছত্রিশ": 36,
    "সাঁইত্রিশ": 37, "আটত্রিশ": 38, "উনচল্লিশ": 39, "ঊনচল্লিশ": 39,
    "চল্লিশ": 40, "একচল্লিশ": 41, "বিয়াল্লিশ": 42, "তেতাল্লিশ": 43,
    "চুয়াল্লিশ": 44, "পঁয়তাল্লিশ": 45, "ছেচল্লিশ": 46, "সাতচল্লিশ": 47,
    "আটচল্লিশ": 48, "উনপঞ্চাশ": 49, "ঊনপঞ্চাশ": 49, "পঞ্চাশ": 50,
    "একান্ন": 51, "বাহান্ন": 52, "বায়ান্ন": 52, "তিপ্পান্ন": 53,
    "চুয়ান্ন": 54, "পঞ্চান্ন": 55, "ছাপ্পান্ন": 56, "সাতান্ন": 57,
    "আটান্ন": 58, "উনষাট": 59, "ঊনষাট": 59, "ষাট": 60, "একষট্টি": 61,
    "বাষট্টি": 62, "তেষট্টি": 63, "চৌষট্টি": 64, "পঁয়ষট্টি": 65,
    "ছেষট্টি": 66, "সাতষট্টি": 67, "আটষট্টি": 68, "উনসত্তর": 69,
    "ঊনসত্তর": 69, "সত্তর": 70, "একাত্তর": 71, "বাহাত্তর": 72,
    "তিয়াত্তর": 73, "চুয়াত্তর": 74, "পঁচাত্তর": 75, "ছিয়াত্তর": 76,
    "সাতাত্তর": 77, "আটাত্তর": 78, "উনআশি": 79, "ঊনআশি": 79, "আশি": 80,
    "একাশি": 81, "বিরাশি": 82, "তিরাশি": 83, "চুরাশি": 84, "পঁচাশি": 85,
    "ছিয়াশি": 86, "সাতাশি": 87, "আটাশি": 88, "উননব্বই": 89, "ঊননব্বই": 89,
    "নব্বই": 90, "একানব্বই": 91, "বিরানব্বই": 92, "তিরানব্বই": 93,
    "চুরানব্বই": 94, "পঁচানব্বই": 95, "ছিয়ানব্বই": 96, "সাতানব্বই": 97,
    "আটানব্বই": 98, "নিরানব্বই": 99,
}
_LATIN_WORDS = {
    # Banglish
    "ek": 1, "dui": 2, "du": 2, "tin": 3, "teen": 3, "char": 4, "chaar": 4,
    "pach": 5, "panch": 5, "paanch": 5, "pas": 5, "choy": 6, "chhoy": 6,
    "choi": 6, "sat": 7, "saat": 7, "aat": 8, "aath": 8, "noy": 9, "noi": 9,
    "dosh": 10, "dos": 10, "egaro": 11, "baro": 12, "tero": 13, "choddo": 14,
    "chouddo": 14, "ponero": 15, "sholo": 16, "sotero": 17, "atharo": 18,
    "unish": 19, "bish": 20, "kuri": 20, "pochish": 25, "ponchish": 25,
    "trish": 30, "tirish": 30, "chollish": 40, "ponchash": 50,
    "panchash": 50, "shat": 60, "shaat": 60, "sottor": 70, "ashi": 80,
    "nobboi": 90,
    # English
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_FRACTIONS = {"দেড়": 1.5, "আড়াই": 2.5, "der": 1.5, "dedh": 1.5, "deer": 1.5,
              "arai": 2.5, "arrai": 2.5, "adai": 2.5}
_MODIFIERS = {"সাড়ে": 0.5, "পৌনে": -0.25, "সোয়া": 0.25, "sare": 0.5,
              "share": 0.5, "saare": 0.5, "poune": -0.25, "soa": 0.25,
              "soya": 0.25}
_HUNDRED = {"শো", "শ", "শত", "sho", "shoto", "hundred"}
_BIG = {"হাজার": 1000, "লাখ": 100000, "লক্ষ": 100000, "কোটি": 10_000_000,
        "hajar": 1000, "hazar": 1000, "hajaar": 1000, "hazaar": 1000,
        "thousand": 1000, "lakh": 100000, "lac": 100000,
        "lakhs": 100000, "koti": 10_000_000, "crore": 10_000_000}
CURRENCY = {"taka", "tk", "টাকা", "টাকার", "takar", "tka"}

_BN_WORDS = {nfc(k): v for k, v in _BN_WORDS.items()}
_FRACTIONS = {nfc(k): v for k, v in _FRACTIONS.items()}
_MODIFIERS = {nfc(k): v for k, v in _MODIFIERS.items()}
_HUNDRED = {nfc(k) for k in _HUNDRED}
_BIG = {nfc(k): v for k, v in _BIG.items()}
CURRENCY = {nfc(k) for k in CURRENCY}

# "so" only counts as "hundred" when glued to a number word ("pachso"):
# on its own it is far more likely to be the English word "so".
_COMPOUND_SUFFIXES = sorted(list(_HUNDRED) + ["so"], key=len, reverse=True)


def _is_bangla(s: str) -> bool:
    return any("ঀ" <= ch <= "৿" for ch in s)


def _classify(tok: str):
    """Return a list of (kind, value) parts for one token, or None."""
    if tok in _BN_WORDS:
        return [("num", _BN_WORDS[tok], "bn")]
    if tok in _LATIN_WORDS:
        return [("num", _LATIN_WORDS[tok], "latin")]
    if tok in _FRACTIONS:
        return [("num", _FRACTIONS[tok], "bn" if _is_bangla(tok) else "latin")]
    if tok in _MODIFIERS:
        return [("mod", _MODIFIERS[tok], "bn" if _is_bangla(tok) else "latin")]
    if tok in _HUNDRED:
        return [("mul", 100, "x")]
    if tok in _BIG:
        return [("mul", _BIG[tok], "x")]
    try:
        return [("digit", float(tok), "digit")]
    except ValueError:
        pass
    # compounds: "পাঁচশো", "দেড়শো", "pachsho", "duisho"
    for suf in _COMPOUND_SUFFIXES:
        if tok.endswith(suf) and len(tok) > len(suf):
            head = _classify(tok[: -len(suf)])
            if head and head[-1][0] == "num":
                return head + [("mul", 100, "x")]
    return None


@dataclass
class Span:
    value: float
    start: int
    end: int
    has_mul: bool = False
    has_digit: bool = False
    scripts: set = field(default_factory=set)
    near_currency: bool = False

    @property
    def reliable(self) -> bool:
        """Latin number words alone ("ek", "at") are too ambiguous to trust."""
        if self.has_digit or self.has_mul or self.near_currency:
            return True
        return "bn" in self.scripts and self.value >= 10


def find_spans(toks: list[str]) -> list[Span]:
    spans: list[Span] = []
    i = 0
    while i < len(toks):
        parts = _classify(toks[i])
        if not parts:
            i += 1
            continue
        start = i
        total, current, pending = 0.0, None, 0.0
        has_mul = has_digit = False
        scripts: set = set()
        last_kind = None
        while i < len(toks):
            parts = _classify(toks[i])
            if not parts:
                break
            # two bare digit groups in a row ("500 1000") are separate amounts
            if parts[0][0] == "digit" and last_kind == "digit":
                break
            for kind, val, script in parts:
                scripts.add(script)
                if kind == "mod":
                    pending += val
                elif kind in ("num", "digit"):
                    has_digit |= kind == "digit"
                    current = (current or 0.0) + val + pending
                    pending = 0.0
                elif kind == "mul":
                    has_mul = True
                    if val == 100:
                        current = (current if current is not None else 1.0) * 100
                    else:
                        total += (current if current is not None else 1.0) * val
                        current = None
                last_kind = kind
            i += 1
        value = total + (current or 0.0)
        if value > 0:
            near = (i < len(toks) and toks[i] in CURRENCY) or (
                start > 0 and toks[start - 1] in CURRENCY)
            spans.append(Span(value, start, i, has_mul, has_digit, scripts, near))
    return spans


def parse_amount(toks: list[str]) -> dict:
    """Pick the transaction amount from tokens.

    Returns {"amount": int|None, "candidates": [int], "ambiguous": bool}.
    Never guesses: two different plausible amounts -> ambiguous.
    """
    spans = [s for s in find_spans(toks) if s.reliable]
    if not spans:
        return {"amount": None, "candidates": [], "ambiguous": False}
    near = [s for s in spans if s.near_currency]
    pool = near if len(near) == 1 else spans
    values = sorted({round(s.value, 2) for s in pool})
    whole = [v for v in values if float(v).is_integer()]
    if len(values) == 1 and whole:
        return {"amount": int(values[0]), "candidates": [int(values[0])],
                "ambiguous": False}
    cands = [int(v) for v in whole] or [int(round(v)) for v in values]
    return {"amount": None, "candidates": cands, "ambiguous": True}


def is_number_token(tok: str) -> bool:
    return _classify(tok) is not None or tok in CURRENCY
