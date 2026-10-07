"""ml/real_data.py: real wallet data in the DATA_REQUEST schema becomes training events."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
import real_data  # noqa: E402

from app.core.features import FEATURES  # noqa: E402


def test_sample_loads_with_serving_features():
    ev = real_data.load(ROOT / "data" / "real_sample" / "transactions.csv")
    assert ev and {e["label"] for e in ev} == {0, 1}
    assert set(ev[0]["feats"]) >= set(FEATURES)
    assert [e["ts"] for e in ev] == sorted(e["ts"] for e in ev)  # time order for the split


def test_schema_errors_are_clear(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("user_id,ts,amount\nu1,2026-01-01T10:00:00+06:00,5\n")
    with pytest.raises(real_data.SchemaError, match="missing columns"):
        real_data.load(p)
    p.write_text("user_id,ts,type,counterparty,amount,balance_before,label\n"
                 "u1,2026-01-01T10:00:00+06:00,teleport,x,5,10,0\n")
    with pytest.raises(real_data.SchemaError, match="unknown type"):
        real_data.load(p)
