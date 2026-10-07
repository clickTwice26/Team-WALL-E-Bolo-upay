"""Spoken PIN / OTP detector, shared by the agent and the human-handoff chat.

"amar pin 1234" or "OTP holo ৪৮২১৯৩" must never be acted on, stored or shown
to staff. A 4-6 digit number near a PIN/OTP/password/code word counts, unless
it is an amount ("pin lagbe na, 2000 taka pathao").
"""
from __future__ import annotations

import re

from .numbers import CURRENCY
from .text import normalize

SECRET_WORDS = tuple(normalize(w) for w in (
    "pin", "পিন", "otp", "ওটিপি", "password", "পাসওয়ার্ড", "passcode", "পাসকোড", "code", "কোড"))
WINDOW = 4  # tokens between the word and the number

_DIGITS = "0-9০-৯"
# a 4-6 digit group, or digits said one by one ("1 2 3 4"), not part of a phone number
_SECRET_NUM = re.compile(
    rf"(?<![{_DIGITS}])(?:[{_DIGITS}]{{4,6}}|(?:[{_DIGITS}][\s-]){{3,5}}[{_DIGITS}])(?![{_DIGITS}])")
_AMOUNT_AFTER = re.compile(r"^\s*(?:taka|tk|টাকা|৳)", re.IGNORECASE)


def _is_secret_word(tok: str) -> bool:
    # prefix match: Bangla glues suffixes on ("পিনটা", "কোডটা")
    return any(tok.startswith(w) for w in SECRET_WORDS)


def _tokens(text: str) -> list[str]:
    """Normalised tokens with digits said one by one joined ("1 2 3 4" -> "1234")."""
    out: list[str] = []
    run = False
    for tok in normalize(text).split():
        single = tok.isdigit() and len(tok) == 1
        if single and run:
            out[-1] += tok
        else:
            out.append(tok)
        run = single
    return out


def contains_secret(text: str) -> bool:
    toks = _tokens(text)
    words = [i for i, t in enumerate(toks) if _is_secret_word(t)]
    if not words:
        return False
    for i, t in enumerate(toks):
        if not (t.isdigit() and 4 <= len(t) <= 6):
            continue
        amount = (i + 1 < len(toks) and toks[i + 1] in CURRENCY) or (i > 0 and toks[i - 1] in CURRENCY)
        if not amount and any(abs(i - w) <= WINDOW for w in words):
            return True
    return False


def mask(text: str) -> str:
    """Replace the PIN/OTP digits with ••••, leaving amounts and phone numbers."""
    if not contains_secret(text):
        return text

    def _sub(m: re.Match) -> str:
        if _AMOUNT_AFTER.match(text[m.end():]) or text[:m.start()].rstrip().endswith("৳"):
            return m.group(0)
        return "••••"
    return _SECRET_NUM.sub(_sub, text)
