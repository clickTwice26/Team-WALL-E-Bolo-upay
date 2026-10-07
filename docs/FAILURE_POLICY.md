# AI safety and failure policy

What Bolo upay does when a part of it is unsure, unavailable or disputed. The
rule behind every row: **when in doubt, money does not move without the user
seeing what will happen, and the user can always stop it.**

## When something fails

| Situation | What the app does | What the user sees | Where |
|---|---|---|---|
| Speech recognition unavailable (no mic, browser without Web Speech) | Typing works everywhere | "Voice input is not available here. Please type instead." | `app/lib/screens/assistant.dart` |
| Speech recognized with low confidence (< 0.6) | The transcript is **not** used automatically | "I'm not sure I heard that right. Check the words, fix them if needed, then send." | `app/lib/services/voice.dart`, `assistant.dart` |
| Rule parser and LLM disagree on the amount or recipient | Nothing is guessed: the app asks | "Did you mean ...?" / "Which Rahim?" | `api/app/core/parser.py` |
| LLM down, slow (20 s timeout) or no key | Rule parser only (it scored 100% on the test set) | Nothing changes | `api/app/core/llm.py` |
| Server voice (TTS) fails | Device voice; the text is always on screen | Nothing changes | `app/lib/services/voice.dart` |
| Risk model file missing, unreadable, or trained on other features | Transparent rule scoring with fixed thresholds (0.3 / 0.7) | Warnings still list their reasons | `api/app/core/risk.py` (`load_model`, `_fallback_prob`) |
| Gradient boosting fails at request time | Logistic-regression fallback **with its own thresholds** | Nothing changes | `risk.score` |
| SHAP explanations unavailable | Same score; reasons come from the yes/no signals that are on | Shorter reason list | `risk.assess` |
| API unreachable | **No transfer.** Only the server can move money | "Cannot reach the server." | `api/app/main.py` (`/api/execute`) |
| Session expired | Back to the PIN screen; nothing is sent | PIN screen | `app/lib/main.dart` |
| Too many wrong PINs | Account locked 15 min (doubling), biometrics included | "Too many wrong PINs. Try again in N minutes." | `api/app/auth.py` |
| The agent (LLM or rules) proposes an unsafe action | Dropped by the safety guard: no PIN entry, no biometrics, no ticking the RED box, no skipping a hold | The agent says it can't do that | `api/app/core/agent.py` (`sanitize`) |

## When the score is borderline

- **YELLOW** (probability between the two thresholds): the user answers 2–3
  spoken questions before anything is sent, and the answers are scored again.
- **RED from a hard rule** (PIN/OTP request, fake upay staff, "send it back" with
  no money received, relative in trouble from a new number) is final: no
  interview can talk it down.
- Thresholds are tuned to hold at most 2% and warn at most 12% of honest
  payments on an earlier time slice (`ml/train_risk.py`).

## When the user disagrees

| The user... | What happens |
|---|---|
| Thinks a RED warning is wrong | They can still send after the 30-second hold, ticking the warning and entering the PIN. The override is counted (monitoring below). |
| Taps **"This warning seems wrong?"** | Stored as a label (`POST /api/feedback`). It never changes the transfer; it feeds the threshold review and retraining. |
| Wants a person | "Talk to a person" (or two misunderstandings in a row, or reporting a scam) hands the chat to support staff, with scam cases first. Staff can stop a pending transfer; they cannot send money or see a PIN. |

## Monitoring

`GET /api/admin/monitor` (ops: `X-Admin-Token`; any signed-in user on a demo
site) and the **Model health** card on the dashboard report the last 14 days:

| Signal | Alert when | Why |
|---|---|---|
| Drift: PSI of each input against its training distribution | PSI > 0.2 for any input (with ≥ 30 checks) | The world changed since training; thresholds may no longer hold |
| Level mix (GREEN / YELLOW / RED) vs training | Shown next to each other | A sudden jump in RED or YELLOW |
| RED transfers still sent | > 30% (with ≥ 10 RED) | RED too strict, or people being talked past the warning |
| Warnings reported wrong | > 20% (with ≥ 10 warnings) | YELLOW threshold too low |
| Support handoffs by reason, waiting now, median wait | Shown | Scam reports and support load |

Every API request also writes one JSON log line with a request id (returned as
`X-Request-ID`), method, route, status and time. No bodies are logged, so no
phone numbers, PINs or answers.

## Threshold review

- **When:** monthly, and at once when the monitor raises an alert.
- **Who:** the risk owner at upay (in the prototype, Team WALL-E). A second
  person signs off any threshold change.
- **How:** rerun `python ml/train_risk.py` with the latest labelled outcomes
  (confirmed scams, "warning was wrong" reports, disputes). Compare the test
  split with the current thresholds, and change thresholds only within the
  2% held / 12% warned limits. Record the decision and the numbers in
  `model/risk_metrics.json` (it is versioned with the model).
