# Team WALL-E · বলো upay (Bolo upay)

**A voice-first Bangla payment assistant with a built-in scam and mistake shield.**
Prototype by **Team WALL-E** (Shagato Chowdhury, Umme Munia) for the AI Dev Fest 2026 AI Hackathon (DIU CPC × upay). Track 03 (Customer Innovation & Financial Independence) and Track 01 (Trust & Risk Intelligence).

> This is a hackathon prototype. It is **not the official upay app**, it moves no real money, and all users, numbers and transactions are synthetic.

**Live deployment:** `https://<your-domain>` ← replace with the deployed URL before submitting

---


## Screenshots

| PIN login | Home | Voice input |
|---|---|---|
| ![](docs/screenshots/00_login.png) | ![](docs/screenshots/01_home.png) | ![](docs/screenshots/02_voice_input.png) |
| **Normal send (GREEN)** | **PIN** | **Done** |
| ![](docs/screenshots/03_green.png) | ![](docs/screenshots/09_pin.png) | ![](docs/screenshots/10_done.png) |
| **Which Rahim?** | **Extra zero?** | **Scam interview** |
| ![](docs/screenshots/04_which_rahim.png) | ![](docs/screenshots/05_extra_zero.png) | ![](docs/screenshots/06_interview.png) |
| **Fake upay call (RED)** | **Hold before PIN** | |
| ![](docs/screenshots/07_red.png) | ![](docs/screenshots/08_hold.png) | |

## 1. Project overview

**Problem.** Mobile financial services in Bangladesh lose most stolen money for good. Bangladesh Bank figures (reported by New Age, July 2026) show Tk 81.32 crore of MFS fraud in 2025, of which 91.3% was never recovered: scammers move money through mule wallets within minutes. MFS providers also handled about 700,000 customer disputes worth Tk 153.98 crore. Low-literate users find menu-driven apps hard and make transaction errors (wrong number, extra zero), and most scams work by talking a victim into sending money themselves.

**Solution.** Bolo upay lets a user say a payment in Bangla, Banglish or English ("আম্মুকে দেড় হাজার টাকা পাঠাও"). Before any money moves, it:
1. understands the command with two independent parsers and **asks instead of guessing** when they disagree,
2. runs a **risk check** on the user's own history (new number, unusual amount, active phone call, "send it back" with no money received, and more),
3. for risky transfers, **asks 2–3 short questions aloud** ("Did someone call you asking for this money?") and checks the answers for scam patterns,
4. adjusts authentication to the risk: fingerprint for low risk, PIN for medium, **hold + warning + PIN** for high risk.

**Purpose.** Stop scams and mistakes at the only moment money can still be saved, before the user presses send. Make digital payments usable for people who struggle with menus, which brings more safe transactions to upay.

## 2. Features and how AI is used

| Feature | AI / logic used |
|---|---|
| Voice input in Bangla / English, editable transcript | On-device speech-to-text (`speech_to_text`, Web Speech API on web). Audio never leaves the device |
| Command understanding | **Rule parser** (Bangla number words like দেড়, আড়াই, সাড়ে, পৌনে; Bangla digits; phone numbers; intents) **plus optional LLM** (Anthropic, OpenAI or Gemini) returning structured JSON. If the amounts disagree, the app asks |
| Recipient resolution | Alias matching with Bangla case suffixes (আম্মুকে, rahim-ke) and fuzzy matching for speech errors; ambiguous names → the user picks; fuzzy → the user confirms |
| Scam risk score | **Logistic regression** on history-derived features, thresholds tuned on a validation split, explainable per feature |
| Scam interview | Spoken questions; answers matched against a Bangla/Banglish/English scam phrase lexicon (`data/scam_phrases.json`) with negation handling ("keu otp chay nai" is not a hit) |
| Hard rules | Asking for a PIN/OTP, fake upay staff, lottery/fee, allowance fee → RED. "Send it back" when no money came from that number → RED. "Relative in trouble" from a new number → RED |
| Mistake guard | Known recipient + amount about 10× the usual → "Did you mean ৳350?" |
| Risk-based authentication | GREEN: Face ID / fingerprint or PIN · YELLOW: PIN · RED: 30-second hold, warning acknowledgement, then PIN. Enforced by the server, not the client |
| Explanations | Every warning lists its reasons in Bangla and English |
| Ops dashboard | Decisions by risk level, transfers cancelled after a warning, money protected, scam patterns seen |
| Accuracy report | Measured parser accuracy and scam-shield metrics, shown live in the app |

What the app deliberately does **not** do: it never listens to phone calls, never uses voice biometrics (voices can be cloned), and never sends money without the user's PIN or biometric confirmation.

## 3. Technology stack

| Layer | Technology |
|---|---|
| App (iOS, Android, Web) | Flutter 3 (Dart), Material 3, bundled Hind Siliguri font, UI follows upay's yellow/blue design language and the public upay UX case study by Shadhin Lablu (Dribbble) |
| Voice | `speech_to_text` (STT), `flutter_tts` (TTS) |
| Biometrics | `local_auth` (Face ID / Touch ID / fingerprint) |
| Backend API | Python 3.11, FastAPI, Pydantic, Uvicorn |
| ML | scikit-learn (logistic regression, gradient boosting for comparison), NumPy, joblib |
| Text matching | RapidFuzz |
| LLM (optional) | Anthropic Python SDK (`claude-opus-5-5` by default), OpenAI or Gemini via REST |
| Storage | SQLite (prototype) |
| Security | bcrypt-hashed demo PIN, server-side authentication rules |
| Tests | pytest (39 tests), parser evaluation script |
| Deploy | Docker, Docker Compose, Caddy (automatic HTTPS) |

## 4. Requirements

- **To run the API:** Python 3.11+
- **To build the app:** Flutter SDK 3.x (stable). iOS builds need a Mac with Xcode and CocoaPods
- **To deploy:** a Linux server with Docker and Docker Compose, a domain (or subdomain) pointing to the server, ports 80 and 443 open
- **Browser:** Chrome or Edge for voice input on the web build (Web Speech API). Typing works in every browser
- **HTTPS is mandatory for voice:** browsers block the microphone on plain `http://` (except `localhost`)

## 5. Installation and setup

```bash
git clone https://github.com/clickTwice26/Team-WALL-E-Bolo-upay.git
cd Team-WALL-E-Bolo-upay

# backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r api/requirements.txt

# (optional) regenerate synthetic data, retrain the model, re-run the evaluation
python ml/generate_data.py
python ml/train_risk.py
python ml/evaluate_parser.py

# app
cd app
flutter pub get
```

## 6. Environment variables

Copy `.env.example` to `.env`. Never commit `.env`.

| Variable | Purpose | Example |
|---|---|---|
| `DOMAIN` | Public domain for HTTPS (Caddy) | `bolo.example.com` |
| `LLM_PROVIDER` | Optional second parser: `anthropic`, `openai` or `gemini`. Empty = rules only | `anthropic` |
| `LLM_API_KEY` | Key for that provider | `<your-key>` |
| `LLM_MODEL` | Optional model override | `claude-opus-5-5` |
| `HOLD_SECONDS` | How long a RED transfer stays on hold | `30` |
| `CORS_ORIGINS` | Allowed origins for the API | `*` |
| `DB_PATH` | SQLite file (set by Docker to `/data/bolo.db`) | `data/bolo.db` |
| `WEB_DIR` | Folder of the Flutter web build served at `/` | `app/build/web` |
| `API_BASE` (Flutter build flag) | API URL for iOS/Android builds | `--dart-define=API_BASE=https://bolo.example.com` |

## 7. Run and build commands

**Local development**
```bash
# terminal 1: API on http://localhost:8000 (docs at /docs)
cd api && uvicorn app.main:app --reload --port 8000

# terminal 2: build the web app; the API serves it at http://localhost:8000
cd app && flutter build web --release --no-web-resources-cdn
```

**iPhone (via Xcode or flutter)**
```bash
cd app
flutter run -d <iphone-id> --dart-define=API_BASE=https://bolo.example.com
# or: cd ios && pod install && open Runner.xcworkspace  (pick your Team under Signing)
```

**Android APK**
```bash
cd app && flutter build apk --release --dart-define=API_BASE=https://bolo.example.com
# output: app/build/app/outputs/flutter-apk/app-release.apk
```

**Production (your server)**
```bash
cp .env.example .env        # set DOMAIN, optional LLM key
docker compose up -d --build
docker compose logs -f app  # check it started
```
The app and API are served together at `https://$DOMAIN`.

## 8. Live deployment URL

`https://<your-domain>` ← replace before submission.

Unlock the app with the **demo PIN `1234`**. Use the settings button (top right on the home screen) to switch between three synthetic users, toggle Bangla/English, and simulate "on a phone call". The **demo PIN is `1234`**.

## 9. Testing

```bash
cd api && python -m pytest -q          # 39 tests: parser, scam matcher, API flow
python ml/evaluate_parser.py           # labelled command set → model/parser_metrics.json
python ml/train_risk.py                # trains and evaluates → model/risk_metrics.json
```

**Measured results**

| Parser (96 labelled commands, rules only) | Result |
|---|---|
| Intent / amount / recipient accuracy | 100% / 100% / 100% |
| Wrong amount shown without asking | **0%** |

These commands were written by the team alongside the parser, so they show the parser handles the listed patterns; real user speech will be harder. Collecting real commands is the next step.

| Scam shield (1,200 synthetic held-out scenarios) | Bolo upay | Rules only |
|---|---|---|
| Scams flagged (YELLOW or RED) | 91.9% | 53.1% |
| Scams held (RED) | 73.8% | 16.2% |
| Honest transfers held (RED) | 1.1% | 0.9% |
| Honest transfers warned (YELLOW or RED) | 13.4% | 6.1% |

The scenarios are simulated (no real fraud data is available). The numbers show the pipeline behaves as designed, not real-world performance. Test AUC: logistic regression 0.986, gradient boosting 0.992; logistic regression was chosen because every warning can be explained.

**Manual test script** (with the deployed app, user "Rahima Begum"):
1. "আম্মুকে দেড় হাজার টাকা পাঠাও" → GREEN, ৳1,500 to Ammu, fingerprint or PIN.
2. "rahim ke 500 taka pathao" → asks which Rahim (brother or shop).
3. "rahim store ke 3500 taka" → "Did you mean ৳350?".
4. "01799998888 e 2000 taka ferot pathao" → RED: no money came from this number.
5. Turn on "simulate phone call", say "01799998888 e 5000 taka pathao", answer "upay office theke phone dise" → RED with a 30-second hold.

## 10. Other configuration

- **Microphone and Face ID permissions** are declared in `app/ios/Runner/Info.plist` and `app/android/app/src/main/AndroidManifest.xml`.
- **Bangla speech recognition** depends on the device. Chrome on Android and desktop supports `bn-BD`. If Bangla is not available on a device, switch the app to English or type the command.
- **Fingerprint** works in the iOS and Android builds. The web build uses PIN only.
- **Phone-call signal:** a native upay app can know a call is active (not its content). The prototype simulates this with a toggle.
- **Reset demo data:** settings → "Reset demo data", or `POST /api/demo/reset`.
- **API docs:** `https://<your-domain>/docs` (OpenAPI).
- **Disclosure of external resources:** Flutter and pub packages, FastAPI, scikit-learn, RapidFuzz, Hind Siliguri font (SIL Open Font License, `app/assets/fonts/OFL.txt`), optional LLM APIs. AI coding assistants were used during development. All data is synthetic.

## Repository layout

```
api/            FastAPI backend (app/core: parser, numbers, contacts, scam, features, risk, llm)
app/            Flutter app (iOS, Android, Web)
ml/             generate_data.py, train_risk.py, evaluate_parser.py
data/           seed.json (synthetic), scam_phrases.json, test_commands.json
model/          risk_model.joblib, risk_metrics.json, parser_metrics.json
deploy/         Dockerfile, Caddyfile
docs/           Bolo-upay-Report-Team-WALL-E.pdf (project report), report/ (LaTeX source),
                PIPELINE.md, REPORT.md, DEMO_SCRIPT.md
```

## Responsible AI

Synthetic data only. No call recording. No voice biometrics. The AI never moves money; the user always confirms with a PIN or biometric. Every warning shows its reasons. Honest-user friction (false alarms) is measured and reported. Known limits: a pressured victim can still ignore a warning; account takeover (scammer using a stolen PIN on their own phone) and USSD users are outside this prototype.
