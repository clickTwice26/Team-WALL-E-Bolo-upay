"""Rule-based intent detection (path B of the parser)."""
from __future__ import annotations

from .text import normalize

RECHARGE = ["recharge", "রিচার্জ", "রিচার্য", "flexiload", "flexi", "ফ্লেক্সি",
            "ফ্লেক্সিলোড", "top up", "topup", "টপআপ", "bhore dao", "ভরে দাও",
            "rechaj", "richarge"]
BALANCE = ["balance", "ব্যালেন্স", "ব্যালান্স", "koto taka ache", "কত টাকা আছে",
           "taka koto ache", "টাকা কত আছে", "check balance"]
SEND = ["pathao", "pathan", "pathai", "pathabo", "pathiye", "pathate", "patha",
        "পাঠাও", "পাঠান", "পাঠাই", "পাঠাবো", "পাঠিয়ে", "পাঠাতে", "পাঠা",
        "send", "transfer", "ট্রান্সফার", "dao", "diye dao", "দাও", "দিয়ে দাও",
        "den", "দেন", "dite", "দিতে", "ferot", "ফেরত", "return", "give"]
UNSUPPORTED = {
    "cash_out": ["cash out", "cashout", "ক্যাশ আউট", "ক্যাশআউট", "taka tulbo",
                 "টাকা তুলব", "টাকা তুলবো", "withdraw"],
    "pay_bill": ["bill", "বিল", "electricity", "বিদ্যুৎ", "gas bill", "গ্যাস"],
    "add_money": ["add money", "অ্যাড মানি", "cash in", "ক্যাশ ইন"],
}
RETURN_CLAIM = ["ferot", "ফেরত", "return", "vul kore", "bhul kore", "ভুল করে",
                "ভুলে", "vule", "bhule", "by mistake", "wrong number"]
SELF = ["amar", "আমার", "nijer", "নিজের", "my number", "my phone", "my own"]

_cache: dict[str, list[str]] = {}


def _norm_list(name: str, items: list[str]) -> list[str]:
    if name not in _cache:
        _cache[name] = [normalize(i) for i in items]
    return _cache[name]


def _has(text: str, name: str, items: list[str]) -> bool:
    padded = f" {text} "
    for kw in _norm_list(name, items):
        if any("ঀ" <= ch <= "৿" for ch in kw):
            if kw in text:  # Bangla words take glued suffixes: পাঠাও -> পাঠাওতো
                return True
        elif f" {kw} " in padded:
            return True
    return False


def detect(text_norm: str, has_amount: bool) -> dict:
    """Return {"intent", "is_return_claim", "self_target", "unsupported"}."""
    out = {
        "is_return_claim": _has(text_norm, "ret", RETURN_CLAIM),
        "self_target": _has(text_norm, "self", SELF),
        "unsupported": None,
    }
    if _has(text_norm, "recharge", RECHARGE):
        out["intent"] = "mobile_recharge"
    elif _has(text_norm, "balance", BALANCE) and not has_amount:
        out["intent"] = "check_balance"
    else:
        for name, kws in UNSUPPORTED.items():
            if _has(text_norm, f"u_{name}", kws):
                out["intent"] = "unsupported"
                out["unsupported"] = name
                return out
        if _has(text_norm, "send", SEND) or has_amount:
            out["intent"] = "send_money"
        else:
            out["intent"] = "unknown"
    return out
