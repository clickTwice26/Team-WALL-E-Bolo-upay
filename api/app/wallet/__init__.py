"""Wallet integration boundary: where money actually moves.

The API and the risk code only see this interface. Today ``LocalWallet``
keeps the ledger in our SQLite file; for a pilot, an adapter that calls
upay's API replaces that one class and nothing else (the risk check, the
interview and authentication do not change).

    WALLET_ADAPTER=local      (default) the SQLite ledger
    WALLET_ADAPTER=mock_upay  a simulated upay API with latency and failures
                              (MOCK_UPAY_LATENCY_MS, MOCK_UPAY_FAILURE_RATE)

Every transfer carries an idempotency key: the same key always returns the
first transfer, so a retry after a timeout never sends twice.
"""
from __future__ import annotations

import os
from typing import Protocol, runtime_checkable


class WalletError(Exception):
    pass


class InsufficientFunds(WalletError):
    pass


class WalletUnavailable(WalletError):
    """Timeout or 5xx from the wallet. The transfer may or may not have
    happened; retrying with the same idempotency key is always safe."""


@runtime_checkable
class WalletAdapter(Protocol):
    name: str

    def balance(self, uid: str) -> float: ...

    def history(self, uid: str) -> list[dict]:
        """Transactions oldest first: id, user_id, type, counterparty, amount, ts."""

    def transfer(self, uid: str, intent: str, phone: str, amount: float, idempotency_key: str) -> dict:
        """{"id", "ts", "balance", "replayed"}; raises InsufficientFunds or WalletUnavailable."""


_wallet: WalletAdapter | None = None


def get() -> WalletAdapter:
    global _wallet
    if _wallet is None:
        kind = (os.getenv("WALLET_ADAPTER") or "local").strip().lower()
        if kind == "mock_upay":
            from .mock_upay import MockUpaySandbox
            _wallet = MockUpaySandbox(latency_ms=float(os.getenv("MOCK_UPAY_LATENCY_MS", "120")),
                                      failure_rate=float(os.getenv("MOCK_UPAY_FAILURE_RATE", "0.02")))
        elif kind == "local":
            from .local import LocalWallet
            _wallet = LocalWallet()
        else:
            raise RuntimeError(f"unknown WALLET_ADAPTER {kind!r} (local | mock_upay)")
    return _wallet


def use(adapter: WalletAdapter | None) -> None:
    """Swap the adapter (tests); None goes back to WALLET_ADAPTER."""
    global _wallet
    _wallet = adapter
