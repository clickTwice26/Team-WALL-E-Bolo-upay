"""Text normalisation shared by every parser.

Voice transcripts arrive in Bangla script, Banglish (Bangla in Latin letters)
or English, often mixed. Everything downstream works on the output of
``normalize`` so that the same command spoken different ways looks the same.
"""
from __future__ import annotations

import re
import unicodedata

BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

# Phone numbers in Bangladesh: 01[3-9] followed by 8 digits, optionally
# prefixed with +88 / 88, optionally spoken with spaces or dashes in between.
PHONE_RE = re.compile(r"(?<!\d)(?:\+?88[\s-]?)?(0\s*1\s*[3-9](?:[\s-]*\d){8})(?!\d)")


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def normalize(text: str) -> str:
    """Lower-case, NFC, Bangla digits -> ASCII, tidy whitespace and symbols."""
    t = nfc(text or "").translate(BANGLA_DIGITS).lower()
    t = t.replace("৳", " taka ").replace("/-", " taka ")
    # "1,500" / "1,00,000" -> "1500" / "100000": thousands separators must go
    # before punctuation is stripped, or "1,500" would become "1 500"
    t = re.sub(r"(?<=\d),(?=\d{2,3}\b|\d{2,3},)", "", t)
    t = re.sub(r"[“”\"'’`!?।|,;:()\[\]{}]", " ", t)
    # "5k" / "1.5k" -> "5000" / "1500" (before digits and letters are split,
    # so a lone "k" - Banglish for "ke" - is never read as "thousand")
    t = re.sub(r"(?<![\w.])(\d{1,4}(?:\.\d+)?)k\b",
               lambda m: str(int(round(float(m.group(1)) * 1000))), t)
    # split digits glued to letters: "500taka" / "500টাকা" -> "500 taka"
    t = re.sub(r"(?<=\d)(?=[^\d\s.])", " ", t)
    t = re.sub(r"(?<=[^\d\s.+])(?=\d)", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def extract_phones(text: str) -> tuple[list[str], str]:
    """Return (phones, text_without_phones). Phones are 11-digit 01XXXXXXXXX."""
    phones: list[str] = []

    def _sub(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(1))
        if len(digits) == 11:
            phones.append(digits)
            return " <phone> "
        return m.group(0)

    stripped = PHONE_RE.sub(_sub, text)
    return phones, re.sub(r"\s+", " ", stripped).strip()


def tokens(text: str) -> list[str]:
    return [t for t in text.split(" ") if t]


def mask_phone(phone: str) -> str:
    return phone[:3] + "****" + phone[-4:] if len(phone) == 11 else phone
