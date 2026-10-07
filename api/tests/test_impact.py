"""Impact simulator (/api/impact): rescaling, assumptions and access."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.pop("LLM_PROVIDER", None)

from fastapi.testclient import TestClient  # noqa: E402

from app import impact  # noqa: E402
from app.main import app  # noqa: E402
from helpers import signed_in  # noqa: E402


def test_chain_scales_with_transfers_and_prevalence():
    a = impact.simulate(1000, 0.01)
    b = impact.simulate(100000, 0.01)
    me, big = a["shield"]["bolo_upay"]["mid"], b["shield"]["bolo_upay"]["mid"]
    assert me["scams"] == 10 and big["scams"] == 1000
    assert me["scams"] >= me["scams_flagged"] >= me["scams_held_red"] > 0
    assert me["scams_stopped"] <= me["scams_flagged"] and me["tk_protected"] > 0
    assert abs(big["tk_protected"] - 100 * me["tk_protected"]) <= 100
    assert a["label"] == "Simulation on synthetic data, not real results"


def test_new_model_stops_more_than_the_previous_one_and_counts_its_cost():
    s = impact.simulate(1000, 0.05)["shield"]
    me, old, rules = s["bolo_upay"]["mid"], s["previous_model"]["mid"], s["rules_only"]["mid"]
    assert me["scams_stopped"] > old["scams_stopped"] > rules["scams_stopped"] * 0.5
    assert me["honest_warned"] > 0 and me["honest_payments_abandoned"] > 0  # the false-warning cost is shown


def test_low_mid_high_are_ordered_and_disputes_are_ranges():
    r = impact.simulate(1000, 0.01)
    low, mid, high = (r["shield"]["bolo_upay"][c]["tk_protected"] for c in ("low", "mid", "high"))
    assert low <= mid <= high
    d = r["disputes"]
    assert d["low"]["avoided_per_year"] < d["mid"]["avoided_per_year"] < d["high"]["avoided_per_year"]
    assert set(r["assumptions"]) >= {"stop_rate_red", "cost_per_dispute_tk", "abandon_rate_after_warning"}


def test_api_access_and_validation():
    anon = TestClient(app)
    assert anon.get("/api/impact").status_code == 401
    u1 = signed_in(app, "u1")
    r = u1.get("/api/impact", params={"transfers": 1000, "prevalence": 0.01})
    assert r.status_code == 200 and r.json()["transfers"] == 1000
    assert u1.get("/api/impact", params={"prevalence": 0.9}).status_code == 422
