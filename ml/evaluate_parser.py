"""Evaluate the command parser on the labelled test set.

Run:  python ml/evaluate_parser.py           (rule parser only)
      LLM_PROVIDER=... LLM_API_KEY=... python ml/evaluate_parser.py --llm

Writes model/parser_metrics.json. The most important number is
silent_wrong_amount_rate: how often the app would show a wrong amount
without asking. The target is 0.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from app.core.parser import parse  # noqa: E402

ASK_STATUSES = {"clarify_amount", "need_amount", "clarify_recipient", "need_recipient",
                "confirm_recipient"}
# payments whose amount and payee are checked (app/test/parser_parity_test.dart uses the same rules)
MONEY_INTENTS = ("send_money", "mobile_recharge", "cash_out", "merchant_payment", "bill_payment")


def recipient_of(r: dict):
    if r["recipient"]:
        return r["recipient"]["id"]
    return r["new_number"]


def main(use_llm: bool = False) -> dict:
    seed = json.loads((ROOT / "data" / "seed.json").read_text(encoding="utf-8"))
    users = {u["id"]: u for u in seed["users"]}
    tests = json.loads((ROOT / "data" / "test_commands.json").read_text(encoding="utf-8"))["commands"]

    n = len(tests)
    intent_ok = amount_ok = amount_n = silent_wrong_amount = 0
    rec_ok = rec_n = silent_wrong_recipient = 0
    end_to_end = 0
    failures = []
    for t in tests:
        r = parse(t["text"], users[t["user"]], use_llm=use_llm)
        asked = r["status"] in ASK_STATUSES
        i_ok = r["intent"] == t["intent"]
        intent_ok += i_ok

        a_ok = True
        if t["intent"] in MONEY_INTENTS:
            amount_n += 1
            if t["amount"] is None:
                a_ok = r["amount"] is None and asked
            else:
                a_ok = r["amount"] == t["amount"]
                if r["amount"] is not None and r["amount"] != t["amount"]:
                    silent_wrong_amount += 1
            amount_ok += a_ok

        r_ok = True
        if t["intent"] in MONEY_INTENTS and t["recipient"] is not None:
            rec_n += 1
            exp = t["recipient"]
            got = recipient_of(r)
            if exp == "ask":
                r_ok = r["status"] in ("clarify_recipient", "need_recipient", "clarify_amount", "need_amount")
            elif exp.endswith("?"):
                r_ok = got == exp[:-1] and r["status"] in ("confirm_recipient", "clarify_amount", "need_amount")
            else:
                r_ok = got == exp
                if got is not None and got != exp and r["status"] == "ok":
                    silent_wrong_recipient += 1
            rec_ok += r_ok

        all_ok = i_ok and a_ok and r_ok
        end_to_end += all_ok
        if not all_ok:
            failures.append({"id": t["id"], "text": t["text"], "expected": {
                "intent": t["intent"], "amount": t["amount"], "recipient": t["recipient"]},
                "got": {"intent": r["intent"], "amount": r["amount"],
                        "recipient": recipient_of(r), "status": r["status"]}})

    errors = n - end_to_end
    unsafe = silent_wrong_amount + silent_wrong_recipient
    metrics = {
        "test_set_size": n,
        "llm_used": use_llm,
        "intent_accuracy": round(intent_ok / n, 4),
        "amount_accuracy": round(amount_ok / amount_n, 4) if amount_n else None,
        "recipient_accuracy": round(rec_ok / rec_n, 4) if rec_n else None,
        "end_to_end_accuracy": round(end_to_end / n, 4),
        "silent_wrong_amount_rate": round(silent_wrong_amount / amount_n, 4) if amount_n else None,
        "silent_wrong_recipient_rate": round(silent_wrong_recipient / rec_n, 4) if rec_n else None,
        "safe_failure_rate": round((errors - unsafe) / errors, 4) if errors else 1.0,
        "failures": failures,
        "note": "Test commands were written by the team (Bangla, Banglish, English, Bangla "
                "digits, number words, phone numbers, ambiguous names and amounts). "
                "Real user speech will be messier; collecting real commands is the next step.",
    }
    (ROOT / "model" / "parser_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
    return metrics


if __name__ == "__main__":
    m = main(use_llm="--llm" in sys.argv)
    print(json.dumps({k: v for k, v in m.items() if k != "failures"}, indent=2))
    for f in m["failures"]:
        print("FAIL", f)
