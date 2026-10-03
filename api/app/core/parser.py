"""Command parser: rule path + optional LLM path + cross-check.

Output ``status`` tells the app what to do next:
  ok                - everything understood, go to risk check + confirmation
  clarify_amount    - amount missing, ambiguous or the two paths disagree
  clarify_recipient - two or more contacts match, user must pick
  need_recipient    - no recipient found
  confirm_recipient - recipient found by fuzzy match, user must confirm
  unsupported       - action not supported in this prototype (cash out, bills)
  unknown           - could not understand
The parser never guesses an amount or a person.
"""
from __future__ import annotations

from . import contacts as contacts_mod
from . import intent as intent_mod
from . import llm
from .numbers import parse_amount
from .text import extract_phones, normalize, tokens

QUESTIONS = {
    "clarify_amount": ("কত টাকা পাঠাবেন? সঠিক পরিমাণটি বেছে নিন।",
                       "How much? Please choose the correct amount."),
    "need_amount": ("কত টাকা? পরিমাণটি বলুন।", "How much? Please say the amount."),
    "clarify_recipient": ("কাকে পাঠাবেন? একজনকে বেছে নিন।",
                          "Who should receive it? Please pick one."),
    "need_recipient": ("কাকে পাঠাবেন? নাম বা নম্বর বলুন।",
                       "Who should receive it? Say a name or number."),
    "confirm_recipient": ("আপনি কি এই ব্যক্তিকে বোঝাচ্ছেন?", "Did you mean this person?"),
    "unsupported": ("এই প্রোটোটাইপে এখন শুধু সেন্ড মানি, রিচার্জ ও ব্যালেন্স দেখা যায়।",
                    "This prototype supports Send Money, Recharge and Balance only."),
    "unknown": ("দুঃখিত, বুঝতে পারিনি। আবার বলুন, যেমন: আম্মুকে ৫০০ টাকা পাঠাও।",
                "Sorry, I didn't understand. Try: \"Ammu ke 500 taka pathao\"."),
}


def _contact_out(c: dict | None) -> dict | None:
    if not c:
        return None
    return {k: c.get(k) for k in ("id", "name", "name_bn", "phone", "relation")}


def parse(text: str, user: dict, use_llm: bool = True) -> dict:
    norm = normalize(text)
    phones, rest = extract_phones(norm)
    toks = tokens(rest)
    amt = parse_amount(toks)
    det = intent_mod.detect(norm, amt["amount"] is not None or amt["ambiguous"])

    rule = {"intent": det["intent"], "amount": amt["amount"],
            "amount_candidates": amt["candidates"], "phones": phones}

    llm_out = llm.extract(text) if use_llm else None
    agreement = None
    intent = det["intent"]
    amount = amt["amount"]
    candidates = list(amt["candidates"])
    if llm_out is not None:
        llm_amount = llm_out.amount
        same_intent = llm_out.intent == det["intent"]
        same_amount = llm_amount == amount
        agreement = {"intent": same_intent, "amount": same_amount}
        if not same_amount:
            # disagreement -> ask with both readings, never pick one silently
            for v in (amount, llm_amount):
                if v and v not in candidates:
                    candidates.append(v)
            amount = None
        if not same_intent and det["intent"] == "unknown" and llm_out.confidence >= 0.8:
            intent = llm_out.intent
        if not phones and llm_out.phone and len(llm_out.phone) == 11:
            phones = [llm_out.phone]

    result = {
        "text": text,
        "normalized": norm,
        "intent": intent,
        "amount": amount,
        "amount_candidates": sorted(candidates),
        "is_return_claim": det["is_return_claim"],
        "recipient": None,
        "recipient_match": None,
        "recipient_candidates": [],
        "new_number": None,
        "unsupported": det["unsupported"],
        "parsers": {"rule": rule,
                    "llm": llm_out.model_dump() if llm_out else None,
                    "llm_used": llm_out is not None,
                    "agreement": agreement},
    }

    def done(status: str) -> dict:
        result["status"] = status
        q = QUESTIONS.get(status)
        result["question_bn"], result["question_en"] = q if q else (None, None)
        return result

    if intent == "unsupported":
        return done("unsupported")
    if intent == "unknown":
        return done("unknown")
    if intent == "check_balance":
        return done("ok")

    # recipient
    rec_tokens = toks
    if llm_out and llm_out.recipient_text:
        rec_tokens = toks + tokens(normalize(llm_out.recipient_text))
    rec = contacts_mod.resolve(rec_tokens, phones, user["contacts"], user["phone"])
    if rec["status"] == "found":
        result["recipient"] = _contact_out(rec["contact"])
        result["recipient_match"] = rec["match"]
    elif rec["status"] == "new_number":
        result["new_number"] = rec["phone"]
        result["recipient_match"] = "new_number"
    elif rec["status"] == "self" or (intent == "mobile_recharge" and det["self_target"]
                                     and rec["status"] == "none"):
        result["recipient"] = {"id": "self", "name": user["name"], "name_bn": user.get("name_bn"),
                               "phone": user["phone"], "relation": "self"}
        result["recipient_match"] = "self"
    elif rec["status"] == "ambiguous":
        result["recipient_candidates"] = [_contact_out(c) if c.get("id") else c
                                          for c in rec["candidates"]]

    if amount is None:
        return done("clarify_amount" if candidates else "need_amount")
    if rec["status"] == "ambiguous":
        return done("clarify_recipient")
    if result["recipient"] is None and result["new_number"] is None:
        return done("need_recipient")
    if result["recipient_match"] == "fuzzy":
        return done("confirm_recipient")
    return done("ok")
