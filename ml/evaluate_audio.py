"""Evaluate real Bangla speech: STT + parser on what people actually said (R1).

Run:  python ml/evaluate_audio.py data/eval_logs/*.json            (study logs from the app)
      python ml/evaluate_audio.py data/eval_sample/audio_log_SAMPLE.json
      python ml/evaluate_audio.py LOGS... --reparse                (re-run today's rule parser
                                                                    on the same transcripts)

Input: the JSON files the app's evaluation mode exports (transcript, STT
confidence and parse result per prompt; never audio). Output:
model/audio_metrics.json (or --out PATH) with WER and CER (jiwer), intent,
amount and recipient accuracy, the clarification rate and the silent wrong
amount / recipient rate, overall and by condition, dialect, age band and gender.

The number that matters most is silent_wrong_amount_rate: a wrong amount the
app would show without stopping to ask. Target: <= 1% (docs/AUDIO_EVAL.md).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import jiwer

ROOT = Path(__file__).resolve().parents[1]
ASK_STATUSES = {"clarify_amount", "need_amount", "clarify_recipient", "need_recipient", "confirm_recipient"}
MONEY_INTENTS = {"send_money", "mobile_recharge", "cash_out"}
TARGET_SILENT_WRONG_AMOUNT = 0.01
MIN_SPEAKERS = 12
CONDITIONS = ("quiet", "street", "bus_tv")
_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def normalize(text: str) -> str:
    """Compare words, not formatting: NFC, Bangla digits -> ASCII, no
    thousands separators or punctuation, lower case."""
    t = unicodedata.normalize("NFC", text or "").translate(_BN_DIGITS).lower()
    t = re.sub(r"(?<=\d)[,.](?=\d{3}\b)", "", t)          # 1,500 -> 1500
    t = re.sub(r"[।,.!?;:\"'()\[\]\-–—+]", " ", t)
    return " ".join(t.split())


def load(paths: list[Path]) -> tuple[list[dict], bool]:
    """Flatten exported sessions into one row per spoken prompt. Only the last
    attempt counts (the facilitator repeats a prompt only when the speaker
    misread it); typed test rows and skips are left out."""
    rows, sample = [], False
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        sample = sample or bool(data.get("sample"))
        for s in data.get("sessions", []):
            meta = {k: s.get(k) for k in ("participant", "age_band", "gender", "dialect", "condition")}
            last: dict[str, dict] = {}
            for r in s.get("records", []):
                if r.get("input", "voice") != "voice" or r.get("skipped"):
                    continue
                prev = last.get(r["prompt_id"])
                if prev is None or r.get("attempt", 1) >= prev.get("attempt", 1):
                    last[r["prompt_id"]] = r
            rows += [{**meta, **r, "source": p.name} for r in last.values()]
    return rows, sample


def reparse(rows: list[dict]) -> None:
    """Replace the logged parse with today's rule parser on the same transcript,
    to check a parser fix against real speech without new recordings."""
    sys.path.insert(0, str(ROOT / "api"))
    from app.core.parser import parse  # noqa: E402
    seed = json.loads((ROOT / "data" / "seed.json").read_text(encoding="utf-8"))
    user = {u["id"]: u for u in seed["users"]}["u1"]
    for r in rows:
        p = parse(r.get("transcript") or " ", user, use_llm=False)
        rec = (p["recipient"] or {}).get("id") or p["new_number"]
        r["parse"] = {"status": p["status"], "intent": p["intent"], "amount": p["amount"],
                      "recipient": rec, "llm_used": False}


def judge(r: dict) -> dict:
    """One row against its labels. Same rules as ml/evaluate_parser.py, plus
    two that only exist with speech: unsure STT (confidence < 0.6) makes the
    user check the words, so it is never silent; and a fuzzy name ("cX?")
    may also come back exact, since spoken spelling variants sound the same."""
    exp, got = r.get("expected") or {}, r.get("parse") or {}
    status, unsure = got.get("status"), bool(r.get("unsure"))
    asked = status in ASK_STATUSES or unsure
    out = {"intent_ok": got.get("intent") == exp.get("intent"), "asked": asked}

    if exp.get("intent") in MONEY_INTENTS:
        e, g = exp.get("amount"), got.get("amount")
        out["amount_ok"] = (g is None and status in ASK_STATUSES) if e is None else g == e
        wrong = g is not None and g != e   # includes "picked one" where it had to ask
        out["wrong_amount"] = wrong
        out["silent_wrong_amount"] = wrong and not unsure

    e = exp.get("recipient")
    if exp.get("intent") in ("send_money", "mobile_recharge") and e is not None:
        g = got.get("recipient")
        if e == "ask":
            out["recipient_ok"] = status in ("clarify_recipient", "need_recipient", "clarify_amount", "need_amount")
            out["silent_wrong_recipient"] = status == "ok" and g is not None and not unsure
        else:
            want = e.rstrip("?")
            out["recipient_ok"] = g == want
            out["silent_wrong_recipient"] = g is not None and g != want and status == "ok" and not unsure
    return out


def _rate(xs: list[bool]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def metrics(rows: list[dict]) -> dict:
    judged = [(r, judge(r)) for r in rows]
    refs = [(normalize(r["reference"]), normalize(r.get("transcript", ""))) for r in rows if r.get("reference")]
    refs = [(a, b) for a, b in refs if a]
    conf = [r["confidence"] for r in rows if r.get("has_confidence") and r.get("confidence") is not None]
    col = lambda k: [j[k] for _, j in judged if k in j]  # noqa: E731
    return {
        "utterances": len(rows),
        "speakers": len({r.get("participant") for r in rows}),
        "wer": round(jiwer.wer([a for a, _ in refs], [b for _, b in refs]), 4) if refs else None,
        "cer": round(jiwer.cer([a for a, _ in refs], [b for _, b in refs]), 4) if refs else None,
        "intent_accuracy": _rate(col("intent_ok")),
        "amount_accuracy": _rate(col("amount_ok")),
        "recipient_accuracy": _rate(col("recipient_ok")),
        "clarification_rate": _rate(col("asked")),
        "wrong_amount_rate": _rate(col("wrong_amount")),
        "silent_wrong_amount_rate": _rate(col("silent_wrong_amount")),
        "silent_wrong_recipient_rate": _rate(col("silent_wrong_recipient")),
        "stt_unsure_rate": _rate([bool(r.get("unsure")) for r in rows]),
        "mean_confidence": round(sum(conf) / len(conf), 3) if conf else None,
    }


def by(rows: list[dict], key: str) -> dict:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(str(r.get(key) or "unknown"), []).append(r)
    return {k: metrics(v) for k, v in sorted(groups.items())}


def failures(rows: list[dict], limit: int = 25) -> list[dict]:
    """Silent wrong amounts/recipients first: what to fix in numbers.py and the alias lists."""
    out = []
    for r in rows:
        j = judge(r)
        bad = [k for k in ("silent_wrong_amount", "silent_wrong_recipient") if j.get(k)]
        bad += [k for k in ("intent_ok", "amount_ok", "recipient_ok") if j.get(k) is False]
        if bad:
            out.append({"prompt_id": r["prompt_id"], "reference": r.get("reference"),
                        "transcript": r.get("transcript"), "confidence": r.get("confidence"),
                        "expected": r.get("expected"), "parse": r.get("parse"), "problems": bad,
                        **{k: r.get(k) for k in ("participant", "condition", "dialect")}})
    out.sort(key=lambda f: not any(p.startswith("silent") for p in f["problems"]))
    return out[:limit]


def main(paths: list[Path], out: Path | None = None, redo_parse: bool = False) -> dict:
    rows, sample = load(paths)
    if redo_parse:
        reparse(rows)
    speakers: dict[str, set] = {}
    for r in rows:
        speakers.setdefault(r.get("participant"), set()).add(r.get("condition"))
    full = sum(1 for c in speakers.values() if set(CONDITIONS) <= c)
    overall = metrics(rows)
    swa = overall["silent_wrong_amount_rate"]
    result = {
        "sample": sample,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": sorted(p.name for p in paths),
        "reparsed": redo_parse,
        "design": {"speakers": len(speakers), "speakers_all_conditions": full,
                   "min_speakers": MIN_SPEAKERS, "conditions": list(CONDITIONS),
                   "meets_design": full >= MIN_SPEAKERS},
        "target": {"silent_wrong_amount_max": TARGET_SILENT_WRONG_AMOUNT,
                   "met": swa is not None and swa <= TARGET_SILENT_WRONG_AMOUNT},
        "overall": overall,
        "by_condition": by(rows, "condition"),
        "by_dialect": by(rows, "dialect"),
        "by_age": by(rows, "age_band"),
        "by_gender": by(rows, "gender"),
        "failures": failures(rows),
        "note": ("SAMPLE: synthetic log made up to test the pipeline, not real results."
                 if sample else
                 "Real speech from the study in docs/AUDIO_EVAL.md, recognised on the phone (no audio kept)."),
    }
    out = out or ROOT / "model" / "audio_metrics.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("logs", nargs="+", type=Path, help="JSON files exported by the app's evaluation mode")
    ap.add_argument("--out", type=Path, help="default: model/audio_metrics.json")
    ap.add_argument("--reparse", action="store_true", help="re-run the current rule parser on the transcripts")
    a = ap.parse_args()
    m = main(a.logs, a.out, a.reparse)
    print(json.dumps({k: m[k] for k in ("sample", "design", "target", "overall")}, ensure_ascii=False, indent=2))
    for c, v in m["by_condition"].items():
        print(f"{c:10s} WER {v['wer']}  amount {v['amount_accuracy']}  silent wrong amount {v['silent_wrong_amount_rate']}")
