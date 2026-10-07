"""A stand-in for upay's wallet API, for integration tests and load runs.

Every call waits a simulated network delay and fails at a set rate, the way
a remote wallet does. Half the failed transfers are lost requests (nothing
happened) and half are lost responses (the money moved but we never heard
back): the case idempotency keys exist for. The sandbox books transfers in
the local ledger, so the app shows the same balance as with LocalWallet.
"""
from __future__ import annotations

import random
import time

from . import WalletUnavailable
from .local import LocalWallet


class MockUpaySandbox:
    name = "mock_upay"

    def __init__(self, latency_ms: float = 120, failure_rate: float = 0.02, seed: int | None = None):
        self.latency_ms = latency_ms
        self.failure_rate = failure_rate
        self.inject: list[str] = []  # tests: next failures, "request_lost" or "response_lost"
        self._rng = random.Random(seed)
        self._ledger = LocalWallet()

    def _network(self) -> str | None:
        """Wait like a remote call; the failure to simulate, if any."""
        if self.latency_ms:
            time.sleep(self.latency_ms * self._rng.uniform(0.5, 1.5) / 1000)
        if self.inject:
            return self.inject.pop(0)
        if self._rng.random() < self.failure_rate:
            return self._rng.choice(("request_lost", "response_lost"))
        return None

    def balance(self, uid: str) -> float:
        if self._network():
            raise WalletUnavailable("upay sandbox: balance timed out")
        return self._ledger.balance(uid)

    def history(self, uid: str) -> list[dict]:
        if self._network():
            raise WalletUnavailable("upay sandbox: history timed out")
        return self._ledger.history(uid)

    def transfer(self, uid: str, intent: str, phone: str, amount: float, idempotency_key: str) -> dict:
        fail = self._network()
        if fail == "request_lost":
            raise WalletUnavailable("upay sandbox: request timed out")
        tx = self._ledger.transfer(uid, intent, phone, amount, idempotency_key)
        if fail == "response_lost":
            raise WalletUnavailable("upay sandbox: response lost after the transfer")
        return tx
