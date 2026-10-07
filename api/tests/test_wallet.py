"""Wallet adapter, idempotent execute and the mock upay sandbox."""
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ["HOLD_SECONDS"] = "0"
os.environ.pop("LLM_PROVIDER", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import store, wallet  # noqa: E402
from app.main import app  # noqa: E402
from app.wallet.local import LocalWallet  # noqa: E402
from app.wallet.mock_upay import MockUpaySandbox  # noqa: E402
from helpers import signed_in  # noqa: E402

DAY = "2026-10-03T14:00:00+06:00"
GREEN = {"intent": "send_money", "amount": 500, "recipient_phone": "01700000101", "command_text": "Ammu ke 500 taka pathao"}


@pytest.fixture
def u1():
    store.reset()
    wallet.use(None)
    yield signed_in(app, "u1")
    wallet.use(None)
    store.reset()


def _assess(c, draft=GREEN):
    a = c.post("/api/assess", json={"draft": draft, "now": DAY}).json()
    assert a["level"] == "GREEN", a
    return a["assessment_id"]


def _pay(c, aid, key=None, pin="1234"):
    headers = {"Idempotency-Key": key} if key else {}
    return c.post("/api/execute", json={"assessment_id": aid, "method": "pin", "pin": pin}, headers=headers)


def _sent(uid="u1"):
    return [t for t in store.history(uid) if "-x" in t["id"]]


def test_adapters_follow_the_protocol():
    assert isinstance(LocalWallet(), wallet.WalletAdapter)
    assert isinstance(MockUpaySandbox(latency_ms=0), wallet.WalletAdapter)
    assert wallet.get().name == "local"  # WALLET_ADAPTER unset


def test_same_idempotency_key_never_sends_twice(u1):
    aid = _assess(u1)
    first = _pay(u1, aid, key="tap-0001-abcd")
    again = _pay(u1, aid, key="tap-0001-abcd")
    assert first.status_code == again.status_code == 200
    assert again.json() == first.json()  # the first result, not "already executed"
    assert len(_sent()) == 1 and store.user("u1")["balance"] == 8450 - 500
    assert sum(d["outcome"] == "sent" for d in store.decisions()) == 1
    # without the key a repeat is refused, and still nothing is sent
    assert _pay(u1, aid).status_code == 409 and len(_sent()) == 1


def test_a_key_belongs_to_one_transfer(u1):
    _pay(u1, _assess(u1), key="tap-0002-abcd")
    r = _pay(u1, _assess(u1), key="tap-0002-abcd")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "idempotency_key_reused"
    assert len(_sent()) == 1


def test_a_refused_attempt_can_be_retried_with_the_same_key(u1):
    aid = _assess(u1)
    assert _pay(u1, aid, key="tap-0003-abcd", pin="0000").status_code == 401
    assert _pay(u1, aid, key="tap-0003-abcd").status_code == 200
    assert len(_sent()) == 1


def test_parallel_retries_send_once(u1):
    aid = _assess(u1)
    clients = [TestClient(app, headers=dict(u1.headers)) for _ in range(4)]
    with ThreadPoolExecutor(4) as pool:
        rs = list(pool.map(lambda c: _pay(c, aid, key="tap-0004-abcd"), clients))
    assert [r.status_code for r in rs] == [200] * 4
    assert len({r.json()["transaction"]["id"] for r in rs}) == 1
    assert len(_sent()) == 1 and store.user("u1")["balance"] == 8450 - 500


def test_lost_response_from_upay_is_safe_to_retry(u1):
    sandbox = MockUpaySandbox(latency_ms=0, failure_rate=0)
    wallet.use(sandbox)
    aid = _assess(u1)
    sandbox.inject = ["response_lost"]  # upay moved the money, we never heard back
    r = _pay(u1, aid, key="tap-0005-abcd")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "wallet_unavailable"
    assert len(_sent()) == 1 and store.get_assessment(aid)["status"] == "open"
    r = _pay(u1, aid, key="tap-0005-abcd")  # the app retries the same tap
    assert r.status_code == 200 and r.json()["transaction"]["id"] == _sent()[0]["id"]
    assert len(_sent()) == 1 and store.user("u1")["balance"] == 8450 - 500
    assert store.get_assessment(aid)["status"] == "executed"


def test_lost_request_sends_nothing_until_the_retry(u1):
    sandbox = MockUpaySandbox(latency_ms=0, failure_rate=0)
    wallet.use(sandbox)
    aid = _assess(u1)
    sandbox.inject = ["request_lost"]
    assert _pay(u1, aid, key="tap-0006-abcd").status_code == 503 and not _sent()
    assert _pay(u1, aid, key="tap-0006-abcd").status_code == 200 and len(_sent()) == 1


def test_swapping_the_adapter_does_not_change_the_risk_check(u1):
    risky = {"intent": "send_money", "amount": 2000, "recipient_phone": "01799998888",
             "is_return_claim": True, "command_text": "01799998888 e 2000 taka ferot pathao"}
    local = u1.post("/api/assess", json={"draft": risky, "now": DAY}).json()
    wallet.use(MockUpaySandbox(latency_ms=0, failure_rate=0))
    sandbox = u1.post("/api/assess", json={"draft": risky, "now": DAY}).json()
    for k in ("level", "probability", "hard_rules", "features"):
        assert local[k] == sandbox[k], k
    wallet.use(MockUpaySandbox(latency_ms=0, failure_rate=0, seed=1))
    wallet.get().inject = ["request_lost"]
    r = u1.post("/api/assess", json={"draft": risky, "now": DAY})
    assert r.status_code == 503  # a wallet outage is an error, never a GREEN


def test_prometheus_metrics_are_served_before_the_spa():
    c = TestClient(app)
    c.get("/api/health")
    r = c.get("/metrics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert "http_requests_total" in r.text and "<html" not in r.text
