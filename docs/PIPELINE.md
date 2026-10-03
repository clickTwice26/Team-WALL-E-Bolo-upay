# Bolo upay — System Pipeline

Voice-first Bangla payment assistant with a built-in scam and mistake shield.
Prototype for AI Dev Fest 2026 AI Hackathon (DIU CPC × upay). Synthetic data only.

## 1. End-to-end flow

```
[1] Voice / text input (Bangla, Banglish, English)
        │  Web Speech API (bn-BD) → transcript shown, editable
        ▼
[2] Normalizer
        │  Bangla digits → ASCII, Bangla number words → number, spelling unification
        ▼
[3] Intent parser (two independent paths)
        │  A: LLM → strict JSON {intent, amount, recipient, confidence}
        │  B: rule parser → {intent, amount, recipient}
        │  Cross-check: amount/intent disagree or low confidence → ask user (never guess)
        ▼
[4] Recipient resolver
        │  fuzzy match against contacts ("Rahim bhai" → Rahim Uddin)
        │  0 matches → treat as new number; 2+ matches → user picks
        ▼
[5] Risk engine
        │  features from transaction history + context
        │  ML score (logistic regression / gradient boosting) + hard rules
        │  → GREEN / YELLOW / RED + top reasons
        ▼
[6] Scam interview (YELLOW/RED only)
        │  AI asks 2–3 Bangla questions aloud, user answers by voice
        │  answers matched against data/scam_phrases.json → risk updated
        ▼
[7] Confirmation screen
        │  large text, recipient name + amount, read back by voice
        ▼
[8] Risk-based authentication
        │  GREEN → fingerprint (WebAuthn) or PIN
        │  YELLOW → PIN required + warning
        │  RED → hold + cooling-off timer + warning, then PIN
        ▼
[9] Execute (simulated) + log
        │  transaction saved, decision + reasons logged (no PIN, no raw audio)
        ▼
[10] Ops dashboard + Accuracy Report
```

## 2. Components

### [1] Voice input
- Browser Web Speech API, `lang = "bn-BD"` (fallback `en-US`), Chrome.
- Always show the transcript in an editable box. Text input always available.
- Raw audio never leaves the browser.

### [2] Normalizer (`lib/normalize.ts`)
- Bangla digits ০-৯ → 0-9.
- Number words: এক…একশো, শো/শ, হাজার, লাখ, দেড় (1.5), আড়াই (2.5), সাড়ে (+0.5), "5k", "5 hazar".
- Unify spellings: pathao/pathan/পাঠাও; taka/tk/টাকা; recharge/rechaj/রিচার্জ.
- Unit tests on every rule.

### [3] Intent parser (`lib/intent.ts`, `/api/parse`)
- Intents: `send_money`, `mobile_recharge`, `check_balance`, `unknown`.
- Path A (LLM): system prompt + JSON schema, temperature 0, returns
  `{intent, amount, recipient_text, confidence}`.
- Path B (rules): regex + keyword tables over normalized text.
- Decision:
  - both agree → accept
  - amounts differ → ask "500 na 5000?"
  - confidence < 0.8 or intent unknown → ask a clarifying question
- No LLM key → Path B only (app still works).

### [4] Recipient resolver (`lib/contacts.ts`)
- Fuzzy match (normalized Levenshtein / token match) on name + nickname (Ammu, Abbu, bhai, apa).
- Phone number spoken → validate BD format `01[3-9]XXXXXXXX`.
- Output: contact or `new_number` flag.

### [5] Risk engine (`lib/risk.ts`, model trained in `ml/train_risk.py`)
Features:
| Feature | Meaning |
|---|---|
| is_new_recipient | never sent to this number before |
| amount_ratio | amount ÷ user's median send amount |
| amount_vs_recipient | amount ÷ usual amount to this recipient |
| hour | late night (00:00–05:00) |
| sends_last_30min | rapid repeated sends |
| balance_fraction | share of balance being sent |
| on_active_call | (native app signal; simulated toggle in prototype) |
| return_claim_no_inflow | user says "ferot" but no incoming money from that number |
| scam_phrase_score | from scam interview answers |

- Model: logistic regression (explainable weights) trained on synthetic labeled scenarios; exported to `model/risk_weights.json` and run in TypeScript.
- Hard rules override: `return_claim_no_inflow` → RED; PIN/OTP phrase → RED.
- Thresholds: score < 0.3 GREEN, 0.3–0.7 YELLOW, ≥ 0.7 RED (tuned on validation set).
- Output: level + top 3 reasons in Bangla and English.

### [6] Scam interview (`lib/interview.ts`)
- Questions (Bangla, spoken via SpeechSynthesis):
  1. কেউ কি ফোন করে এই টাকা পাঠাতে বলেছে?
  2. সে কি নিজেকে উপায় অফিস / কাস্টমার কেয়ার বলেছে?
  3. সে কি আপনার পিন বা ওটিপি চেয়েছে?
- Answers → normalizer → scam phrase matcher (exact + fuzzy) → category hits → score.
- Shows which phrase triggered and the category explanation.

### [7] Confirmation
- Recipient name, number (masked), amount in large Bangla digits, read aloud.
- Edit / Cancel always visible.

### [8] Authentication
- WebAuthn passkey for fingerprint (platform authenticator). If unsupported → PIN.
- PIN keypad: large keys, Bangla digits, vibration per tap, digits never spoken.
- Demo PIN hashed (SHA-256 + salt), never logged.
- RED: 60-second cooling-off timer + "Call the person on their known number" + helpline 16268.

### [9] Execute + log
- Simulated balance update in the synthetic store.
- Decision log: timestamp, intent, amount, risk level, reasons, user choice (proceeded / cancelled). No PIN, no audio.

### [10] Ops dashboard + Accuracy Report
- Dashboard: attempts by risk level, scam categories caught, amount "protected" (simulated).
- Accuracy Report: runs the labeled test set live (see §4).

## 3. Synthetic data (`ml/generate_data.py`)
- 50 users, each with 5–15 contacts (family nicknames, shops, friends).
- 6 months of transactions per user: send money, recharge, cash-in, cash-out, merchant pay; realistic amounts (Tk 20–20,000), salary-day and month-end patterns.
- Scam scenarios injected with labels: fake official, sent-by-mistake, lottery, allowance fee, relative-in-trouble, OTP request.
- Honest-mistake scenarios: wrong contact, extra zero.
- Split: train 70% / validation 15% / test 15% (test never used for training or threshold tuning).
- No real PII; all names and numbers generated.

## 4. Evaluation (`ml/evaluate.py`, `data/test_commands.json`)
Labeled command test set (150–200 items): Bangla, Banglish, English, Bangla digits, number words, mixed language, ambiguous names, ambiguous amounts.

| Metric | Definition | Target |
|---|---|---|
| Intent accuracy | correct intent / total | ≥ 95% |
| Amount accuracy | correct amount / commands with amount | ≥ 95% |
| Silent wrong amount | wrong amount accepted without asking | 0% |
| Recipient accuracy | correct contact or correct "ask" | ≥ 90% |
| Safe-failure rate | when wrong, share that asked instead of guessing | report |
| Scam recall | scams flagged YELLOW/RED / all scams | report |
| False-alarm rate | normal sends flagged RED / all normal | report |
| Baseline | rules-only risk vs ML risk | report both |

Report measured numbers only.

## 5. Tech stack
| Layer | Choice |
|---|---|
| Frontend + API | Next.js (App Router), TypeScript, Tailwind |
| Speech | Web Speech API (STT), SpeechSynthesis (TTS) |
| LLM | Gemini / OpenAI / Claude via API route; optional |
| ML training | Python, pandas, scikit-learn |
| Model serving | exported JSON weights, inference in TypeScript |
| Auth demo | WebAuthn, hashed PIN |
| Deploy | Vercel (live URL) |

## 6. Repository layout
```
app/                 Next.js pages: / (assistant), /dashboard, /accuracy
app/api/parse        intent API (LLM + rules)
app/api/risk         risk scoring API
lib/                 normalize, intent, contacts, risk, interview, scam matcher
data/                scam_phrases.json, users.json, transactions.json, test_commands.json
model/               risk_weights.json, metrics.json
ml/                  generate_data.py, train_risk.py, evaluate.py
docs/                PIPELINE.md, report
.env.example         LLM_PROVIDER, LLM_API_KEY placeholders
README.md            all 10 required sections
```

## 7. Responsible AI
- Synthetic data only, no PII.
- AI never moves money: confirmation + PIN/fingerprint always required.
- No call recording; scam detection via user answers + history.
- No voice biometrics (spoofable).
- Reasons shown for every warning; false-alarm rate measured.
- Known limits: warnings can be ignored under scammer pressure; account takeover and USSD users not covered.

## 8. Demo script (video, 3–5 min)
1. Problem: 91% of stolen MFS money unrecovered; ~700k disputes; low-literate users make errors.
2. Normal send by voice: "Ammu ke 500 taka pathao" → GREEN → fingerprint.
3. Tricky amount: "Rahim ke দেড় হাজার" → parsed 1500 correctly.
4. Mistake: speech hears 5000 instead of 500 → YELLOW "you usually send 500".
5. Scam: "ferot pathao" with no inflow → RED; fake upay call → interview → RED.
6. Accuracy Report page with measured metrics.
7. Impact + path to production (native app call signal, upay PIN system, pilot).
