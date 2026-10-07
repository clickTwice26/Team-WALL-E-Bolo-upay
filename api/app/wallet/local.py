"""The prototype's own ledger: balances and transactions in the SQLite store."""
from __future__ import annotations

import uuid

from .. import store
from . import InsufficientFunds


class LocalWallet:
    name = "local"

    def balance(self, uid: str) -> float:
        r = store.conn().execute("SELECT balance FROM users WHERE id=?", (uid,)).fetchone()
        return r["balance"] if r else 0.0

    def history(self, uid: str) -> list[dict]:
        return store.history(uid)

    def transfer(self, uid: str, intent: str, phone: str, amount: float, idempotency_key: str) -> dict:
        with store._lock:
            c = store.conn()
            # take the write lock before reading the balance, so two workers
            # cannot both see enough money and both send
            c.execute("BEGIN IMMEDIATE")
            try:
                r = c.execute("SELECT tx_id, ts, balance FROM wallet_requests WHERE user_id=? AND key=?",
                              (uid, idempotency_key)).fetchone()
                if r:  # this key already sent: return that transfer, send nothing
                    c.commit()
                    return {"id": r["tx_id"], "ts": r["ts"], "balance": r["balance"], "replayed": True}
                bal = c.execute("SELECT balance FROM users WHERE id=?", (uid,)).fetchone()["balance"]
                if amount > bal:
                    raise InsufficientFunds("insufficient_balance")
                tid = f"{uid}-x{uuid.uuid4().hex[:8]}"
                ts = store.now().isoformat()
                c.execute("INSERT INTO transactions VALUES (?,?,?,?,?,?)", (tid, uid, intent, phone, amount, ts))
                c.execute("UPDATE users SET balance=balance-? WHERE id=?", (amount, uid))
                c.execute("INSERT INTO wallet_requests VALUES (?,?,?,?,?)",
                          (uid, idempotency_key, tid, ts, bal - amount))
                c.commit()
            except BaseException:
                c.rollback()
                raise
        return {"id": tid, "ts": ts, "balance": bal - amount, "replayed": False}
