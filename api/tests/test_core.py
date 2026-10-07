import json
from pathlib import Path

import pytest

from app.core import scam
from app.core.numbers import parse_amount
from app.core.parser import parse
from app.core.text import extract_phones, normalize, tokens

ROOT = Path(__file__).resolve().parents[2]
USERS = {u["id"]: u for u in json.loads((ROOT / "data" / "seed.json").read_text("utf-8"))["users"]}


def amount(text):
    _, rest = extract_phones(normalize(text))
    return parse_amount(tokens(rest))


@pytest.mark.parametrize("text,expected", [
    ("500 taka", 500), ("৫০০ টাকা", 500), ("1,500 tk", 1500), ("1,00,000 taka", 100000),
    ("5k", 5000), ("1.5k", 1500), ("দেড় হাজার", 1500), ("আড়াইশো", 250),
    ("সাড়ে তিন হাজার", 3500), ("পৌনে দুই হাজার", 1750), ("দুই হাজার পাঁচশো", 2500),
    ("এক লাখ বিশ হাজার", 120000), ("pach hajar", 5000), ("der hajar", 1500),
    ("sare tin hajar", 3500), ("duisho taka", 200), ("two thousand five hundred", 2500),
    ("৫০০টাকা", 500),
])
def test_amounts(text, expected):
    assert amount(text)["amount"] == expected


@pytest.mark.parametrize("text", ["500 1000 pathao", "ammu ke 500, 1000"])
def test_two_amounts_are_ambiguous(text):
    r = amount(text)
    assert r["amount"] is None and r["ambiguous"]


def test_lone_k_is_not_thousand():
    assert amount("ammu k 500")["amount"] == 500


def test_phone_is_not_amount():
    phones, rest = extract_phones(normalize("01712345678 e 500 taka"))
    assert phones == ["01712345678"]
    assert parse_amount(tokens(rest))["amount"] == 500


def test_bangla_digit_phone():
    phones, _ = extract_phones(normalize("০১৭১২৩৪৫৬৭৮ নম্বরে"))
    assert phones == ["01712345678"]


def test_scam_phrase_and_negation():
    assert scam.match("upay office theke phone dise")["hits"][0]["category"] == "fake_official"
    assert any(h["category"] == "pin_otp_request" for h in scam.match("otp ta chaise")["hits"])
    assert scam.match("keu otp chay nai")["score"] == 0


def test_ambiguous_contact_asks():
    r = parse("rahim ke 500 taka pathao", USERS["u1"], use_llm=False)
    assert r["status"] == "clarify_recipient"
    assert {c["id"] for c in r["recipient_candidates"]} == {"c2", "c3"}


def test_longest_alias_wins():
    r = parse("রহিম ভাইকে ৫০০ টাকা", USERS["u1"], use_llm=False)
    assert r["status"] == "ok" and r["recipient"]["id"] == "c2"


def test_fuzzy_name_needs_confirmation():
    r = parse("rohim bhai ke 500", USERS["u1"], use_llm=False)
    assert r["status"] == "confirm_recipient" and r["recipient"]["id"] == "c2"


def test_parser_test_set_has_no_silent_wrong_amount():
    import sys
    sys.path.insert(0, str(ROOT / "ml"))
    from evaluate_parser import main
    m = main(use_llm=False)
    assert m["silent_wrong_amount_rate"] == 0
    assert m["silent_wrong_recipient_rate"] == 0


def test_money_mule_phrases():
    for text in ("commission pabo bolse, onno number e pathate hobe", "অনলাইনে কাজ, কমিশন দেবে বলেছে",
                 "they said forward the money for a commission"):
        assert [h["category"] for h in scam.match(text)["hits"]] == ["money_mule"], text


def test_negation_also_stops_a_fuzzy_match():
    # "commission dibe" is negated; the near-identical "commission debe" must not sneak in
    assert scam.match("keu commission dibe na")["score"] == 0
    assert scam.match("costomer care theke bolse")["hits"][0]["category"] == "fake_official"  # misspelling still caught
