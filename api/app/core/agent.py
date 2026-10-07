"""Bolo agent: one voice/text assistant on every page of the app.

The app sends what is on screen (page, step, a short summary, and the actions
its buttons offer right now), the last pages the user visited and the
conversation. The agent answers in Bangla and English and returns actions,
which the app runs through the same code as its buttons.

Two planning paths, like the parser: an LLM when a key is set, and a
page-aware keyword router for Bangla, Banglish and English. Every plan from
either path goes through ``sanitize``: the agent can open pages and fill in a
transfer, but it can never enter a PIN, use biometrics, tick the RED warning
box, skip a hold, or confirm anything the page does not offer to confirm.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Literal, Optional

from pydantic import BaseModel

from . import contacts as contacts_mod
from . import intent as intent_mod
from . import llm, pinguard
from .numbers import parse_amount
from .text import extract_phones, mask_phone, normalize, tokens

PAGES = ("home", "dashboard", "accuracy", "assistant")
GLOBAL_ACTIONS = {"navigate", "go_back", "open_settings", "refresh", "set_language",
                  "show_balance", "switch_user", "set_simulate_call", "reset_demo",
                  "start_transfer"}
PAGE_ACTIONS = {"select_amount", "select_recipient", "clarify_continue", "answer_interview",
                "confirm", "accept_suggestion", "keep_amount", "continue_to_pin",
                "cancel_transfer", "new_transaction", "repeat"}
# Only the user's own words may trigger these: never on an automatic
# follow-up (observation) call, never without a message.
USER_WORDS_ONLY = {"start_transfer", "select_amount", "select_recipient", "clarify_continue",
                   "answer_interview", "confirm", "accept_suggestion", "keep_amount",
                   "continue_to_pin", "reset_demo", "switch_user"}
MAX_ACTIONS = 4
MAX_AMOUNT = 1_000_000
MAX_TEXT = 300
PHONE_RE = re.compile(r"^01[3-9]\d{8}$")


class AgentAction(BaseModel):
    type: Literal["navigate", "go_back", "open_settings", "refresh", "set_language",
                  "show_balance", "switch_user", "set_simulate_call", "reset_demo",
                  "start_transfer", "select_amount", "select_recipient", "clarify_continue",
                  "answer_interview", "confirm", "accept_suggestion", "keep_amount",
                  "continue_to_pin", "cancel_transfer", "new_transaction", "repeat"]
    page: Optional[Literal["home", "dashboard", "accuracy", "assistant"]] = None
    lang: Optional[Literal["bn", "en"]] = None
    on: Optional[bool] = None
    user_id: Optional[str] = None
    text: Optional[str] = None
    amount: Optional[int] = None
    contact_id: Optional[str] = None
    phone: Optional[str] = None


class AgentPlan(BaseModel):
    reply_bn: str
    reply_en: str
    actions: list[AgentAction]
    done: bool


# ---------------------------------------------------------------- replies
PAGE_LABEL = {"home": ("হোম", "Home"), "dashboard": ("ড্যাশবোর্ড", "Dashboard"),
              "accuracy": ("অ্যাকুরেসি রিপোর্ট", "Accuracy report"),
              "assistant": ("সেন্ড মানি", "Send Money"), "settings": ("সেটিংস", "Settings")}
NOT_UNDERSTOOD = ("দুঃখিত, বুঝতে পারিনি। বলতে পারেন, যেমন: 'আম্মুকে ৫০০ টাকা পাঠাও', "
                  "'ড্যাশবোর্ড খোলো' বা 'ব্যালেন্স দেখাও'।",
                  "Sorry, I didn't understand. You can say, for example: 'Send 500 taka to "
                  "Ammu', 'Open the dashboard' or 'Show my balance'.")
PIN_WARNING = ("সতর্কতা! পিন বা ওটিপি কখনো কাউকে বলবেন না, আমাকেও না। উপায় কখনো পিন বা ওটিপি চায় না। "
               "কেউ চাইলে ফোন কেটে দিন এবং হেল্পলাইন ১৬২৬৮ নম্বরে কল করুন।",
               "Warning! Never share your PIN or OTP with anyone, not even me. upay never asks "
               "for it. If someone asks, hang up and call the helpline 16268.")
GUARD_NOTE = (" (নিরাপত্তার জন্য এই ধাপটি আপনাকে নিজে করতে হবে।)",
              " (For your safety, that step is yours to do by hand.)")
HELP = ("আমি যেকোনো পেজে আপনার কথা শুনে কাজ করতে পারি: টাকা পাঠানো ('আম্মুকে ৫০০ টাকা পাঠাও'), "
        "পেজ খোলা ('ড্যাশবোর্ড খোলো'), ব্যালেন্স দেখা, ভাষা বদলানো, আর এই পেজে কী আছে বলা। "
        "পিন সবসময় আপনাকেই দিতে হবে।",
        "I can act on what you say on any page: send money ('Send 500 taka to Ammu'), open "
        "pages ('Open the dashboard'), show your balance, switch the language, and tell you "
        "what is on this page. You always enter the PIN yourself.")

_BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def _taka(n: float) -> tuple[str, str]:
    s = f"{int(round(n)):,}"
    return "৳" + s.translate(_BN_DIGITS), "৳" + s


def _plan(bn: str, en: str, actions: list[dict] | None = None, done: bool = True) -> dict:
    return {"reply_bn": bn, "reply_en": en, "actions": actions or [], "done": done}


def _label(pid: str | None) -> tuple[str, str]:
    return PAGE_LABEL.get(pid or "", (pid or "", pid or ""))


def _describe(page: dict, prefix: tuple[str, str] = ("", "")) -> tuple[str, str]:
    bn = (page.get("summary_bn") or "").strip() or "এই পেজের কোনো বিবরণ পাওয়া যায়নি।"
    en = (page.get("summary_en") or "").strip() or "I have no description of this page."
    return prefix[0] + bn, prefix[1] + en


# ---------------------------------------------------------------- matching
def _bangla(s: str) -> bool:
    return any("ঀ" <= ch <= "৿" for ch in s)


@lru_cache(maxsize=None)
def _pattern(phrases: tuple[str, ...]) -> re.Pattern:
    alts = []
    for p in phrases:
        n = re.escape(normalize(p))
        # Bangla words take glued suffixes ("ড্যাশবোর্ডে"); Latin words stand alone
        alts.append(rf"(?:^|\s){n}" if _bangla(p) else rf"(?:^|\s){n}(?=\s|$)")
    return re.compile("|".join(alts))


def _has(t: str, phrases: tuple[str, ...]) -> bool:
    return bool(_pattern(phrases).search(t))


def _norm_set(words: str) -> frozenset[str]:
    return frozenset(normalize(w) for w in words.split())


_YES = _norm_set("হ্যাঁ হ্যা হাঁ হা জি জ্বি জী ঠিক আচ্ছা ওকে নিশ্চিত কনফার্ম পাঠাও পাঠান পাঠিয়ে দাও দিন "
                 "ha haa hae hya ji jee thik accha achha acha ok okay okey confirm pathao pathan "
                 "pathiye dao yes yeah yep yup sure correct send")
_NO = _norm_set("না নাহ নো na nah no nope")
_FILLER = _norm_set("আছে ache please plz pls ভাই bhai আপা apa তো to করো koro করুন korun এটা eta "
                    "এখন ekhon now just it that s is right sir")
_YES_PHRASES = frozenset(normalize(p) for p in ("go ahead", "do it", "send it", "go on",
                                                "that's right", "all right"))
_NO_PHRASES = frozenset(normalize(p) for p in ("no thanks", "no thank you"))


def _bare(t: str, core: frozenset[str], phrases: frozenset[str]) -> bool:
    """A short yes / no with nothing else in it: no amount, number or name."""
    words = t.split()
    if not words or len(words) > 5:
        return False
    rest = [w for w in words if w not in _FILLER]
    if " ".join(words) in phrases or " ".join(rest) in phrases:
        return True
    return bool(rest) and all(w in core for w in rest)


def _is_yes(t: str) -> bool:
    return _bare(t, _YES, _YES_PHRASES)


def _is_no(t: str) -> bool:
    return _bare(t, _NO, _NO_PHRASES)


def _amount(t: str) -> Optional[int]:
    _, rest = extract_phones(t)
    a = parse_amount(tokens(rest))["amount"]
    return a if a and 1 <= a <= MAX_AMOUNT else None


CANCEL = ("বাতিল", "বাদ দাও", "বাদ দিন", "দরকার নেই", "লাগবে না", "পাঠাবো না", "পাঠাব না",
          "পাঠাতে চাই না", "ক্যানসেল", "ক্যান্সেল", "batil", "bad dao", "bad den", "thak",
          "dorkar nai", "dorkar nei", "lagbe na", "pathabo na", "pathate chai na", "cancel",
          "abort", "don't send", "do not send", "dont send", "never mind", "nevermind", "forget it")
CANCEL_WORDS = _norm_set("থাক থাকুক")
REPEAT = ("আবার বলো", "আবার বলুন", "আরেকবার বলো", "আরেকবার বলুন", "রিপিট", "abar bolo", "abar bolen",
          "arekbar bolo", "repeat", "say again", "say that again", "say it again", "one more time")
NEW_TX = ("নতুন", "আরেকটা", "আরেকটি", "new", "notun", "arekta", "another")
CONTINUE = ("এগিয়ে যাও", "এগিয়ে যান", "চালিয়ে যাও", "continue", "next", "proceed", "egiye jao",
            "chaliye jao")
PIN_WORDS = ("পিন", "pin", "otp", "ওটিপি", "fingerprint", "ফিঙ্গারপ্রিন্ট", "আঙুল")
HELP_WORDS = ("help", "হেল্প", "সাহায্য", "কী করতে পারো", "কি করতে পারো", "ki korte paro",
              "ki ki korte paro", "what can you do", "how does this work", "কিভাবে কাজ করে")
LANG_EN = _norm_set("english ইংরেজি ইংরেজিতে ইংলিশ ইংলিশে engreji ingreji inglish")
LANG_BN = _norm_set("bangla বাংলা বাংলায় বাংলাতে banglay banglate bengali")
LANG_VERBS = ("বলো", "বলুন", "বলবে", "কথা", "চালাও", "করো", "bolo", "bolen", "speak", "talk",
              "switch", "change", "use", "in", "e", "te", "please", "language", "ভাষা", "bhasha")
RESET = ("reset", "রিসেট")
DEMO = ("demo", "ডেমো")
SIM = ("simulate", "simulation", "সিমুলেশন", "সিমুলেট", "simulet")
CALL = ("call", "কল", "phone call", "ফোন কল")
ON = ("on", "চালু", "chalu", "start", "enable", "অন", "turn on")
OFF = ("off", "বন্ধ", "bondho", "bondo", "stop", "disable", "অফ", "turn off")
SWITCH = ("switch", "সুইচ", "change user", "user change", "ইউজার বদল", "ইউজার পরিবর্তন",
          "অ্যাকাউন্ট বদল", "বদলাও", "bodlao", "login as", "log in as", "লগইন", "হিসেবে",
          "hishebe", "hisebe", "account e jao", "অ্যাকাউন্টে যাও")
USER_WORD = ("user", "ইউজার", "ব্যবহারকারী", "account", "অ্যাকাউন্ট")
SETTINGS = ("settings", "setting", "সেটিংস", "সেটিং")
REFRESH = ("refresh", "রিফ্রেশ", "reload", "রিলোড", "update koro", "আপডেট করো")
BALANCE = ("balance", "ব্যালেন্স", "ব্যালান্স", "koto taka ache", "কত টাকা আছে", "taka koto ache",
           "টাকা কত আছে")
HIDE = ("hide", "লুকাও", "লুকিয়ে", "lukao", "lukiye", "বন্ধ", "bondho", "off")
BACK = ("ফিরে যাও", "ফিরে চলো", "পিছনে যাও", "পেছনে যাও", "আগের পেজে যাও", "আগের পাতায় যাও",
        "fire jao", "fire cholo", "pichone jao", "pichhone jao", "back jao", "go back", "back")
NAV_VERBS = ("যাও", "যান", "খোলো", "খুলুন", "খোল", "দেখাও", "দেখান", "চলো", "নিয়ে যাও", "jao",
             "kholo", "khulo", "dekhao", "dekhan", "cholo", "niye jao", "open", "go to", "go",
             "show", "take me to")
PAGE_WORDS = {
    "home": ("home", "হোম", "main page", "মূল পাতা", "প্রথম পাতা", "home page"),
    "dashboard": ("dashboard", "ড্যাশবোর্ড", "ops", "অপস"),
    "accuracy": ("accuracy", "অ্যাকুরেসি", "একুরেসি", "নির্ভুলতা", "metrics", "মেট্রিক্স"),
    "assistant": ("send money", "সেন্ড মানি", "বলো upay", "bolo upay", "টাকা পাঠানোর পেজ",
                  "taka pathanor page", "assistant"),
}
THIS_PAGE = ("এই পেজে কী", "এই পেজে কি", "এই পাতায় কী", "এই পাতায় কি", "স্ক্রিনে কী", "স্ক্রিনে কি",
             "এখানে কী আছে", "এখানে কি আছে", "এটা কোন পেজ", "আমি কোথায়", "ei page e ki",
             "ei pagee ki", "ekhane ki ache", "screen e ki", "eta kon page", "ami kothay",
             "what's on this page", "what is on this page", "what's on the screen",
             "what is on the screen", "what is this page", "where am i", "read this page",
             "describe this page")
PREV_PAGE = ("আগের পেজে", "আগের পাতায়", "ager page", "ager pagee", "previous page", "last page",
             "page before")
QUESTION = ("কী", "কি", "ছিল", "ki", "chilo", "what", "which")
AGAIN = ("আবার পাঠাও", "আবার পাঠান", "আরেকবার পাঠাও", "আগেরটা আবার", "একই টাকা আবার", "abar pathao",
         "abar pathan", "arekbar pathao", "aro ekbar pathao", "same again", "send again",
         "send it again", "repeat the transfer", "repeat last transfer", "do it again")
ORDINALS = {0: ("প্রথম", "প্রথমটা", "প্রথমজন", "1st", "first", "prothom", "prothomta",
                "ek number"),
            1: ("দ্বিতীয়", "দ্বিতীয়টা", "2nd", "second", "ditiyo", "ditio", "dui number"),
            2: ("তৃতীয়", "3rd", "third", "tritiyo", "tin number"),
            -1: ("শেষ", "শেষেরটা", "শেষটা", "last", "shesh", "sheshta", "shesherta")}
RELATION_WORDS = {
    "mother": "ma maa মা ammu আম্মু amma আম্মা mother mom",
    "father": "baba বাবা abbu আব্বু abba আব্বা father dad",
    "brother": "bhai ভাই bhaiya ভাইয়া brother",
    "sister": "apa আপা apu আপু bon বোন sister",
    "shop": "dokan দোকান shop store স্টোর",
    "landlord": "bariwala বাড়িওয়ালা landlord",
    "wife": "bou বউ wife stri স্ত্রী",
    "supplier": "supplier সাপ্লায়ার",
    "friend": "bondhu বন্ধু friend",
    "mess": "mess মেস manager",
}


# ---------------------------------------------------------------- Send Money page
def _word_bases(w: str) -> set[str]:
    out = {w}
    for suf in ("টাকে", "টা", "টি", "take", "ta", "ti"):
        if w.endswith(suf) and len(w) - len(suf) >= 2:
            out.add(w[: -len(suf)])
    for b in list(out):
        out |= contacts_mod._bases(b)
    return out


def _vocab(c: dict, contact: dict | None) -> set[str]:
    src = contact or c
    words: set[str] = set()
    for s in [src.get("name"), src.get("name_bn"), *src.get("aliases", [])]:
        words |= set(normalize(s or "").split())
    words |= set(normalize(RELATION_WORDS.get(src.get("relation") or "", "")).split())
    return words


def _ordinal(t: str) -> tuple[Optional[int], str]:
    for idx, phrases in ORDINALS.items():
        m = _pattern(phrases).search(t)
        if m:
            return idx, (t[: m.start()] + " " + t[m.end():]).strip()
    return None, t


def _pick_recipient(t: str, candidates: list[dict], user: dict) -> Optional[dict]:
    """Which displayed candidate the user means: by phone, order or a word only
    one of them has ("dokan" -> Rahim Store, "bhai" -> Rahim Uddin)."""
    by_id = {c["id"]: c for c in user["contacts"]}
    phones, rest = extract_phones(t)
    if phones:
        known = next((c for c in user["contacts"] if c["phone"] == phones[0]), None)
        return {"contact_id": known["id"]} if known else {"phone": phones[0]}
    idx, rest = _ordinal(rest)
    if idx is not None and candidates and -len(candidates) <= idx < len(candidates):
        c = candidates[idx]
        return {"contact_id": c["id"]} if c.get("id") in by_id else None
    cands = [c for c in candidates if c.get("id") in by_id]
    said = set().union(*[_word_bases(w) for w in rest.split()]) if rest.split() else set()
    vocab = {c["id"]: _vocab(c, by_id[c["id"]]) for c in cands}
    hits = [c for c in cands
            if (vocab[c["id"]] - set().union(*[vocab[o["id"]] for o in cands if o is not c])) & said]
    if len(hits) == 1:
        return {"contact_id": hits[0]["id"]}
    r = contacts_mod.resolve(tokens(rest), [], [by_id[c["id"]] for c in cands])
    if r["status"] == "found":
        return {"contact_id": r["contact"]["id"]}
    return None


def _full_command(t: str, user: dict) -> bool:
    """"karim ke 2000 pathao" on a step page is a new command, not an answer."""
    amount = _amount(t)
    det = intent_mod.detect(t, amount is not None)
    if det["intent"] not in ("send_money", "mobile_recharge") or amount is None:
        return False
    phones, rest = extract_phones(t)
    if phones:
        return True
    return contacts_mod.resolve(tokens(rest), [], user["contacts"])["status"] in ("found", "ambiguous")


def _send_money(t: str, msg: str, page: dict, user: dict) -> Optional[dict]:
    step = page.get("step")
    c = page.get("content") or {}
    offered = set(page.get("actions") or [])
    if "cancel_transfer" in offered and (_has(t, CANCEL) or set(t.split()) & CANCEL_WORDS):
        return _plan("ঠিক আছে, লেনদেনটি বাতিল করছি।", "OK, cancelling the transfer.",
                     [{"type": "cancel_transfer"}])
    if "repeat" in offered and _has(t, REPEAT):
        return _plan("", "", [{"type": "repeat"}])

    if step == "interview" and "answer_interview" in offered:
        # the user's own words go to the scam check, whatever they are
        return _plan("", "", [{"type": "answer_interview", "text": msg}])

    if step == "clarify":
        if _full_command(t, user):
            return None
        acts: list[dict] = []
        amount = _amount(_ordinal(t)[1])  # "1st" is an order, not ৳1
        if amount and "select_amount" in offered:
            acts.append({"type": "select_amount", "amount": amount})
        cands = c.get("recipient_candidates") or []
        rec = None
        if "select_recipient" in offered:
            rec = _pick_recipient(t, cands, user)
            if rec is None and _is_yes(t) and len(cands) == 1 and cands[0].get("id"):
                rec = {"contact_id": cands[0]["id"]}  # "yes" to "Did you mean ...?"
        if rec:
            acts.append({"type": "select_recipient", **rec})
        if acts:
            acts.append({"type": "clarify_continue"})
            return _plan("ঠিক আছে।", "OK.", acts)
        if _is_yes(t) and "clarify_continue" in offered:
            return _plan("ঠিক আছে।", "OK.", [{"type": "clarify_continue"}])
        return None

    if step == "review":
        mistake = c.get("mistake")
        amount = _amount(t)
        if mistake and "accept_suggestion" in offered:
            if amount == mistake.get("suggested") or (amount is None and _is_yes(t)):
                bn, en = _taka(mistake["suggested"])
                return _plan(f"ঠিক আছে, {bn} করে দিচ্ছি।", f"OK, changing it to {en}.",
                             [{"type": "accept_suggestion"}])
            if amount == c.get("amount") or (amount is None and _is_no(t)):
                bn, en = _taka(c.get("amount") or 0)
                return _plan(f"ঠিক আছে, {bn}-ই থাকছে।", f"OK, keeping {en}.",
                             [{"type": "keep_amount"}])
        if _is_yes(t):
            if c.get("level") == "RED":
                reasons = c.get("reasons") or []
                why_bn = " ".join(r.get("bn", "") for r in reasons[:2]).strip()
                why_en = " ".join(r.get("en", "") for r in reasons[:2]).strip()
                return _plan(
                    f"এই লেনদেনে প্রতারণার ঝুঁকি বেশি। {why_bn} নিরাপত্তার জন্য আমি এটি নিশ্চিত করতে "
                    "পারি না। তবুও পাঠাতে চাইলে 'তবুও পাঠাতে চাই' বোতামে নিজে চাপ দিন।",
                    f"This transfer has a high scam risk. {why_en} For your safety I can't "
                    "confirm it. If you still want to send, tap 'I still want to send' yourself.")
            if "confirm" in offered:
                return _plan("ঠিক আছে, নিশ্চিত করছি। এবার পিন দিন।", "OK, confirming. Now enter your PIN.",
                             [{"type": "confirm"}])
        if _is_no(t) and not mistake and "cancel_transfer" in offered:
            return _plan("ঠিক আছে, লেনদেনটি বাতিল করছি।", "OK, cancelling the transfer.",
                         [{"type": "cancel_transfer"}])
        return None

    if step == "hold" and (_is_yes(t) or _has(t, CONTINUE)):
        if "continue_to_pin" in offered:
            return _plan("ঠিক আছে, পিনের ধাপে যাচ্ছি।", "OK, going to the PIN step.",
                         [{"type": "continue_to_pin"}])
        left = int(c.get("hold_seconds_left") or 0)
        wait_bn = f" আরও {str(left).translate(_BN_DIGITS)} সেকেন্ড অপেক্ষা করতে হবে।" if left else ""
        wait_en = f" There are {left} seconds left on the hold." if left else ""
        return _plan("নিরাপত্তার জন্য সতর্কবার্তার বক্সে টিক আপনাকে নিজে দিতে হবে।" + wait_bn,
                     "For your safety, you have to tick the warning box yourself." + wait_en)

    if step == "auth" and (_is_yes(t) or _has(t, PIN_WORDS)):
        return _plan("পিন বা ফিঙ্গারপ্রিন্ট আপনাকে নিজে দিতে হবে। আমি কখনো পিন দেখি না বা দিই না।",
                     "You enter the PIN or fingerprint yourself. I never see or enter your PIN.")

    if step == "done" and "new_transaction" in offered and _has(t, NEW_TX):
        return _plan("ঠিক আছে, নতুন লেনদেন।", "OK, a new transaction.", [{"type": "new_transaction"}])
    return None


# ---------------------------------------------------------------- global commands
def _help(t, msg, req, facts):
    if _has(t, HELP_WORDS):
        return _plan(*HELP)


def _language(t, msg, req, facts):
    words = t.split()
    en_at = max((i for i, w in enumerate(words) if w in LANG_EN), default=-1)
    bn_at = max((i for i, w in enumerate(words) if w in LANG_BN), default=-1)
    if en_at < 0 and bn_at < 0:
        return None
    if len(words) > 4 and not _has(t, LANG_VERBS):
        return None
    if bn_at > en_at:
        return _plan("ঠিক আছে, এখন থেকে বাংলায় বলছি।", "OK, I'll speak Bangla from now on.",
                     [{"type": "set_language", "lang": "bn"}])
    return _plan("ঠিক আছে, এখন থেকে ইংরেজিতে বলছি।", "OK, I'll speak English from now on.",
                 [{"type": "set_language", "lang": "en"}])


def _reset(t, msg, req, facts):
    if not _has(t, RESET):
        return None
    if _has(t, DEMO):
        return _plan("ডেমো ডেটা রিসেট করছি।", "Resetting the demo data.", [{"type": "reset_demo"}])
    return _plan("ডেমো ডেটা রিসেট করতে চাইলে বলুন 'ডেমো রিসেট করো'।",
                 "To reset the demo data, say 'reset the demo'.")


def _call_sim(t, msg, req, facts):
    sim = _has(t, SIM)
    on, off = _has(t, ON), _has(t, OFF)
    if not sim and not (_has(t, CALL) and (on or off) and _amount(t) is None
                        and not intent_mod.has_send_verb(t)):
        return None
    current = bool((req.get("settings") or {}).get("simulate_call"))
    value = True if on and not off else False if off and not on else not current
    if value:
        return _plan("ঠিক আছে, ফোন কল চলছে বলে ধরে নিচ্ছি (সিমুলেশন)।",
                     "OK, simulating an active phone call.",
                     [{"type": "set_simulate_call", "on": True}])
    return _plan("ফোন কল সিমুলেশন বন্ধ করলাম।", "Phone call simulation is off.",
                 [{"type": "set_simulate_call", "on": False}])


def _switch_user(t, msg, req, facts):
    if not _has(t, SWITCH):
        return None
    said = set().union(*[_word_bases(w) for w in t.split()])
    match = []
    for u in facts.get("users", []):
        names = {normalize(u["name"]), normalize(u.get("name_bn") or "")}
        names |= {normalize(u["name"]).split()[0], normalize(u.get("name_bn") or "x").split()[0]}
        if names & said or any(n and n in t for n in names if " " in n):
            match.append(u)
    if len(match) == 1:
        u = match[0]
        if u["id"] == facts["user"]["id"]:
            return _plan(f"আপনি এখন {u.get('name_bn') or u['name']} হিসেবেই আছেন।",
                         f"You are already {u['name']}.")
        return _plan(f"ঠিক আছে, {u.get('name_bn') or u['name']} হিসেবে চালু করছি।",
                     f"OK, switching to {u['name']}.", [{"type": "switch_user", "user_id": u["id"]}])
    if _has(t, USER_WORD):
        names_bn = ", ".join(u.get("name_bn") or u["name"] for u in facts.get("users", []))
        names_en = ", ".join(u["name"] for u in facts.get("users", []))
        return _plan(f"কোন ব্যবহারকারী? {names_bn}।", f"Which user? {names_en}.")
    return None


def _settings(t, msg, req, facts):
    if not _has(t, SETTINGS):
        return None
    if req["page"].get("id") == "settings":
        return _plan(*_describe(req["page"], ("আপনি সেটিংসেই আছেন। ", "You are in settings. ")))
    return _plan("সেটিংস খুলছি।", "Opening settings.", [{"type": "open_settings"}])


def _refresh(t, msg, req, facts):
    if _has(t, REFRESH):
        return _plan("নতুন করে লোড করছি।", "Refreshing.", [{"type": "refresh"}])


def _balance(t, msg, req, facts):
    if not _has(t, BALANCE) or _amount(t) is not None:
        return None
    if _has(t, HIDE):
        return _plan("ব্যালেন্স লুকিয়ে রাখলাম।", "Balance hidden.",
                     [{"type": "show_balance", "on": False}])
    bn, en = _taka(facts["user"]["balance"])
    return _plan(f"আপনার ব্যালেন্স {bn}।", f"Your balance is {en}.",
                 [{"type": "show_balance", "on": True}])


def _go_back(t, msg, req, facts):
    if _has(t, BACK) and not intent_mod.has_send_verb(t) and _amount(t) is None:
        return _plan("ঠিক আছে, আগের পেজে যাচ্ছি।", "OK, going back.", [{"type": "go_back"}])


def _navigate(t, msg, req, facts):
    if _amount(t) is not None or extract_phones(t)[0]:
        return None
    targets = [p for p, words in PAGE_WORDS.items() if _has(t, words)]
    if len(targets) != 1 or not (_has(t, NAV_VERBS) or len(t.split()) <= 3):
        return None
    target = targets[0]
    # "send money e jao" opens the page; "ammu ke send money koro" is a transfer
    if intent_mod.has_send_verb(_pattern(PAGE_WORDS[target]).sub(" ", t)):
        return None
    bn, en = _label(target)
    if req["page"].get("id") == target:
        return _plan(*_describe(req["page"], (f"আপনি এখন {bn} পেজেই আছেন। ", f"You are already on {en}. ")))
    return _plan(f"{bn} খুলছি।", f"Opening {en}.", [{"type": "navigate", "page": target}])


def _page_question(t, msg, req, facts):
    page = req["page"]
    if _has(t, THIS_PAGE):
        bn, en = _label(page.get("id"))
        return _plan(*_describe(page, (f"আপনি এখন {bn} পেজে আছেন। ", f"You are on {en}. ")))
    if _has(t, PREV_PAGE) and _has(t, QUESTION):
        recent = req.get("recent_pages") or []
        if not recent:
            return _plan("এর আগে অন্য কোনো পেজ খোলা হয়নি।", "There was no page before this one.")
        bn, en = _label(recent[0].get("id"))
        return _plan(*_describe(recent[0], (f"আগের পেজ ছিল {bn}। ", f"The previous page was {en}. ")))
    return None


def _last_command(req: dict, user: dict) -> Optional[str]:
    pages = [req["page"], *(req.get("recent_pages") or [])]
    for p in pages:
        cmd = ((p.get("content") or {}).get("command") or "").strip()
        if p.get("id") == "assistant" and cmd:
            return cmd
    for turn in reversed(req.get("history") or []):
        text = (turn.get("text") or "").strip()
        if turn.get("role") == "user" and text and normalize(text) != normalize(req["message"]) \
                and _full_command(normalize(text), user):
            return text
    return None


def _send_again(t, msg, req, facts):
    if not _has(t, AGAIN) or _full_command(t, facts["user"]):
        return None
    cmd = _last_command(req, facts["user"])
    if not cmd:
        return _plan("কোন লেনদেনটি আবার করতে চান? পুরোটা বলুন, যেমন 'আম্মুকে ৫০০ টাকা পাঠাও'।",
                     "Which transfer should I repeat? Say all of it, e.g. 'Send 500 taka to Ammu'.")
    return _plan(f"আগের লেনদেনটি আবার শুরু করছি: \"{cmd}\"। পাঠানোর আগে আবার যাচাই হবে।",
                 f"Starting the last transfer again: \"{cmd}\". It will be checked again before sending.",
                 [{"type": "start_transfer", "text": cmd[:MAX_TEXT]}])


GLOBAL_RULES = (_help, _language, _reset, _call_sim, _switch_user, _settings, _refresh,
                _balance, _page_question, _go_back, _navigate, _send_again)


def _last_agent_text(history: list[dict]) -> str:
    for turn in reversed(history or []):
        if turn.get("role") == "agent":
            return (turn.get("text") or "").strip()
    return ""


def rules(req: dict, facts: dict) -> dict:
    """The page-aware keyword router (used without an LLM, or when it fails)."""
    msg = (req.get("message") or "").strip()
    if req.get("observation") or not msg:
        return _plan("", "")
    t = normalize(msg)
    page = req["page"]

    if page.get("id") == "assistant":
        p = _send_money(t, msg, page, facts["user"])
        if p:
            return p
    for rule in GLOBAL_RULES:
        p = rule(t, msg, req, facts)
        if p:
            return p

    amount = _amount(t)
    det = intent_mod.detect(t, amount is not None)
    if det["intent"] == "unsupported":
        what_bn, what_en = {"cash_out": ("ক্যাশ আউট", "Cash out"), "pay_bill": ("বিল পে", "Pay bill"),
                            "add_money": ("অ্যাড মানি", "Add money")}.get(det["unsupported"], ("এটি", "That"))
        return _plan(f"{what_bn} এই প্রোটোটাইপে এখনো নেই। সেন্ড মানি, রিচার্জ আর ব্যালেন্স দেখা যায়।",
                     f"{what_en} is not in this prototype yet. You can send money, recharge and check your balance.")
    if det["intent"] in ("send_money", "mobile_recharge"):
        return _plan("ঠিক আছে, সেন্ড মানি পেজে যাচাই করছি।", "OK, checking it on the Send Money page.",
                     [{"type": "start_transfer", "text": msg[:MAX_TEXT]}])
    return _plan(*NOT_UNDERSTOOD)


# ---------------------------------------------------------------- safety guard
def _valid(a: dict, req: dict, facts: dict) -> Optional[dict]:
    """The action with only its checked arguments, or None to drop it."""
    t = a.get("type")
    msg = (req.get("message") or "").strip()
    offered = set(req["page"].get("actions") or [])
    if t not in GLOBAL_ACTIONS and t not in PAGE_ACTIONS:
        return None
    if t in PAGE_ACTIONS and t not in offered:
        return None
    if t in USER_WORDS_ONLY and (req.get("observation") or not msg):
        return None
    if t == "navigate":
        return {"type": t, "page": a["page"]} if a.get("page") in PAGES else None
    if t == "set_language":
        return {"type": t, "lang": a["lang"]} if a.get("lang") in ("bn", "en") else None
    if t in ("show_balance", "set_simulate_call"):
        return {"type": t, "on": a["on"]} if isinstance(a.get("on"), bool) else None
    if t == "switch_user":
        ids = {u["id"] for u in facts.get("users", [])}
        return {"type": t, "user_id": a["user_id"]} if a.get("user_id") in ids else None
    if t == "reset_demo":
        return {"type": t} if _has(normalize(msg), RESET) else None
    if t == "start_transfer":
        text = str(a.get("text") or "").strip()
        return {"type": t, "text": text} if 0 < len(text) <= MAX_TEXT else None
    if t == "select_amount":
        n = a.get("amount")
        if isinstance(n, float) and n.is_integer():
            n = int(n)
        ok = isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= MAX_AMOUNT
        return {"type": t, "amount": n} if ok else None
    if t == "select_recipient":
        if a.get("contact_id") in {c["id"] for c in facts["user"]["contacts"]}:
            return {"type": t, "contact_id": a["contact_id"]}
        phone = str(a.get("phone") or "")
        return {"type": t, "phone": phone} if PHONE_RE.match(phone) else None
    if t == "answer_interview":
        # always the user's raw words, never the model's paraphrase
        return {"type": t, "text": msg}
    return {"type": t}


def sanitize(plan: dict, req: dict, facts: dict) -> tuple[dict, bool]:
    """Apply the safety rules to a plan from either path.
    Returns (clean plan, whether anything was dropped)."""
    actions, dropped = [], False
    for a in plan.get("actions") or []:
        clean = _valid(a if isinstance(a, dict) else {}, req, facts)
        if clean is None or len(actions) >= MAX_ACTIONS:
            dropped = True
            continue
        actions.append(clean)
    out = _plan(str(plan.get("reply_bn") or "")[:600], str(plan.get("reply_en") or "")[:600],
                actions, done=bool(plan.get("done", True)) or not actions)
    return out, dropped


# ---------------------------------------------------------------- LLM path
SYSTEM_PROMPT = """You are Bolo, the voice assistant inside the Bolo upay mobile wallet
(a hackathon prototype with synthetic data). You can act on any page of the app.
The user speaks Bangla, Banglish or English. Reply briefly (one or two short
sentences, read aloud) in both Bangla (reply_bn) and English (reply_en).

You get the current page (id, step, summary, content, and `actions`: the page
actions its buttons offer right now), up to 3 recent pages (newest first), the
conversation, facts about the user and the app settings.

Actions you may return (at most 4, run in order):
Global, any page:
- navigate {page: home|dashboard|accuracy|assistant}; go_back; open_settings; refresh
- set_language {lang: bn|en}; show_balance {on}; set_simulate_call {on}
- switch_user {user_id} (only when the user asks to switch user)
- reset_demo (only when the user explicitly asks to reset the demo)
- start_transfer {text}: any send-money or recharge request; pass the user's own words.
  The Send Money page parses it, runs the scam check and asks the user to confirm.
Page actions, ONLY if listed in current_page.actions:
- select_amount {amount}; select_recipient {contact_id | phone}; clarify_continue
- answer_interview: the user's answer to a scam-check question, in their own words
- confirm; accept_suggestion; keep_amount; continue_to_pin; cancel_transfer;
  new_transaction; repeat

Safety rules (the app enforces them too):
- There is no action for entering a PIN, using biometrics, ticking the RED warning
  box or skipping a hold. Tell the user to do those by hand.
- Never ask for, repeat or accept a PIN or OTP. If the user says one, warn them.
- Never confirm a RED transfer; explain its reasons and that it is risky.
- Confirm or answer only with the user's own words: a new command on a review
  screen ("karim ke 2000 pathao") is a new transfer, not a confirmation.
- During the scam interview, pass the user's answer with answer_interview; never
  suggest or rephrase answers.
- If you don't understand, say so and give an example.

Set done=false only when you need to see the page again after your actions to tell
the user the result (e.g. after start_transfer, to read out the risk check);
otherwise done=true. On observation turns (observation=true) the user said nothing
new: briefly tell them what is on the page now; do not start or confirm anything."""


def _llm_input(req: dict, facts: dict) -> str:
    u = facts["user"]
    names = {c["phone"]: c["name"] for c in u["contacts"]}
    return json.dumps({
        "message": req.get("message") or "",
        "observation": bool(req.get("observation")),
        "user_language": "bn" if req.get("bangla", True) else "en",
        "current_page": req["page"],
        "recent_pages": req.get("recent_pages") or [],
        "conversation": req.get("history") or [],
        "settings": req.get("settings") or {},
        "facts": {
            "user": {"id": u["id"], "name": u["name"], "name_bn": u.get("name_bn"),
                     "phone": mask_phone(u["phone"]), "balance": u["balance"]},
            "contacts": [{"id": c["id"], "name": c["name"], "name_bn": c.get("name_bn"),
                          "relation": c.get("relation"), "phone": mask_phone(c["phone"])}
                         for c in u["contacts"]],
            "recent_transactions": [
                {"type": t["type"], "amount": t["amount"], "ts": t["ts"],
                 "with": names.get(t["counterparty"]) or mask_phone(t["counterparty"] or "")}
                for t in (facts.get("history") or [])[-8:]],
            "demo_users": [{"id": x["id"], "name": x["name"], "name_bn": x.get("name_bn")}
                           for x in facts.get("users", [])],
            "ops_dashboard": facts.get("ops") or {},
        },
    }, ensure_ascii=False, default=str)


# ---------------------------------------------------------------- entry point
def run(req: dict, facts: dict) -> dict:
    """One agent turn. ``facts``: user, users, history (recent transactions), ops."""
    req = {**req, "message": (req.get("message") or "").strip(),
           "recent_pages": (req.get("recent_pages") or [])[:3],
           "history": (req.get("history") or [])[-12:]}
    if req["message"] and pinguard.contains_secret(req["message"]):
        return {**_plan(*PIN_WARNING), "llm_used": False, "source": "guard"}

    plan, source = None, "rules"
    if req.get("use_llm", True) and llm.enabled():
        out = llm.structured(SYSTEM_PROMPT, _llm_input(req, facts), AgentPlan)
        if out is not None:
            plan, source = out.model_dump(exclude_none=True), "llm"
    llm_used = source == "llm"
    if plan is None:
        plan = rules(req, facts)
    clean, dropped = sanitize(plan, req, facts)
    if dropped:
        source = "guard"
        if llm_used:
            clean["reply_bn"] += GUARD_NOTE[0]
            clean["reply_en"] += GUARD_NOTE[1]
    return {**clean, "llm_used": llm_used, "source": source}
