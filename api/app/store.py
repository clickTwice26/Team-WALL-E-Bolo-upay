"""SQLite storage for the prototype (synthetic data only)."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import bcrypt

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "data" / "seed.json"
DB_PATH = os.getenv("DB_PATH", str(ROOT / "data" / "bolo.db"))
TZ = ZoneInfo("Asia/Dhaka")

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, profile TEXT NOT NULL,
  balance REAL NOT NULL, pin_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS transactions (id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
  type TEXT NOT NULL, counterparty TEXT, amount REAL NOT NULL, ts TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS tx_user ON transactions(user_id, ts);
CREATE TABLE IF NOT EXISTS assessments (id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
  draft TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open', pin_failures INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, ts TEXT NOT NULL,
  user_id TEXT NOT NULL, intent TEXT, amount REAL, recipient TEXT, level TEXT,
  probability REAL, categories TEXT, outcome TEXT NOT NULL, interviewed INTEGER);
CREATE TABLE IF NOT EXISTS handoffs (id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'waiting', priority TEXT NOT NULL DEFAULT 'normal',
  reason TEXT, context TEXT NOT NULL, agent_name TEXT, resolution TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS handoff_messages (id INTEGER PRIMARY KEY AUTOINCREMENT,
  handoff_id TEXT NOT NULL, sender TEXT NOT NULL, name TEXT, text TEXT NOT NULL, ts TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS hm_handoff ON handoff_messages(handoff_id, id);
CREATE TABLE IF NOT EXISTS pin_guard (user_id TEXT PRIMARY KEY, failures INTEGER NOT NULL,
  locked_until TEXT);
CREATE TABLE IF NOT EXISTS devices (user_id TEXT NOT NULL, key_id TEXT NOT NULL,
  public_key TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (user_id, key_id));
CREATE TABLE IF NOT EXISTS feedback (assessment_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
  kind TEXT NOT NULL, level TEXT, ts TEXT NOT NULL);
"""


def now() -> datetime:
    return datetime.now(TZ)


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        if _conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            _seed(_conn)
    return _conn


def _seed(c: sqlite3.Connection) -> None:
    data = json.loads(SEED.read_text(encoding="utf-8"))
    pin_hash = bcrypt.hashpw(data["demo_pin"].encode(), bcrypt.gensalt()).decode()
    for u in data["users"]:
        profile = {k: v for k, v in u.items() if k != "balance"}
        c.execute("INSERT INTO users VALUES (?,?,?,?)",
                  (u["id"], json.dumps(profile, ensure_ascii=False), u["balance"], pin_hash))
    c.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?)",
                  [(t["id"], t["user_id"], t["type"], t["counterparty"], t["amount"], t["ts"])
                   for t in data["transactions"]])
    c.commit()


def reset() -> None:
    with _lock:
        c = conn()
        c.executescript("DELETE FROM users; DELETE FROM transactions; "
                        "DELETE FROM assessments; DELETE FROM decisions; "
                        "DELETE FROM handoffs; DELETE FROM handoff_messages; "
                        "DELETE FROM pin_guard; DELETE FROM feedback;")
        _seed(c)


def users() -> list[dict]:
    rows = conn().execute("SELECT profile, balance FROM users ORDER BY id").fetchall()
    return [dict(json.loads(r["profile"]), balance=r["balance"]) for r in rows]


def user(uid: str) -> dict | None:
    r = conn().execute("SELECT profile, balance FROM users WHERE id=?", (uid,)).fetchone()
    return dict(json.loads(r["profile"]), balance=r["balance"]) if r else None


def check_pin(uid: str, pin: str) -> bool:
    r = conn().execute("SELECT pin_hash FROM users WHERE id=?", (uid,)).fetchone()
    return bool(r) and bcrypt.checkpw(pin.encode(), r["pin_hash"].encode())


def pin_state(uid: str) -> tuple[int, datetime | None]:
    """(wrong PINs in a row, locked until) for one account."""
    r = conn().execute("SELECT failures, locked_until FROM pin_guard WHERE user_id=?", (uid,)).fetchone()
    if not r:
        return 0, None
    return r["failures"], datetime.fromisoformat(r["locked_until"]) if r["locked_until"] else None


def set_pin_state(uid: str, failures: int, locked_until: datetime | None) -> None:
    with _lock:
        conn().execute("INSERT INTO pin_guard VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                       "failures=excluded.failures, locked_until=excluded.locked_until",
                       (uid, failures, locked_until.isoformat() if locked_until else None))
        conn().commit()


def register_device(uid: str, key_id: str, public_key: str) -> None:
    with _lock:
        conn().execute("INSERT OR IGNORE INTO devices VALUES (?,?,?,?)",
                       (uid, key_id, public_key, now().isoformat()))
        conn().commit()


def device_registered(uid: str, key_id: str) -> bool:
    return conn().execute("SELECT 1 FROM devices WHERE user_id=? AND key_id=?", (uid, key_id)).fetchone() is not None


def history(uid: str) -> list[dict]:
    rows = conn().execute("SELECT * FROM transactions WHERE user_id=? ORDER BY ts", (uid,)).fetchall()
    return [dict(r) for r in rows]


def save_assessment(uid: str, draft: dict, result: dict) -> str:
    aid = uuid.uuid4().hex[:12]
    with _lock:
        conn().execute("INSERT INTO assessments (id,user_id,draft,result,created_at) VALUES (?,?,?,?,?)",
                       (aid, uid, json.dumps(draft, ensure_ascii=False),
                        json.dumps(result, ensure_ascii=False), now().isoformat()))
        conn().commit()
    return aid


def get_assessment(aid: str) -> dict | None:
    r = conn().execute("SELECT * FROM assessments WHERE id=?", (aid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["draft"] = json.loads(d["draft"])
    d["result"] = json.loads(d["result"])
    return d


def update_assessment(aid: str, **fields) -> None:
    sets = ", ".join(f"{k}=?" for k in fields)
    with _lock:
        conn().execute(f"UPDATE assessments SET {sets} WHERE id=?", (*fields.values(), aid))
        conn().commit()


def execute_transfer(uid: str, intent: str, phone: str, amount: float) -> dict:
    with _lock:
        c = conn()
        bal = c.execute("SELECT balance FROM users WHERE id=?", (uid,)).fetchone()["balance"]
        if amount > bal:
            raise ValueError("insufficient_balance")
        tid = f"{uid}-x{uuid.uuid4().hex[:8]}"
        ts = now().isoformat()
        c.execute("INSERT INTO transactions VALUES (?,?,?,?,?,?)", (tid, uid, intent, phone, amount, ts))
        c.execute("UPDATE users SET balance=balance-? WHERE id=?", (amount, uid))
        c.commit()
        return {"id": tid, "ts": ts, "balance": bal - amount}


def log_decision(uid: str, draft: dict, result: dict, outcome: str) -> None:
    cats = [r["key"].split(":", 1)[1] for r in result.get("reasons", []) if r["key"].startswith("scam:")]
    with _lock:
        conn().execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (uuid.uuid4().hex[:12], now().isoformat(), uid, draft.get("intent"),
                        draft.get("amount"), draft.get("recipient_phone"), result.get("level"),
                        result.get("probability"), json.dumps(cats), outcome,
                        1 if draft.get("answers") else 0))
        conn().commit()


def decisions(limit: int = 200) -> list[dict]:
    rows = conn().execute("SELECT * FROM decisions ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["categories"] = json.loads(d["categories"] or "[]")
        out.append(d)
    return out


def assessments_since(ts: str) -> list[dict]:
    """Every risk check since ``ts`` (ISO time), oldest first."""
    rows = conn().execute("SELECT id FROM assessments WHERE created_at >= ? ORDER BY created_at", (ts,)).fetchall()
    return [get_assessment(r["id"]) for r in rows]


def add_feedback(aid: str, uid: str, kind: str, level: str | None) -> None:
    with _lock:
        conn().execute("INSERT OR IGNORE INTO feedback VALUES (?,?,?,?,?)", (aid, uid, kind, level, now().isoformat()))
        conn().commit()


def feedback_since(ts: str) -> list[dict]:
    return [dict(r) for r in conn().execute("SELECT * FROM feedback WHERE ts >= ?", (ts,)).fetchall()]


def assessments_for(uid: str, limit: int = 8) -> list[dict]:
    rows = conn().execute("SELECT id FROM assessments WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                          (uid, limit)).fetchall()
    return [get_assessment(r["id"]) for r in rows]


# ---------- human handoff ----------
def _handoff(r: sqlite3.Row | None) -> dict | None:
    if not r:
        return None
    d = dict(r)
    d["context"] = json.loads(d["context"])
    return d


def create_handoff(uid: str, priority: str, reason: str, context: dict) -> str:
    hid = uuid.uuid4().hex[:10]
    ts = now().isoformat()
    with _lock:
        conn().execute("INSERT INTO handoffs (id,user_id,status,priority,reason,context,created_at,updated_at) "
                       "VALUES (?,?,?,?,?,?,?,?)",
                       (hid, uid, "waiting", priority, reason, json.dumps(context, ensure_ascii=False), ts, ts))
        conn().commit()
    return hid


def get_handoff(hid: str) -> dict | None:
    return _handoff(conn().execute("SELECT * FROM handoffs WHERE id=?", (hid,)).fetchone())


def open_handoff_for(uid: str) -> dict | None:
    return _handoff(conn().execute(
        "SELECT * FROM handoffs WHERE user_id=? AND status!='closed' ORDER BY created_at DESC LIMIT 1",
        (uid,)).fetchone())


def list_handoffs() -> list[dict]:
    return [_handoff(r) for r in conn().execute("SELECT * FROM handoffs").fetchall()]


def update_handoff(hid: str, **fields) -> None:
    fields["updated_at"] = now().isoformat()
    sets = ", ".join(f"{k}=?" for k in fields)
    with _lock:
        conn().execute(f"UPDATE handoffs SET {sets} WHERE id=?", (*fields.values(), hid))
        conn().commit()


def add_handoff_message(hid: str, sender: str, name: str | None, text: str) -> dict:
    ts = now().isoformat()
    with _lock:
        cur = conn().execute("INSERT INTO handoff_messages (handoff_id,sender,name,text,ts) VALUES (?,?,?,?,?)",
                             (hid, sender, name, text, ts))
        conn().execute("UPDATE handoffs SET updated_at=? WHERE id=?", (ts, hid))
        conn().commit()
    return {"id": cur.lastrowid, "sender": sender, "name": name, "text": text, "ts": ts}


def handoff_messages(hid: str, after: int = 0) -> list[dict]:
    rows = conn().execute("SELECT id, sender, name, text, ts FROM handoff_messages "
                          "WHERE handoff_id=? AND id>? ORDER BY id", (hid, after)).fetchall()
    return [dict(r) for r in rows]
