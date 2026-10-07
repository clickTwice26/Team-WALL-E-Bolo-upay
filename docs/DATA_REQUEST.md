# Data request to upay: retraining the scam shield on real data

Every model in this prototype is trained on simulated wallet timelines. The pipeline is ready for real data: `python ml/train_risk.py --data transactions.csv` computes the same features the API serves with and writes `model/risk_model_real.joblib`, `model/risk_metrics_real.json` and `docs/img/calibration_real.png` (git-ignored), with the same metrics as the synthetic run so the two can be compared side by side. A synthetic sample in the schema is in `data/real_sample/transactions.csv`.

## Fields (one CSV row per wallet transaction)

| Column | Meaning |
|---|---|
| `user_id` | Pseudonymous account id (salted hash, salt kept by upay) |
| `ts` | Time with offset, ISO 8601 (`2026-03-01T21:15:00+06:00`) |
| `type` | `send_money`, `mobile_recharge`, `cash_out`, `merchant_payment`, `bill_payment` or `receive` |
| `counterparty` | Salted hash of the other phone number, agent or merchant id (same salt, so repeats match) |
| `amount` | Taka |
| `balance_before` | Balance just before the transaction |
| `label` | `1` if a fraud report was confirmed for this payment, `0` otherwise; empty for incoming money |

Useful later: dispute outcomes (wrong number or wrong amount, refunded or not) to train the mistake guard, and the date each fraud report was confirmed.

## How we would handle it

- **Anonymised before it leaves upay's systems**, or better, **training runs on upay's own servers**: the script needs only Python and this repository, and nothing has to be sent to us or to any cloud service. The LLM is never involved in training. In production the LLM path itself should be a local model as well (README, "LLM today, local model in production").
- **Late labels:** fraud reports arrive days or weeks after the payment. We train only on payments older than the reporting window (for example 60 days) so recent fraud is not counted as honest, and split by time (train on earlier months, test on the latest).
- **What real data cannot carry:** an active phone call and the words the user said exist only in the app at the moment of payment. They are 0 in historical data, so the real-data model learns the behavioural signals; the hard rules for call and scam words stay in place on top.
- **Size:** a few months of transactions for a sample of accounts with the confirmed fraud cases from the same period is enough for a first comparison.

## Model card template for the real-data run

| | Synthetic (current) | Real data |
|---|---|---|
| Transactions / users / fraud share | `risk_metrics.json → dataset` | `risk_metrics_real.json → dataset` |
| PR-AUC, ROC-AUC, Brier (test, by time) | | |
| Scams flagged / held at RED | | |
| Honest payments warned / held | | |
| Thresholds (max 2% honest held, 12% warned) | | |
| Top features (SHAP) | | |
