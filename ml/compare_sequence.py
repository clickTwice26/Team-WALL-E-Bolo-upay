"""Does a sequence model beat the served one? A small GRU, compared honestly.

Judge feedback asked us to investigate sequential models. This trains a GRU
over each payment's last 20 transactions (type, size against the user's
usual, time gap, first-time counterparty, contact, hour) plus the payment's
own 18 features, on exactly the data and time split of ml/train_risk.py, and
compares it with the served gradient-boosting model on the test split.

Rule: the GRU replaces the served model only if it improves test PR-AUC by
more than 0.01. The result is written either way.

Needs JAX (CPU):  pip install "jax[cpu]"
Run:  python ml/compare_sequence.py   ->  model/sequence_metrics.json
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path

import jax
import jax.numpy as jnp
import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "ml"))
import joblib  # noqa: E402
import simulate  # noqa: E402
from app.core.features import FEATURES, vector  # noqa: E402

STEPS, HIDDEN, EPOCHS, BATCH, LR = 20, 32, 25, 128, 3e-3
TYPES = ("send_money", "mobile_recharge", "cash_out", "merchant_payment", "receive")
ADOPT_MARGIN = 0.01


def steps(e: dict) -> np.ndarray:
    """[STEPS + 1, 11]: the last 20 transactions, then the payment itself."""
    rows, seen, prev = [], set(), None
    txs = e["recent"] + [{"type": e["intent"], "amount": e["amount"], "ts": e["ts"].isoformat(),
                          "counterparty": e["phone"]}]
    for t in txs:
        ts = datetime.fromisoformat(t["ts"])
        gap = 0.0 if prev is None else math.log1p(max((ts - prev).total_seconds(), 0) / 3600)
        hour = ts.hour + ts.minute / 60
        cp = t["counterparty"]
        rows.append([*(1.0 if t["type"] == k else 0.0 for k in TYPES),
                     math.log(max(t["amount"], 1) / e["median"]), gap,
                     0.0 if cp in seen else 1.0, 1.0 if cp in e["contacts"] else 0.0,
                     math.sin(2 * math.pi * hour / 24), math.cos(2 * math.pi * hour / 24)])
        seen.add(cp)
        prev = ts
    x = np.zeros((STEPS + 1, len(rows[0])), dtype=np.float32)
    x[-len(rows):] = rows[-(STEPS + 1):]  # left-pad short histories with zeros
    return x


def init(key, n_in, n_tab):
    k1, k2, k3 = jax.random.split(key, 3)
    s = 1 / math.sqrt(HIDDEN)
    return {"W": jax.random.uniform(k1, (n_in + HIDDEN, 3 * HIDDEN), minval=-s, maxval=s),
            "b": jnp.zeros(3 * HIDDEN),
            "head": jax.random.normal(k2, (HIDDEN + n_tab,)) * 0.05,
            "bias": jnp.zeros(()), "_k": k3}


def forward(p, seq, tab):
    def cell(h, x):
        z = jnp.concatenate([x, h], -1) @ p["W"] + p["b"]
        r, u, n = jnp.split(z, 3, -1)
        r, u = jax.nn.sigmoid(r), jax.nn.sigmoid(u)
        n = jnp.tanh(n + r * h)  # (simplified reset gate: fine for a comparison model)
        h = (1 - u) * n + u * h
        return h, None
    h0 = jnp.zeros((seq.shape[0], HIDDEN))
    h, _ = jax.lax.scan(cell, h0, jnp.swapaxes(seq, 0, 1))
    return jnp.concatenate([h, tab], -1) @ p["head"] + p["bias"]


def loss(p, seq, tab, y):
    z = forward(p, seq, tab)
    return jnp.mean(jnp.logaddexp(0, z) - y * z)


@jax.jit
def step(p, m, v, t, seq, tab, y):
    params = {k: p[k] for k in ("W", "b", "head", "bias")}
    g = jax.grad(loss)(params, seq, tab, y)
    out_p, out_m, out_v = dict(p), {}, {}
    for k in params:  # Adam
        out_m[k] = 0.9 * m[k] + 0.1 * g[k]
        out_v[k] = 0.999 * v[k] + 0.001 * g[k] ** 2
        mh, vh = out_m[k] / (1 - 0.9 ** t), out_v[k] / (1 - 0.999 ** t)
        out_p[k] = p[k] - LR * mh / (jnp.sqrt(vh) + 1e-8)
    return out_p, out_m, out_v


def main() -> None:
    events = simulate.generate()
    n = len(events)
    y = np.array([e["label"] for e in events], dtype=np.float32)
    seq = np.stack([steps(e) for e in events])
    tab_raw = np.array([vector(e["feats"]) for e in events])
    cut = [int(n * q) for q in (0.60, 0.70, 0.85)]
    fit, va, te = np.arange(0, cut[1]), np.arange(cut[1], cut[2]), np.arange(cut[2], n)
    tab = StandardScaler().fit(tab_raw[fit]).transform(tab_raw).astype(np.float32)

    p = init(jax.random.PRNGKey(7), seq.shape[-1], tab.shape[-1])
    p.pop("_k")
    m = {k: jnp.zeros_like(v) for k, v in p.items()}
    v = {k: jnp.zeros_like(x) for k, x in p.items()}
    rng, t, best = np.random.default_rng(7), 0, (-1.0, None, 0)
    for epoch in range(EPOCHS):
        order = rng.permutation(fit)
        for i in range(0, len(order), BATCH):
            b = order[i:i + BATCH]
            t += 1
            p, m, v = step(p, m, v, t, seq[b], tab[b], y[b])
        pr = average_precision_score(y[va], np.asarray(forward(p, seq[va], tab[va])))
        if pr > best[0]:
            best = (pr, {k: x for k, x in p.items()}, epoch + 1)  # early stopping on the tuning split
    p = best[1]
    gru = np.asarray(jax.nn.sigmoid(forward(p, seq[te], tab[te])))

    served = joblib.load(ROOT / "model" / "risk_model.joblib")
    gb = served["model"].predict_proba(tab_raw[te])[:, 1]
    res = {
        "gru_over_last_20_plus_features": {"roc_auc": round(float(roc_auc_score(y[te], gru)), 4),
                                           "pr_auc": round(float(average_precision_score(y[te], gru)), 4),
                                           "epochs": best[2]},
        "served_gradient_boosting": {"roc_auc": round(float(roc_auc_score(y[te], gb)), 4),
                                     "pr_auc": round(float(average_precision_score(y[te], gb)), 4)},
    }
    gain = res["gru_over_last_20_plus_features"]["pr_auc"] - res["served_gradient_boosting"]["pr_auc"]
    res["pr_auc_gain"] = round(gain, 4)
    res["adopted"] = gain > ADOPT_MARGIN
    res["rule"] = f"adopt only if test PR-AUC improves by more than {ADOPT_MARGIN}"
    res["conclusion"] = (
        "The GRU is adopted." if res["adopted"] else
        f"Not adopted: the GRU changes PR-AUC by {gain:+.4f}. The sequence signals that matter "
        "(bursts, new recipients, money passed on, the user's own habits) are already features of the "
        "served model, which stays explainable per decision.")
    res["data"] = {"test": len(te), "steps": STEPS, "hidden": HIDDEN,
                   "note": "Same simulated timelines and time split as ml/train_risk.py."}
    res["trained_at"] = datetime.now().isoformat(timespec="seconds")
    (ROOT / "model" / "sequence_metrics.json").write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
