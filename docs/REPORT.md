# Bolo upay — Project Report

AI Dev Fest 2026 · AI Hackathon (DIU CPC × upay)
Tracks: 03 Customer Innovation & Financial Independence · 01 Trust & Risk Intelligence

## 1. Problem

**For** upay customers who send money by phone, especially first-time and low-literate users,
**scams and payment mistakes** cause losses that are almost never recovered.
**We built** a voice-first Bangla payment assistant that uses the customer's own transaction history and their spoken answers
**to** stop risky transfers before the money leaves, **measured by** scams flagged, honest transfers wrongly held, and wrong amounts shown without asking.

Evidence:
- Bangladesh Bank data (New Age, 3 July 2026): MFS fraud of Tk 81.32 crore in 2025; **91.3% never recovered**, because funds move through mule wallets within minutes. MFS fraud is more than 88% of all unrecovered payment fraud. Officials recommended AI-driven fraud detection.
- The same report: MFS providers handled **699,605 customer disputes worth Tk 153.98 crore** in 2025.
- Most MFS fraud starts with the victim being talked into sharing a PIN/OTP or sending money (bKash, quoted in the same report).
- Interviews with low-literate MFS users in Bangladesh report frequent transaction errors (ACM, "Smartphone based Inclusive MFS Design for Low-Literate Population").
- upay is a challenger with high customer-acquisition costs (Tk 313 crore accumulated losses 2021–2023, The Business Standard). Trust and ease of use are what keep acquired customers active.

## 2. Idea

Recovery after a scam rarely works. The only moment money can reliably be saved is **before the user presses send**. Bolo upay puts a careful, explainable AI check at that moment, inside a payment flow that people can use simply by speaking Bangla.

We do not listen to phone calls (not possible on iOS/Android, and a privacy problem). Instead, the assistant **asks the user** two or three short questions when a transfer looks risky, and checks the answers for scam patterns.

## 3. Implemented solution

```
speak → transcript (editable) → rule parser + optional LLM → cross-check (ask if they disagree)
→ recipient resolution → risk features from history → ML score + hard rules + mistake guard
→ GREEN / YELLOW / RED → (scam interview) → confirmation read aloud
→ risk-based authentication (fingerprint / PIN / hold + PIN) → transfer (simulated) → decision log
```

Components:
- **Flutter app** (iOS, Android, Web): home screen, voice assistant, clarification, interview, warning and hold screens, PIN pad, Face ID / fingerprint, ops dashboard, accuracy report.
- **FastAPI backend**: parse, assess, execute, cancel, dashboard, metrics. Authentication rules are enforced on the server.
- **ML pipeline**: synthetic data generator, risk model training with validation-tuned thresholds, parser evaluation on a labelled command set.
- **Deployment**: one Docker image (API + web app on one origin) behind Caddy with automatic HTTPS.

## 4. Key features

1. Bangla, Banglish and English commands, including Bangla number words (দেড় হাজার = 1,500, আড়াইশো = 250, সাড়ে তিন হাজার = 3,500, পৌনে দুই হাজার = 1,750), Bangla digits, "5k", and spoken phone numbers.
2. Never guesses money or people: two amounts → asks; two contacts named Rahim → asks; a misheard name → asks to confirm.
3. Scam shield with three levels and reasons in plain Bangla.
4. Scam interview by voice, with negation handling.
5. Hard rules for unambiguous evidence, e.g. "send it back" when no money arrived from that number.
6. Mistake guard: "You usually send this person about ৳360. Did you mean ৳350?"
7. Risk-based authentication: fingerprint only for low risk; PIN for medium; 30-second hold, warning acknowledgement and PIN for high risk.
8. Ops dashboard: transfers cancelled after a warning and money protected.
9. Accuracy report inside the app.

## 5. AI approach

| Part | Method | Why |
|---|---|---|
| Speech | On-device STT, editable transcript | Speech recognition makes mistakes; the user can always fix the text |
| Command parsing | Deterministic Bangla/Banglish/English parser + optional LLM with structured output; disagreement → ask | Money needs a second opinion. The parser is predictable; the LLM handles phrasing the rules miss |
| Recipient | Alias matching with Bangla case suffixes, longest-alias wins, fuzzy match with confirmation | Real contact lists have duplicates and nicknames |
| Risk score | Logistic regression on 9 features (new recipient, amount vs usual, night, rapid sends, share of balance, active call, refund claim without inflow, scam-phrase score, recharge) | Close to gradient boosting in AUC (0.986 vs 0.992) and fully explainable |
| Thresholds | Tuned on a validation split: honest transfers held ≤ 2%, then maximise scams flagged | Controls friction for honest users explicitly |
| Scam phrases | Lexicon of 8 scam types in Bangla, Banglish, English; exact + fuzzy match; negation-aware | Victims repeat what the scammer said |
| Evaluation | Two-stage (command only, then with interview answers), 70/15/15 split, rules-only baseline | Mirrors how the app actually decides |

**Results** (see the Accuracy tab and `model/*.json`):
- Parser, 96 labelled commands: intent, amount and recipient 100%; **wrong amount shown without asking: 0%**. The commands were written by the team, so real speech will be harder.
- Scam shield, 1,200 synthetic held-out scenarios: **91.9% of scams flagged** (rules-only baseline 53.1%), 73.8% held at RED (baseline 16.2%), **1.1% of honest transfers held** (baseline 0.9%), 13.4% of honest transfers asked for a PIN and shown a warning.
- These numbers come from simulated data; they show the pipeline works as designed, not real-world fraud performance.

## 6. Real-life impact

- **Customers:** a 10-second pause with the right question at the right moment, in their own language. Scam victims are stopped before the money leaves, which matters because recovery afterwards is rare.
- **upay:** fewer disputes from wrong-number and wrong-amount transfers; less fraud loss and reputational damage; a clear difference from competitors; voice access for customers who avoid the app today, which brings more safe transactions.
- **Measurable pilot metrics:** scams cancelled after a warning, money protected, disputes per 10,000 transfers, false-alarm rate, voice-command completion rate.

## 7. Responsible AI and security

Synthetic data only; no PII. No call recording; no voice biometrics. The AI never moves money. Server-side enforcement of authentication by risk level; hashed PIN; 3 wrong PINs lock the transaction. Every warning is explained. False alarms are measured and reported, and thresholds are chosen to limit them.

## 8. Limitations and next steps

- Synthetic training data → validate on governed, anonymised upay data (controlled validation stage).
- Team-written test commands → collect real Bangla voice commands from consenting pilot users.
- Bangla speech recognition varies by device → evaluate on-device and server ASR options.
- A pressured victim can still ignore a warning; account takeover and USSD users are not covered → add delayed release / call-back for very risky transfers and an SMS confirmation path for USSD.
- Native call-state signal is simulated → implement in the native upay app with user permission.

## 9. Path to production

Competition → technical and business review → controlled validation on governed data → POC inside the upay app (send money only) → pilot with first-time users → measure scams stopped, disputes, false alarms and completion rate → integrate.
