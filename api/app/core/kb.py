"""upay knowledge base: retrieval over upay's public website (RAG).

``scripts/scrape_upay.py`` crawls www.upaybd.com and its public CMS into
``data/upay_kb/kb.jsonl``: about 530 chunks of English and Bangla text
(services, how-tos, limits and charges, FAQ, offers, terms, privacy policy),
each with its source URL.

Retrieval is BM25 over the same normalised tokens the parsers use, with light
Bangla suffix stripping and a small Banglish/Bangla -> English glossary, so
"ক্যাশ আউট চার্জ কত", "cash out er charge koto" and "cash out charge" find the
same rows. No embeddings, no extra dependencies, and it loads in milliseconds.

The agent gives the top chunks to the LLM (which must answer only from them
and cite the page), and without an LLM answers with the best matching lines.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .text import normalize

KB_PATH = Path(__file__).resolve().parents[3] / "data" / "upay_kb" / "kb.jsonl"
MANIFEST = KB_PATH.with_name("manifest.json")
K1, B = 1.4, 0.75

# Banglish / Bangla words -> the English words the site uses, so a query in
# any script reaches both halves of a bilingual chunk
GLOSSARY = {
    "চার্জ": "charge", "খরচ": "charge", "khoroch": "charge", "kharach": "charge", "fee": "charge",
    "ফি": "charge", "cost": "charge", "charj": "charge",
    "লিমিট": "limit", "সীমা": "limit", "limits": "limit", "seema": "limit", "shima": "limit",
    "ক্যাশ": "cash", "ক্যাশআউট": "cashout", "আউট": "out", "ইন": "in",
    "সেন্ড": "send", "মানি": "money", "পাঠানো": "send", "পাঠাতে": "send",
    "রেজিস্ট্রেশন": "registration", "নিবন্ধন": "registration", "রেজিস্টার": "registration",
    "register": "registration", "account": "registration", "একাউন্ট": "account", "অ্যাকাউন্ট": "account",
    "খুলব": "open", "খুলতে": "open", "khulbo": "open", "khulte": "open",
    "পিন": "pin", "ভুলে": "forgot", "vule": "forgot", "bhule": "forgot", "forget": "forgot",
    "রিসেট": "reset", "রিচার্জ": "recharge", "বিল": "bill", "পেমেন্ট": "payment",
    "রেমিট্যান্স": "remittance", "রেমিটেন্স": "remittance", "প্রবাসী": "remittance",
    "এজেন্ট": "agent", "দোকান": "agent", "অফার": "offer", "ক্যাশব্যাক": "cashback",
    "ডিপিএস": "dps", "সঞ্চয়": "dps", "কার্ড": "card", "প্রিপেইড": "prepaid",
    "কাস্টমার": "customer", "অভিযোগ": "complaint",
    "নিরাপত্তা": "security", "প্রতারণা": "fraud", "স্ক্যাম": "fraud", "scam": "fraud",
    "ওটিপি": "otp", "otp": "otp pin", "গোপন": "secret",
    "টোল": "toll", "ট্রাফিক": "traffic", "জরিমানা": "fine", "শিক্ষা": "education",
    "ব্যাংক": "bank", "এটিএম": "atm", "কিউআর": "qr", "দৈনিক": "daily", "মাসিক": "monthly",
    "dainik": "daily", "masik": "monthly",
}
# query side only: how people ask -> the words the answer uses on the site
ASK = {
    "হেল্পলাইন": "16268 call talk", "helpline": "16268 call talk", "hotline": "16268 call talk",
    "কেয়ার": "16268 call talk", "contact": "16268 call talk", "যোগাযোগ": "16268 call talk",
    "jogajog": "16268 call talk", "khulbo": "create registration", "khulte": "create registration",
    "খুলব": "create registration", "খুলতে": "create registration", "open": "create registration",
}
ASK_PHRASES = {"customer care": "16268 call talk customerservice", "কাস্টমার কেয়ার": "16268 call talk",
               "call center": "16268 call talk", "কল সেন্টার": "16268 call talk"}
# press articles repeat product words without answering anything; the charge
# table should win a question about charges or limits
CATEGORY_WEIGHT = {"press": 0.6, "offer": 0.85}
CHARGE_TERMS = frozenset({"charge", "limit", "daily", "monthly"})
STOP = frozenset(normalize(w) for w in (
    "the a an is are was be to of in on for and or with my your i me you it this that what "
    "how can do does upay উপায় কি কী কত কিভাবে কীভাবে কেমনে কোথায় আমি আমার আমাকে আপনার এর "
    "এ ও এবং করে করতে করব করবো হবে হয় আছে জন্য দিয়ে থেকে ki koto kivabe kibhabe kemne kothay "
    "ami amar amake apnar er e o kore korte korbo hobe hoy ache jonno diye theke taka টাকা").split())
BN_SUFFIXES = ("গুলো", "গুলি", "দের", "েরা", "ের", "তে", "কে", "রা", "য়", "র", "ে", "টি", "টা")
WEIGHT_TITLE = 2  # a title/section word counts twice


def _bangla(w: str) -> bool:
    return any("ঀ" <= ch <= "৿" for ch in w)


def _stem(w: str) -> str:
    if _bangla(w):
        for s in BN_SUFFIXES:
            if w.endswith(s) and len(w) - len(s) >= 2:
                return w[: -len(s)]
        return w
    for s in ("ing", "es", "s"):  # charges -> charge, limits -> limit
        if w.endswith(s) and len(w) - len(s) >= 3:
            return w[: -len(s)]
    return w


def terms(text: str, query: bool = False) -> list[str]:
    out = []
    if query:
        t = normalize(text)
        for phrase, extra in ASK_PHRASES.items():
            if normalize(phrase) in t:
                out.extend(extra.split())
    for w in re.split(r"[^\wঀ-৿]+", normalize(text)):
        if not w or w in STOP or (len(w) < 2 and not w.isdigit()):
            continue
        out.append(_stem(w))
        g = GLOSSARY.get(w) or GLOSSARY.get(_stem(w))
        if g:
            out.extend(g.split())
        if query and (ASK.get(w) or ASK.get(_stem(w))):
            out.extend((ASK.get(w) or ASK[_stem(w)]).split())
    return out


class Index:
    def __init__(self, records: list[dict]):
        self.records = records
        self.tf: list[Counter] = []
        df: Counter = Counter()
        for r in records:
            tf = Counter(terms(r["text"]))
            for t in terms(f"{r['title']} {r['section']}"):
                tf[t] += WEIGHT_TITLE
            self.tf.append(tf)
            df.update(tf.keys())
        n = max(len(records), 1)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self.len = [sum(tf.values()) for tf in self.tf]
        self.avg = (sum(self.len) / n) if records else 1.0

    def search(self, query: str, k: int = 4) -> list[dict]:
        q = list(dict.fromkeys(terms(query, query=True)))
        if not q or not self.records:
            return []
        scores = []
        charges = bool(CHARGE_TERMS & set(q))
        for i, tf in enumerate(self.tf):
            s = 0.0
            norm = K1 * (1 - B + B * self.len[i] / self.avg)
            for t in q:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (K1 + 1) / (f + norm)
            if s > 0:
                cat = self.records[i].get("category")
                s *= CATEGORY_WEIGHT.get(cat, 1.0) * (1.4 if charges and cat == "charges_limits" else 1.0)
                scores.append((s, i))
        scores.sort(reverse=True)
        hits, seen = [], set()
        for s, i in scores:
            r = self.records[i]
            if r["text"] in seen:
                continue
            seen.add(r["text"])
            hits.append({**r, "score": round(s, 2), "matched": [t for t in q if t in self.tf[i]]})
            if len(hits) == k:
                break
        return hits


@lru_cache(maxsize=1)
def index() -> Index:
    if not KB_PATH.exists():
        return Index([])
    with KB_PATH.open(encoding="utf-8") as f:
        return Index([json.loads(line) for line in f if line.strip()])


@lru_cache(maxsize=1)
def info() -> dict:
    try:
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        m = {}
    return {"source": m.get("source", "https://www.upaybd.com"), "crawled_at": m.get("crawled_at"),
            "chunks": len(index().records)}


def search(query: str, k: int = 4) -> list[dict]:
    return index().search(query, k)


# ---------------------------------------------------------------- questions
QUESTION = tuple(normalize(w) for w in (
    "কত", "কতো", "কিভাবে", "কীভাবে", "কি ভাবে", "কেমনে", "কোথায়", "কী", "কি", "কেন", "কখন",
    "জানতে চাই", "জানাও", "বলো", "বলুন", "নিয়ম", "koto", "kto", "kivabe", "kibhabe", "ki vabe",
    "kemne", "kothay", "keno", "kokhon", "ki", "niyom", "how", "what", "where", "which", "when",
    "why", "is there", "can i", "do i", "tell me", "explain", "?"))
TOPIC = tuple(normalize(w) for w in (
    "charge", "চার্জ", "খরচ", "khoroch", "fee", "ফি", "limit", "লিমিট", "সীমা", "registration",
    "রেজিস্ট্রেশন", "account", "একাউন্ট", "অ্যাকাউন্ট", "pin reset", "পিন রিসেট", "pin vule",
    "পিন ভুলে", "forgot pin", "offer", "অফার", "cashback", "ক্যাশব্যাক", "dps", "ডিপিএস",
    "remittance", "রেমিট্যান্স", "agent", "এজেন্ট", "helpline", "হেল্পলাইন", "customer care",
    "কাস্টমার কেয়ার", "prepaid card", "প্রিপেইড কার্ড", "card", "কার্ড", "payoneer", "toll", "টোল",
    "traffic fine", "land tax", "e porcha", "nid", "privacy", "terms", "শর্ত", "bank", "ব্যাংক",
    "atm", "এটিএম", "upay", "উপায়", "service", "সার্ভিস", "cash out", "ক্যাশ আউট", "cash in",
    "ক্যাশ ইন", "add money", "অ্যাড মানি", "pay bill", "বিল", "send money", "সেন্ড মানি",
    "recharge", "রিচার্জ", "remit", "qr", "merchant", "মার্চেন্ট", "donation", "education",
    "daily", "monthly", "দৈনিক", "মাসিক", "complaint", "অভিযোগ", "ucb", "pin", "পিন", "otp",
    "ওটিপি", "reset", "রিসেট", "number", "নম্বর", "nombor"))
# asked even without a question word: "send money limit", "cash out charge"
STRONG = tuple(normalize(w) for w in (
    "charge", "চার্জ", "খরচ", "khoroch", "fee", "ফি", "limit", "লিমিট", "সীমা", "kivabe",
    "kibhabe", "কিভাবে", "কীভাবে", "how to", "how do", "how can", "helpline", "হেল্পলাইন",
    "customer care", "কাস্টমার কেয়ার", "pin reset", "পিন রিসেট", "forgot pin", "pin vule",
    "pin bhule", "পিন ভুলে"))


def _has_any(t: str, words: tuple[str, ...]) -> bool:
    padded = f" {t} "
    return any((w in t) if _bangla(w) or w == "?" else (f" {w} " in padded) for w in words)


def is_info_question(text: str) -> bool:
    """'ক্যাশ আউট চার্জ কত?', 'how do I reset my PIN', 'dps ki': a question about
    upay itself (asked with a question word and a product/policy word)."""
    t = normalize(text)
    return _has_any(t, STRONG) or (_has_any(t, TOPIC) and (_has_any(t, QUESTION) or "?" in text))


# ---------------------------------------------------------------- extractive answer
def mostly_bangla(s: str) -> bool:
    letters = [ch for ch in s if ch.isalpha()]
    return bool(letters) and sum("ঀ" <= ch <= "৿" for ch in letters) / len(letters) > 0.4


SUBHEAD = re.compile(r"^(min|max|count|amount|সংখ্যা|এমাউন্ট|সর্বনিম্ন|সর্বোচ্চ)(\s*\|\s*\S.*)?$", re.I)


def _units(text: str) -> list[str]:
    """Lines of a chunk, each FAQ question kept with its answer and each bare
    table row prefixed with its table's header ('Daily Transaction Limit
    (Count | Amount): Send Money | 50 | 50,000')."""
    out: list[str] = []
    caption = sub = ""
    for ln in text.split("\n"):
        ln = ln.strip(" •-")
        if not ln or ln.startswith("## "):
            continue
        cells = [c.strip() for c in ln.split("|")]
        if cells[0].lower() in ("service type", "সার্ভিস টাইপ") and len(cells) > 1:
            caption, sub = " / ".join(c for c in cells[1:] if c), ""
            continue
        if caption and SUBHEAD.match(ln):
            sub = ln
            continue
        if ln.startswith("A:") and out and out[-1].startswith("Q:"):
            out[-1] = f"{out[-1]} {ln}"
        elif caption and _is_grid(ln):
            out.append(f"{caption}{f' ({sub})' if sub else ''}: {ln}")
        else:
            if re.match(r"^\s*table title:", ln, re.I):
                caption = sub = ""
            out.append(ln)
    return out


def best_lines(query: str, hit: dict, bangla: bool, n: int = 2) -> list[str]:
    """The lines of a chunk that best answer the query, in one script."""
    q = set(terms(query, query=True))
    scored = []
    for i, ln in enumerate(_units(hit["text"])):
        if mostly_bangla(ln) != bangla or len(ln) < 12:
            continue
        overlap = len(q & set(terms(ln)))
        if overlap:
            scored.append((overlap, -i, ln))
    scored.sort(reverse=True)
    picked = sorted(scored[:n], key=lambda x: -x[1])
    return [ln[:320] for _, _, ln in picked]


def _is_grid(line: str) -> bool:
    """A table row without field names: 'Send Money | 10 | 25,000'."""
    return "|" in line and not re.match(r"^\s*[^:|]{1,40}:", line)


_CELL = re.compile(r"^\s*([^:|]{1,40}):\s*(.*)$")


def speakable(line: str, bangla: bool) -> str:
    """'title: 16268-Talk To Us | title bn: ১৬২৬৮ | desc: ...' -> the values in
    one language, without the CMS field names, ready to read aloud."""
    if "|" not in line or not re.match(r"^\s*[^:|]{1,40}:", line.split("|")[0]):
        return line  # a table row keeps its cells
    keep, other = [], []
    for cell in line.split("|"):
        m = _CELL.match(cell)
        key, val = (m.group(1).strip().lower(), m.group(2).strip()) if m else ("", cell.strip())
        if not val:
            continue
        bn_cell = key.endswith(" bn") or key.endswith("_bn") or (not key and mostly_bangla(val))
        (keep if bn_cell == bangla else other).append(val)
    vals = list(dict.fromkeys(keep or other))
    return " — ".join(vals)


def answer(query: str, min_score: float = 4.0) -> Optional[dict]:
    """A short extractive answer (no LLM): the best chunk's best lines in
    Bangla and English, with its source. None if nothing is relevant enough."""
    hits = search(query, k=3)
    if not hits or hits[0]["score"] < min_score:
        return None
    top = hits[0]
    lines = _units(top["text"])
    # one charge row per service: a near tie ("cash out" = agent / ATM) lists both
    group = [top] + [h for h in hits[1:] if top["section"].startswith("Charges ›")
                     and h["section"].startswith("Charges ›") and h["score"] >= 0.85 * top["score"]]

    def pick(bangla: bool, src_bangla: bool) -> list[str]:
        return [speakable(x, bangla) for h in group
                for x in best_lines(query, h, bangla=src_bangla, n=2 if len(group) == 1 else 3)]

    en, bn = pick(False, False), pick(True, True)
    # a bilingual row ("title: X | title bn: Y") counts for both languages
    if not bn and any("|" in x for x in lines):
        bn = pick(True, False)
    if not en and not bn:
        return None
    return {"en": " ".join(en) or " ".join(bn), "bn": " ".join(bn) or " ".join(en),
            "source": {"url": top["url"], "title": top["title"], "section": top["section"]},
            "hits": hits}
