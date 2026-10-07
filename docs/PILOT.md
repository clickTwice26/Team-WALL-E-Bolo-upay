# Pilot proposal: Bolo upay with real upay customers

Everything Bolo upay reports today comes from simulated data. A controlled
pilot is how we would replace the simulation with real numbers. This is what
we propose to run with upay.

## Design

| | |
|---|---|
| Who | 5% of active upay customers who opt in, split at random: half get Bolo upay (voice + scam shield), half keep the current app (control) |
| How long | 8 weeks: 2 weeks shadow mode (scores logged, no warnings shown), then 6 weeks live |
| Where | upay sandbox first, then production behind a feature flag |
| Data | Stays with upay on upay's servers; models retrained on governed data only (see the data request in the judge-feedback plan) |
| Safety | Money only moves with the customer's PIN or biometric; a held transfer can always be cancelled; support handoff on every warning screen |

Shadow mode lets us measure honest-warning rates on real traffic before any
customer sees a warning, and tune the thresholds within the 2% held / 12%
warned limits (`docs/FAILURE_POLICY.md`).

## KPIs (pilot group vs control, per 1,000 transfers)

| KPI | Why it matters | Target |
|---|---|---|
| Fraud loss (Tk) | The money the shield is meant to save | Lower than control |
| Confirmed scams stopped | Scams caught before money left | Measured, with the scam type |
| Dispute tickets (wrong number / amount) | Call-centre load the mistake guard should cut | Lower than control |
| Transfer completion rate | The shield must not stop honest payments | Within 1 point of control |
| Honest payments warned / held | The false-warning cost | ≤ 12% warned, ≤ 2% held |
| "This warning seems wrong" reports | Users' own view of false warnings | Tracked weekly |
| Payments given up after a warning | The real cost of a false warning | Tracked weekly |
| CSAT after a warning | Did the warning feel helpful or annoying? | ≥ control |
| Voice success rate | Commands understood without retyping, by dialect and age | Tracked weekly |

## ROI

```
yearly benefit = fraud loss avoided + dispute handling cost avoided + retained transfers
yearly cost    = honest payments given up after warnings + support time for handoffs + running cost
ROI            = (benefit − cost) / cost
```

`GET /api/impact` already computes this chain on simulated rates with the
low / mid / high assumptions in `data/impact_assumptions.json`. The pilot
replaces each assumption with a measured value.

## What we need from upay

1. Sandbox API access for send money, cash out and merchant payment.
2. Anonymized (salted-hash) transaction histories and confirmed fraud labels
   for retraining, on upay's servers.
3. A feature flag and an opt-in screen for the 5% pilot group.
4. Weekly access to dispute and CSAT numbers for both groups.
