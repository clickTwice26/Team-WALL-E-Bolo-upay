"""Bolo upay API.

Flow used by the app (every call after /api/login carries its token):
  POST /api/login    PIN -> session token
  POST /api/parse    voice/text command -> intent, amount, recipient (or a question)
  POST /api/assess   risk check -> GREEN / YELLOW / RED (+ interview questions)
  POST /api/assess   again with the user's interview answers
  POST /api/execute  PIN / biometric -> simulated transfer
  POST /api/cancel   user cancels after a warning
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import auth, handoff, impact, monitor, store
from .core import agent
from .core import features as feat_mod
from .core import interview, llm, parser, risk, scam, tts
from .core.text import mask_phone

log = logging.getLogger("bolo.api")
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
app.include_router(handoff.router)
access_log = logging.getLogger("bolo.access")
if not access_log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(message)s"))
    access_log.addHandler(_h)
    access_log.setLevel(logging.INFO)
    access_log.propagate = False


@app.middleware("http")
async def request_log(request: Request, call_next):
    """One JSON log line per API request, with a request id the client also
    gets back (X-Request-ID). Only method, route, status and time are logged:
    no bodies, so no phone numbers, PINs or answers."""
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        access_log.info(json.dumps({"event": "request", "id": rid, "method": request.method,
                                    "path": request.url.path, "status": response.status_code,
                                    "ms": round((time.perf_counter() - start) * 1000, 1)}))
    response.headers["X-Request-ID"] = rid
    return response


# ---------- models ----------
class ParseIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    use_llm: bool = True


class Draft(BaseModel):
    intent: Literal["send_money", "mobile_recharge", "cash_out", "merchant_payment"]
    amount: int = Field(gt=0, le=1_000_000)
    recipient_phone: str = Field(pattern=r"^01[3-9]\d{8}$")
    is_return_claim: bool = False
    command_text: str = ""


class AssessIn(BaseModel):
    draft: Draft
    on_active_call: bool = False
    answers: list[str] = []
    now: Optional[datetime] = None  # DEMO_MODE only: simulate the time of day


class ExecuteIn(BaseModel):
    assessment_id: str
    method: Literal["pin", "biometric"]
    pin: Optional[str] = Field(default=None, pattern=r"^\d{4,5}$")
    acknowledged_warning: bool = False
    # biometric: the phone's device key signs auth.biometric_payload(...)
    signature: Optional[str] = Field(default=None, max_length=512)
    public_key: Optional[str] = Field(default=None, max_length=512)


class LoginIn(BaseModel):
    user_id: str
    pin: str = Field(pattern=r"^\d{4,5}$")


class CancelIn(BaseModel):
    assessment_id: str


class InterviewNextIn(BaseModel):
    assessment_id: str
    asked: list[str] = Field(default=[], max_length=10)   # question ids already asked
    answers: list[str] = Field(default=[], max_length=10)


class FeedbackIn(BaseModel):
    assessment_id: str
    kind: Literal["wrong_warning"]


class SwitchIn(BaseModel):
    user_id: str


class DeviceIn(BaseModel):
    public_key: str = Field(min_length=40, max_length=512)  # base64 DER, P-256


class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=tts.MAX_CHARS)


class AgentPage(BaseModel):
    """What one page shows right now, as the app describes it."""
    id: str = Field(max_length=40)
    step: Optional[str] = Field(default=None, max_length=40)
    summary_bn: str = Field(default="", max_length=3000)
    summary_en: str = Field(default="", max_length=3000)
    content: dict = {}
    actions: list[str] = []  # page actions its buttons offer right now


class AgentTurn(BaseModel):
    role: Literal["user", "agent"]
    text: str = Field(default="", max_length=2000)


class AgentIn(BaseModel):
    message: str = Field(default="", max_length=500)
    page: AgentPage
    recent_pages: list[AgentPage] = []  # newest first, without the current page
    history: list[AgentTurn] = []
    bangla: bool = True
    settings: dict = {}
    observation: bool = False  # automatic follow-up after the app ran the actions
    use_llm: bool = True


def _user_or_404(uid: str) -> dict:
    u = store.user(uid)
    if not u:
        raise HTTPException(404, "user not found")
    return u


# ---------- endpoints ----------
@app.get("/api/health")
def health():
    return {"ok": True, "llm": llm.provider() if llm.enabled() else None,
            "tts": tts.enabled(), "model": risk.model_card().get("model")}


@app.post("/api/tts")
def text_to_speech(body: TTSIn, s: auth.Session = Depends(auth.current)):
    """Natural server voice (Gemini TTS). The app falls back to the device voice."""
    if not tts.enabled():
        raise HTTPException(503, "tts_disabled")
    try:
        wav = tts.synthesize(body.text)
    except Exception as e:  # network, quota, or no audio returned
        log.warning("TTS failed: %s", e)
        raise HTTPException(502, "tts_failed")
    return Response(wav, media_type="audio/wav")


@app.get("/api/users")
def list_users():
    """Demo persona picker. Only on a demo site (DEMO_MODE=true)."""
    if not auth.demo_mode():
        raise HTTPException(404, "not found")
    return [{"id": u["id"], "name": u["name"], "name_bn": u["name_bn"], "persona": u["persona"],
             "phone": mask_phone(u["phone"])} for u in store.users()]


@app.get("/api/me")
def me(s: auth.Session = Depends(auth.current)):
    """The signed-in user's own profile, contacts and recent transactions."""
    u, uid = s.user, s.user["id"]
    names = {c["phone"]: c for c in u["contacts"]}
    recent = []
    for t in reversed(store.history(uid)[-15:]):
        c = names.get(t["counterparty"])
        recent.append({**t, "name": c["name"] if c else ("নিজের নম্বর" if t["counterparty"] == u["phone"] else None),
                       "counterparty": mask_phone(t["counterparty"] or "")})
    return {**u, "recent": recent}


@app.post("/api/login")
def login(body: LoginIn):
    """PIN unlock -> session token (synthetic users, demo PIN 1234).
    Wrong PINs count per account; too many lock it (423)."""
    if not store.user(body.user_id):
        raise HTTPException(401, {"code": "wrong_pin"})
    auth.check_pin(body.user_id, body.pin)
    return {"ok": True, "token": auth.issue(body.user_id), "expires_in": auth.SESSION_MINUTES * 60}


@app.post("/api/demo/switch")
def demo_switch(body: SwitchIn, s: auth.Session = Depends(auth.current)):
    """Demo site only: a session for another demo persona without its PIN."""
    if not auth.demo_mode():
        raise HTTPException(404, "not found")
    _user_or_404(body.user_id)
    return {"ok": True, "token": auth.issue(body.user_id, amr="demo_switch"),
            "expires_in": auth.SESSION_MINUTES * 60}


@app.post("/api/devices")
def register_device(body: DeviceIn, s: auth.Session = Depends(auth.current)):
    """Register the phone's biometric-protected signing key (after a PIN login)."""
    if s.claims.get("amr") != "pin":
        raise HTTPException(403, {"code": "pin_login_required"})
    try:
        auth.load_device_key(body.public_key)
    except ValueError:
        raise HTTPException(422, {"code": "bad_public_key"})
    kid = auth.key_id(body.public_key)
    store.register_device(s.user["id"], kid, body.public_key)
    return {"ok": True, "key_id": kid}


@app.post("/api/parse")
def parse(body: ParseIn, s: auth.Session = Depends(auth.current)):
    return parser.parse(body.text, s.user, use_llm=body.use_llm)


@app.post("/api/assess")
def assess(body: AssessIn, s: auth.Session = Depends(auth.current)):
    u = s.user
    d = body.draft
    if d.amount > u["balance"]:
        return {"level": "BLOCKED", "reason": "insufficient_balance",
                "message_bn": "আপনার অ্যাকাউন্টে যথেষ্ট ব্যালেন্স নেই।",
                "message_en": "Not enough balance.", "balance": u["balance"]}
    sc = scam.match_many([d.command_text, *body.answers])
    now = body.now.astimezone(store.TZ) if body.now and auth.demo_mode() else None
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
        # adaptive: the first question follows this payment's strongest risk signal;
        # /api/interview/next picks each follow-up from the answers so far
        result["interview"] = [interview.first(feats, d.model_dump())]
        result["interview_mode"] = "adaptive"
        result["interview_max"] = interview.bank()["max_questions"]
    if result["level"] == "RED":
        result["hold_seconds"] = HOLD_SECONDS
    if result["level"] == "GREEN":
        # one-time challenge the phone signs if the user approves with biometrics
        result["bio_challenge"] = secrets.token_urlsafe(24)
    draft = {**d.model_dump(), "answers": body.answers, "on_active_call": body.on_active_call}
    result["assessment_id"] = store.save_assessment(u["id"], draft, result)
    return result


@app.post("/api/execute")
def execute(body: ExecuteIn, s: auth.Session = Depends(auth.current)):
    u = s.user
    auth.ensure_unlocked(u["id"])
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
    if body.method == "biometric":
        # the server checks the phone's signature; it never trusts "biometric: ok"
        challenge = a["result"].get("bio_challenge")
        if not (challenge and body.signature and body.public_key):
            raise HTTPException(403, {"code": "biometric_proof_required"})
        err = auth.verify_device_signature(u["id"], body.public_key,
                                           auth.biometric_payload(a["id"], challenge), body.signature)
        if err:
            raise HTTPException(403, {"code": err})
    if level == "RED":
        waited = (store.now() - datetime.fromisoformat(a["created_at"])).total_seconds()
        if waited < HOLD_SECONDS:
            raise HTTPException(425, {"code": "on_hold", "wait_seconds": int(HOLD_SECONDS - waited) + 1})
        if not body.acknowledged_warning:
            raise HTTPException(400, "warning must be acknowledged")
    if body.method == "pin":
        try:
            auth.check_pin(u["id"], body.pin)  # 423 when the account is locked
        except HTTPException as e:
            if e.status_code != 401:
                raise
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
def cancel(body: CancelIn, s: auth.Session = Depends(auth.current)):
    u = s.user
    a = store.get_assessment(body.assessment_id)
    if not a or a["user_id"] != u["id"]:
        raise HTTPException(404, "assessment not found")
    if a["status"] == "open":
        store.update_assessment(a["id"], status="cancelled")
        store.log_decision(u["id"], a["draft"], a["result"], "cancelled")
    return {"ok": True}


@app.post("/api/feedback")
def feedback(body: FeedbackIn, s: auth.Session = Depends(auth.current)):
    """The user says a warning was wrong. It never changes the transfer; it is a
    label for threshold reviews and retraining (see docs/FAILURE_POLICY.md)."""
    a = store.get_assessment(body.assessment_id)
    if not a or a["user_id"] != s.user["id"]:
        raise HTTPException(404, "assessment not found")
    level = a["result"].get("level")
    if level not in ("YELLOW", "RED"):
        raise HTTPException(409, {"code": "not_a_warning"})
    store.add_feedback(a["id"], s.user["id"], body.kind, level)
    return {"ok": True}


@app.get("/api/impact", dependencies=[Depends(auth.demo_user_or_admin)])
def impact_simulation(transfers: int = 1000, prevalence: float = 0.01):
    """Per N transfers: scams flagged, held and stopped, Tk protected, honest
    users warned, and disputes avoided, at a chosen scam prevalence.
    A simulation on synthetic data with explicit assumptions, not real results."""
    if not (1 <= transfers <= 100_000_000) or not (0.0001 <= prevalence <= 0.5):
        raise HTTPException(422, "transfers 1..100,000,000 and prevalence 0.0001..0.5")
    return impact.simulate(transfers, prevalence)


@app.get("/api/admin/monitor", dependencies=[Depends(auth.demo_user_or_admin)])
def model_health(days: int = 14):
    """Drift, level mix, overrides, wrong-warning reports and support load."""
    return monitor.report(max(1, min(days, 90)))


@app.post("/api/agent")
def agent_turn(body: AgentIn, s: auth.Session = Depends(auth.current)):
    """Bolo agent: replies and app actions for what the user said on any page."""
    u = s.user
    demo = auth.demo_mode()
    d = _dashboard_data()
    facts = {"user": u, "demo": demo,
             # other users and the ops numbers exist only on a demo site
             "users": store.users() if demo else [],
             "history": store.history(u["id"])[-8:],
             "ops": {k: d[k] for k in ("total", "by_level", "sent", "cancelled_after_warning",
                                       "amount_protected", "scam_categories")} if demo else {}}
    return agent.run(body.model_dump(), facts)


@app.get("/api/dashboard", dependencies=[Depends(auth.demo_user_or_admin)])
def dashboard():
    return _dashboard_data()


def _dashboard_data() -> dict:
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
    for name in ("risk_metrics", "parser_metrics", "sequence_metrics"):
        p = ROOT / "model" / f"{name}.json"
        out[name] = json.loads(p.read_text()) if p.exists() else None
    return out


@app.get("/api/interview")
def interview_questions():
    """The fallback question list (the app asks adaptively via /api/interview/next)."""
    return INTERVIEW


@app.post("/api/interview/next")
def interview_next(body: InterviewNextIn, s: auth.Session = Depends(auth.current)):
    a = store.get_assessment(body.assessment_id)
    if not a or a["user_id"] != s.user["id"]:
        raise HTTPException(404, "assessment not found")
    q = interview.next_question(body.asked, body.answers)
    return {"done": q is None, "question": q}


@app.post("/api/demo/reset", dependencies=[Depends(auth.demo_user_or_admin)])
def demo_reset():
    store.reset()
    return {"ok": True}


# ---------- Flutter web build (single deploy: API + app on one origin) ----------
WEB_DIR = Path(os.getenv("WEB_DIR", str(ROOT / "app" / "build" / "web")))
# Cloudflare adds a 4-hour browser cache to responses without Cache-Control,
# so a redeploy would not show. "no-cache" makes browsers revalidate (ETag).
NO_CACHE = {"Cache-Control": "no-cache"}


def _static(base: Path, path: str, request: Request) -> Response:
    """A file inside ``base``, or its index.html (client-side routes)."""
    f = (base / path).resolve()
    if not (path and f.is_file() and base.resolve() in f.parents):
        f = base / "index.html"
    resp = FileResponse(f, headers=NO_CACHE, stat_result=os.stat(f))
    if request.headers.get("if-none-match") == resp.headers["etag"]:
        return Response(status_code=304, headers={**NO_CACHE, "etag": resp.headers["etag"]})
    return resp


# support console: a second Flutter entrypoint built with --base-href /console/
CONSOLE_DIR = Path(os.getenv("CONSOLE_DIR", str(ROOT / "app" / "build" / "console")))
if CONSOLE_DIR.exists():
    @app.get("/console", include_in_schema=False)
    @app.get("/console/{path:path}", include_in_schema=False)
    def console_app(request: Request, path: str = ""):
        return _static(CONSOLE_DIR, path, request)

if WEB_DIR.exists():
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str, request: Request):
        if path.startswith("api/"):  # an API route that does not exist, not a page
            raise HTTPException(404, "not found")
        return _static(WEB_DIR, path, request)
