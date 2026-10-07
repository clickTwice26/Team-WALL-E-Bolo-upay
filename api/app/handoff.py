"""Human handoff and the support console.

The agent connects a customer to a person when they ask for one, report a
scam or lost money, or the bot fails twice. Staff answer from /console.
Staff can only protect money (stop a pending transfer): no route sends
money, approves a held transfer, or reads or changes a PIN. A PIN or OTP
typed into the chat is masked before it is stored, so staff never see it.

Customers are identified by their session token. Staff sign in to named
accounts (CONSOLE_STAFF="Mitu:<password or bcrypt hash>,Rafi:...") and every
console call carries a staff token, so the name shown to customers and stored
on a chat is the signed-in account, not something the browser sends. Without
CONSOLE_STAFF a single shared CONSOLE_TOKEN still works, and the public default
code ("support-demo") is accepted only on a demo site.
"""
from __future__ import annotations

import hmac
import logging
import os
from datetime import datetime, timedelta
from typing import Literal

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import auth, store, wallet
from .core import pinguard
from .core.text import mask_phone

router = APIRouter()
log = logging.getLogger("bolo.console")
DEFAULT_CODE = "support-demo"
STAFF_MINUTES = int(os.getenv("STAFF_SESSION_MINUTES", "480"))

CATEGORIES = ("scam", "money_lost", "dispute", "talk_to_human", "not_understood", "other")
PRIORITY_ORDER = {"urgent": 0, "high": 1, "normal": 2}
STATUS_ORDER = {"waiting": 0, "active": 1, "closed": 2}
# system messages are stored in both languages; the app shows the user's one
WELCOME = ("একজন এজেন্ট শীঘ্রই আপনার সাথে কথা বলবেন। উপায়ের কেউ কখনো আপনার পিন বা ওটিপি চাইবে না। / "
           "An agent will be with you shortly. Nobody from upay will ever ask for your PIN or OTP.")
PIN_WARNING = ("সতর্কতা: পিন বা ওটিপি কাউকে বলবেন না, উপায়ের এজেন্টকেও না। নম্বরটি লুকিয়ে রাখা হয়েছে। / "
               "Warning: never share your PIN or OTP, not even with upay staff. We hid the digits.")
_BN = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


class HandoffIn(BaseModel):
    category: Literal["scam", "money_lost", "dispute", "talk_to_human", "not_understood", "other"] = "talk_to_human"
    reason: str = Field(default="", max_length=300)
    page: dict = {}
    recent_pages: list[dict] = []
    transcript: list[dict] = []
    bangla: bool = True


class CustomerMsgIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ConsoleLoginIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    token: str = Field(max_length=200)  # the account password, or the shared code


class StaffMsgIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class StaffCloseIn(BaseModel):
    resolution: str = Field(default="", max_length=500)


class StopTransferIn(BaseModel):
    assessment_id: str


def _mask_deep(v):
    if isinstance(v, str):
        return pinguard.mask(v)
    if isinstance(v, list):
        return [_mask_deep(x) for x in v]
    if isinstance(v, dict):
        return {k: _mask_deep(x) for k, x in v.items()}
    return v


def _recent_levels(uid: str) -> set[str]:
    hour_ago = store.now() - timedelta(hours=1)
    return {a["result"].get("level") for a in store.assessments_for(uid, 20)
            if datetime.fromisoformat(a["created_at"]) >= hour_ago}


def _priority(uid: str, category: str, page: dict) -> str:
    level = ((page or {}).get("content") or {}).get("level")
    levels = _recent_levels(uid)
    if category in ("scam", "money_lost") or level == "RED" or "RED" in levels:
        return "urgent"
    if category == "dispute" or level == "YELLOW" or "YELLOW" in levels:
        return "high"
    return "normal"


def _queue() -> list[dict]:
    waiting = [h for h in store.list_handoffs() if h["status"] == "waiting"]
    return sorted(waiting, key=lambda h: (PRIORITY_ORDER[h["priority"]], h["created_at"]))


def _position(h: dict) -> int | None:
    if h["status"] != "waiting":
        return None
    ids = [x["id"] for x in _queue()]
    return ids.index(h["id"]) + 1 if h["id"] in ids else None


def _summary(h: dict) -> dict:
    return {"id": h["id"], "status": h["status"], "priority": h["priority"],
            "category": h["context"].get("category"), "agent_name": h["agent_name"],
            "queue_position": _position(h), "resolution": h["resolution"],
            "created_at": h["created_at"], "updated_at": h["updated_at"]}


def _own(hid: str, s: auth.Session) -> dict:
    h = store.get_handoff(hid)
    if not h or h["user_id"] != s.user["id"]:
        raise HTTPException(404, "chat not found")
    return h


# ---------------- customer ----------------
@router.post("/api/handoff")
def start_handoff(body: HandoffIn, s: auth.Session = Depends(auth.current)):
    uid = s.user["id"]
    h = store.open_handoff_for(uid)
    if not h:
        context = _mask_deep({"category": body.category, "reason": body.reason, "page": body.page,
                              "recent_pages": body.recent_pages[:3], "transcript": body.transcript[-12:],
                              "language": "bn" if body.bangla else "en"})
        hid = store.create_handoff(uid, _priority(uid, body.category, body.page),
                                   context["reason"], context)
        store.add_handoff_message(hid, "system", None, WELCOME)
        h = store.get_handoff(hid)
    return {**_summary(h), "messages": store.handoff_messages(h["id"])}


@router.get("/api/handoff/{hid}")
def poll_handoff(hid: str, after: int = 0, s: auth.Session = Depends(auth.current)):
    h = _own(hid, s)
    return {**_summary(h), "messages": store.handoff_messages(hid, after)}


@router.post("/api/handoff/{hid}/messages")
def customer_message(hid: str, body: CustomerMsgIn, s: auth.Session = Depends(auth.current)):
    h = _own(hid, s)
    if h["status"] == "closed":
        raise HTTPException(409, "chat closed")
    text = pinguard.mask(body.text)
    msg = store.add_handoff_message(hid, "user", None, text)
    if text != body.text:
        store.add_handoff_message(hid, "system", None, PIN_WARNING)
    return {"ok": True, "message": msg}


@router.post("/api/handoff/{hid}/close")
def customer_close(hid: str, s: auth.Session = Depends(auth.current)):
    h = _own(hid, s)
    if h["status"] != "closed":
        store.update_handoff(hid, status="closed", resolution="Closed by the customer")
        store.add_handoff_message(hid, "system", None, "গ্রাহক চ্যাটটি শেষ করেছেন। / The customer ended the chat.")
    return {"ok": True}


# ---------------- support console ----------------
def staff_accounts() -> dict[str, str]:
    """CONSOLE_STAFF="Mitu:secret,Rafi:$2b$12$..." -> {name: password or bcrypt hash}."""
    out = {}
    for item in (os.getenv("CONSOLE_STAFF") or "").split(","):
        name, _, pw = item.strip().partition(":")
        if name.strip() and pw:
            out[name.strip()] = pw
    return out


def _password_ok(given: str, stored: str) -> bool:
    if stored.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            return bcrypt.checkpw(given.encode(), stored.encode())
        except ValueError:
            return False
    return hmac.compare_digest(given.encode(), stored.encode())


def shared_code() -> str | None:
    """The shared access code, or None when the console is not usable with one."""
    code = os.getenv("CONSOLE_TOKEN") or DEFAULT_CODE
    if code == DEFAULT_CODE and not auth.demo_mode():
        return None  # never accept the public default on a real site
    return code


console = APIRouter(prefix="/api/console", dependencies=[Depends(auth.staff)])


@router.post("/api/console/login")
def console_login(body: ConsoleLoginIn):
    name = body.name.strip()
    accounts = staff_accounts()
    if accounts:
        ok = name in accounts and _password_ok(body.token, accounts[name])
    else:
        code = shared_code()
        if code is None:
            log.error("support console refused: set CONSOLE_STAFF or a CONSOLE_TOKEN other than the default")
            raise HTTPException(503, {"code": "console_not_configured"})
        ok = bool(name) and hmac.compare_digest(body.token.encode(), code.encode())
    if not ok:
        raise HTTPException(401, "bad console login")
    log.info("console sign-in: %s", name)
    return {"ok": True, "name": name, "token": auth.issue(name, role="staff", amr="password", minutes=STAFF_MINUTES)}


def _row(h: dict, users: dict) -> dict:
    u = users.get(h["user_id"]) or {}
    msgs = store.handoff_messages(h["id"])
    last = msgs[-1] if msgs else None
    talk = [m for m in msgs if m["sender"] != "system"]
    return {**_summary(h), "user_id": h["user_id"], "name": u.get("name"), "name_bn": u.get("name_bn"),
            "reason": h["reason"], "last_message": last,
            "unanswered": h["status"] != "closed" and bool(talk) and talk[-1]["sender"] == "user"}


@console.get("/handoffs")
def console_list():
    hs = store.list_handoffs()
    users = {u["id"]: u for u in store.users()}
    open_ = sorted([h for h in hs if h["status"] != "closed"],
                   key=lambda h: (STATUS_ORDER[h["status"]], PRIORITY_ORDER[h["priority"]], h["created_at"]))
    closed = sorted([h for h in hs if h["status"] == "closed"], key=lambda h: h["updated_at"], reverse=True)[:50]
    counts = {s: sum(h["status"] == s for h in hs) for s in ("waiting", "active", "closed")}
    counts["urgent"] = sum(h["priority"] == "urgent" for h in open_)
    return {"counts": counts, "handoffs": [_row(h, users) for h in open_ + closed]}


def _customer(uid: str) -> dict:
    u = store.user(uid)
    names = {c["phone"]: c["name"] for c in u["contacts"]}
    txs = [{"type": t["type"], "amount": t["amount"], "ts": t["ts"],
            "with": names.get(t["counterparty"]) or mask_phone(t["counterparty"] or "")}
           for t in reversed(wallet.get().history(uid)[-12:])]
    checks = []
    for a in store.assessments_for(uid, 8):
        d, r = a["draft"], a["result"]
        checks.append({
            "id": a["id"], "created_at": a["created_at"], "level": r.get("level"),
            "intent": d.get("intent"), "amount": d.get("amount"),
            "recipient": names.get(d.get("recipient_phone")) or mask_phone(d.get("recipient_phone") or ""),
            "new_recipient": bool((r.get("features") or {}).get("is_new_recipient")),
            "on_call": bool(d.get("on_active_call")),
            "answers": [pinguard.mask(x) for x in d.get("answers") or []],
            "reasons": [{"bn": x.get("bn"), "en": x.get("en")} for x in r.get("reasons") or []],
            "status": a["status"], "can_cancel": a["status"] == "open"})
    return {"profile": {"id": u["id"], "name": u["name"], "name_bn": u.get("name_bn"),
                        "persona": u.get("persona"), "phone": mask_phone(u["phone"]), "balance": u["balance"],
                        "contacts": [{"id": c["id"], "name": c["name"], "relation": c.get("relation"),
                                      "phone": mask_phone(c["phone"])} for c in u["contacts"]]},
            "transactions": txs, "assessments": checks}


def _get(hid: str) -> dict:
    h = store.get_handoff(hid)
    if not h:
        raise HTTPException(404, "chat not found")
    return h


@console.get("/handoffs/{hid}")
def console_detail(hid: str, after: int = 0):
    h = _get(hid)
    users = {u["id"]: u for u in store.users()}
    return {**_row(h, users), "context": h["context"], "messages": store.handoff_messages(hid, after),
            "customer": _customer(h["user_id"])}


def _take(h: dict, agent: str) -> None:
    """Claim a waiting chat for ``agent``; 409 if closed or someone else has it."""
    if h["status"] == "closed":
        raise HTTPException(409, "chat closed")
    if h["agent_name"] and h["agent_name"] != agent:
        raise HTTPException(409, f"chat taken by {h['agent_name']}")
    if h["agent_name"] != agent:
        store.update_handoff(h["id"], agent_name=agent, status="active")
        store.add_handoff_message(h["id"], "system", None,
                                  f"{agent} আপনার সাথে যুক্ত হয়েছেন। / {agent} has joined the chat.")


@console.post("/handoffs/{hid}/claim")
def console_claim(hid: str, agent: str = Depends(auth.staff)):
    _take(_get(hid), agent)
    return {"ok": True}


@console.post("/handoffs/{hid}/messages")
def console_message(hid: str, body: StaffMsgIn, agent: str = Depends(auth.staff)):
    _take(_get(hid), agent)
    return {"ok": True, "message": store.add_handoff_message(hid, "agent", agent, body.text)}


@console.post("/handoffs/{hid}/close")
def console_close(hid: str, body: StaffCloseIn, agent: str = Depends(auth.staff)):
    h = _get(hid)
    if h["agent_name"] and h["agent_name"] != agent:
        raise HTTPException(409, f"chat taken by {h['agent_name']}")
    if h["status"] != "closed":
        store.update_handoff(hid, status="closed", agent_name=h["agent_name"] or agent,
                             resolution=body.resolution or None)
        store.add_handoff_message(hid, "system", None,
                                  f"{agent} চ্যাটটি শেষ করেছেন। / {agent} closed the chat.")
    return {"ok": True}


@console.post("/handoffs/{hid}/cancel-transfer")
def console_stop_transfer(hid: str, body: StopTransferIn, agent: str = Depends(auth.staff)):
    """Protective only: stop the customer's own pending transfer."""
    h = _get(hid)
    a = store.get_assessment(body.assessment_id)
    if not a or a["user_id"] != h["user_id"]:
        raise HTTPException(404, "transfer not found")
    if a["status"] != "open":
        raise HTTPException(409, f"transfer already {a['status']}")
    _take(h, agent)
    store.update_assessment(a["id"], status="cancelled")
    store.log_decision(a["user_id"], a["draft"], a["result"], "cancelled")
    n = int(a["draft"]["amount"])
    store.add_handoff_message(
        hid, "system", None,
        f"{agent} আপনার অপেক্ষমাণ ৳{f'{n:,}'.translate(_BN)} লেনদেনটি বাতিল করেছেন; টাকা আপনার অ্যাকাউন্টেই আছে। / "
        f"{agent} cancelled your pending ৳{n:,} transfer; the money is still in your account.")
    return {"ok": True}


router.include_router(console)
