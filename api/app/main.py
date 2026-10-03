"""Bolo upay API.

Flow used by the app:
  POST /api/parse    voice/text command -> intent, amount, recipient (or a question)
  POST /api/assess   risk check -> GREEN / YELLOW / RED (+ interview questions)
  POST /api/assess   again with the user's interview answers
  POST /api/execute  PIN / biometric -> simulated transfer
  POST /api/cancel   user cancels after a warning
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import store
from .core import features as feat_mod
from .core import llm, parser, risk, scam
from .core.text import mask_phone

ROOT = Path(__file__).resolve().parents[2]
HOLD_SECONDS = int(os.getenv("HOLD_SECONDS", "30"))
MAX_PIN_FAILURES = 3

INTERVIEW = [
    {"id": "who", "bn": "কেউ কি ফোন করে বা মেসেজ দিয়ে এই টাকা পাঠাতে বলেছে? কে বলেছে?",
     "en": "Did someone call or message you asking for this money? Who?"},
    {"id": "official", "bn": "সে কি নিজেকে উপায় অফিস, কাস্টমার কেয়ার বা কোনো অফিসের লোক বলেছে?",
     "en": "Did they say they are from upay, customer care or any office?"},
    {"id": "otp", "bn": "সে কি আপনার পিন বা ওটিপি কোড চেয়েছে? কেন টাকা পাঠাচ্ছেন?",
     "en": "Did they ask for your PIN or OTP? Why are you sending this money?"},
]

app = FastAPI(title="Bolo upay API", version="1.0.0",
              description="Voice-first Bangla payment assistant with scam shield (prototype, synthetic data).")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])


# ---------- models ----------
class ParseIn(BaseModel):
    user_id: str
    text: str = Field(min_length=1, max_length=500)
    use_llm: bool = True


class Draft(BaseModel):
    intent: Literal["send_money", "mobile_recharge"]
    amount: int = Field(gt=0, le=1_000_000)
    recipient_phone: str = Field(pattern=r"^01[3-9]\d{8}$")
    is_return_claim: bool = False
    command_text: str = ""


class AssessIn(BaseModel):
    user_id: str
    draft: Draft
    on_active_call: bool = False
    answers: list[str] = []
    now: Optional[datetime] = None  # demo/testing only: simulate time of day


class ExecuteIn(BaseModel):
    user_id: str
    assessment_id: str
    method: Literal["pin", "biometric"]
    pin: Optional[str] = Field(default=None, pattern=r"^\d{4,5}$")
    acknowledged_warning: bool = False


class CancelIn(BaseModel):
    user_id: str
    assessment_id: str


def _user_or_404(uid: str) -> dict:
    u = store.user(uid)
    if not u:
        raise HTTPException(404, "user not found")
    return u


# ---------- endpoints ----------
@app.get("/api/health")
def health():
    return {"ok": True, "llm": llm.provider() if llm.enabled() else None,
            "model": risk.model_card().get("model")}


@app.get("/api/users")
def list_users():
    return [{"id": u["id"], "name": u["name"], "name_bn": u["name_bn"], "persona": u["persona"],
             "phone": mask_phone(u["phone"])} for u in store.users()]


@app.get("/api/users/{uid}")
def get_user(uid: str):
    u = _user_or_404(uid)
    names = {c["phone"]: c for c in u["contacts"]}
    recent = []
    for t in reversed(store.history(uid)[-15:]):
        c = names.get(t["counterparty"])
        recent.append({**t, "name": c["name"] if c else ("নিজের নম্বর" if t["counterparty"] == u["phone"] else None),
                       "counterparty": mask_phone(t["counterparty"] or "")})
    return {**u, "recent": recent}


@app.post("/api/parse")
def parse(body: ParseIn):
    u = _user_or_404(body.user_id)
    return parser.parse(body.text, u, use_llm=body.use_llm)


@app.post("/api/assess")
def assess(body: AssessIn):
    u = _user_or_404(body.user_id)
    d = body.draft
    if d.amount > u["balance"]:
        return {"level": "BLOCKED", "reason": "insufficient_balance",
                "message_bn": "আপনার অ্যাকাউন্টে যথেষ্ট ব্যালেন্স নেই।",
                "message_en": "Not enough balance.", "balance": u["balance"]}
    said = " ".join([d.command_text, *body.answers])
    sc = scam.match(said)
    now = body.now.astimezone(store.TZ) if body.now else None
    feats, summary = feat_mod.compute(
        amount=d.amount, intent=d.intent, phone=d.recipient_phone,
        is_return_claim=d.is_return_claim, balance=u["balance"],
        history=store.history(u["id"]), contacts=u["contacts"],
        on_call=body.on_active_call, scam_score=sc["score"], now=now,
        self_phone=u["phone"])
    result = risk.assess(feats, summary, sc, d.amount, interviewed=bool(body.answers))
    result["features"] = feats
    result["scam_hits"] = sc["hits"]
    if result["needs_interview"]:
        result["interview"] = INTERVIEW
    if result["level"] == "RED":
        result["hold_seconds"] = HOLD_SECONDS
    draft = {**d.model_dump(), "answers": body.answers, "on_active_call": body.on_active_call}
    result["assessment_id"] = store.save_assessment(u["id"], draft, result)
    return result


@app.post("/api/execute")
def execute(body: ExecuteIn):
    u = _user_or_404(body.user_id)
    a = store.get_assessment(body.assessment_id)
    if not a or a["user_id"] != u["id"]:
        raise HTTPException(404, "assessment not found")
    if a["status"] != "open":
        raise HTTPException(409, f"assessment already {a['status']}")
    level = a["result"]["level"]
    if level == "BLOCKED":
        raise HTTPException(400, "blocked")
    # the server decides which authentication is enough, never the client
    if body.method == "biometric" and level != "GREEN":
        raise HTTPException(403, "PIN required for this transaction")
    if level == "RED":
        waited = (store.now() - datetime.fromisoformat(a["created_at"])).total_seconds()
        if waited < HOLD_SECONDS:
            raise HTTPException(425, {"code": "on_hold", "wait_seconds": int(HOLD_SECONDS - waited) + 1})
        if not body.acknowledged_warning:
            raise HTTPException(400, "warning must be acknowledged")
    if body.method == "pin":
        if not body.pin or not store.check_pin(u["id"], body.pin):
            fails = a["pin_failures"] + 1
            store.update_assessment(a["id"], pin_failures=fails,
                                    status="locked" if fails >= MAX_PIN_FAILURES else "open")
            raise HTTPException(401, {"code": "wrong_pin", "attempts_left": max(0, MAX_PIN_FAILURES - fails)})
    d = a["draft"]
    try:
        tx = store.execute_transfer(u["id"], d["intent"], d["recipient_phone"], d["amount"])
    except ValueError:
        raise HTTPException(400, "insufficient balance")
    store.update_assessment(a["id"], status="executed")
    store.log_decision(u["id"], d, a["result"], "sent")
    return {"ok": True, "transaction": tx, "level": level}


@app.post("/api/cancel")
def cancel(body: CancelIn):
    u = _user_or_404(body.user_id)
    a = store.get_assessment(body.assessment_id)
    if not a or a["user_id"] != u["id"]:
        raise HTTPException(404, "assessment not found")
    if a["status"] == "open":
        store.update_assessment(a["id"], status="cancelled")
        store.log_decision(u["id"], a["draft"], a["result"], "cancelled")
    return {"ok": True}


@app.get("/api/dashboard")
def dashboard():
    ds = store.decisions(500)
    by_level = {lv: sum(1 for d in ds if d["level"] == lv) for lv in ("GREEN", "YELLOW", "RED")}
    stopped = [d for d in ds if d["outcome"] == "cancelled" and d["level"] in ("YELLOW", "RED")]
    cats: dict[str, int] = {}
    for d in ds:
        for c in d["categories"]:
            cats[c] = cats.get(c, 0) + 1
    return {
        "total": len(ds), "by_level": by_level,
        "sent": sum(1 for d in ds if d["outcome"] == "sent"),
        "cancelled_after_warning": len(stopped),
        "amount_protected": sum(d["amount"] or 0 for d in stopped),
        "scam_categories": dict(sorted(cats.items(), key=lambda kv: -kv[1])),
        "recent": [{**d, "recipient": mask_phone(d["recipient"] or "")} for d in ds[:25]],
        "note": "Prototype data from demo sessions only.",
    }


@app.get("/api/metrics")
def metrics():
    out = {"risk_model": risk.model_card()}
    for name in ("risk_metrics", "parser_metrics"):
        p = ROOT / "model" / f"{name}.json"
        out[name] = json.loads(p.read_text()) if p.exists() else None
    return out


@app.get("/api/interview")
def interview_questions():
    return INTERVIEW


@app.post("/api/demo/reset")
def demo_reset():
    store.reset()
    return {"ok": True}


# ---------- Flutter web build (single deploy: API + app on one origin) ----------
WEB_DIR = Path(os.getenv("WEB_DIR", str(ROOT / "app" / "build" / "web")))
if WEB_DIR.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets") if (WEB_DIR / "assets").exists() else None

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = (WEB_DIR / path).resolve()
        if path and f.is_file() and WEB_DIR.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(WEB_DIR / "index.html")
