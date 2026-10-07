# Real Bangla speech evaluation (R1)

Parser accuracy (100%) was measured on 96 **typed** commands. This study
measures what happens when real people **speak** them, on the phones they
use, in the places they use them: the phone's speech recognition (STT) plus
our parser, end to end.

**The number that matters most:** the *silent wrong amount* rate, a wrong
amount the app would show without stopping to ask. **Target: ≤ 1%.**

Everything up to running the sessions is built. What is left is the part only
people can do: recruit, record and run the analysis.

## What is measured

| Metric | Meaning |
|---|---|
| WER, CER | Word / character error rate of the STT transcript against the prompt (jiwer). Bangla digits are mapped to ASCII and punctuation and thousands separators removed before comparing. Free-form tasks have no reference, so no WER. |
| Intent accuracy | Send money, recharge, balance, cash out, unsupported, unknown: right or wrong |
| Amount accuracy | The right amount, or "asked" when the command has no clear amount ("ammu ke 500 1000 pathao") |
| Recipient accuracy | The right contact or number; "asked" for the ambiguous "Rahim". A fuzzy name in the typed set ("rohim bhai") also counts as right when it comes back exact, since spoken spellings sound the same. |
| Clarification rate | Utterances where the app stopped to ask: a parser question, or STT confidence < 0.6 (the app then makes the user check the words, see `docs/FAILURE_POLICY.md`) |
| **Silent wrong amount** | A wrong amount (including picking one where it had to ask) **and** STT was not unsure. Same idea as `ml/evaluate_parser.py`, with the unsure-speech guard counted as asking. |
| Silent wrong recipient | A different contact or number with status `ok` and STT not unsure |
| STT unsure rate, mean confidence | How often the recognizer itself flags low confidence (some engines report none: logged as `has_confidence: false`) |

All of it overall and **by condition, dialect, age band and gender**
(`ml/evaluate_audio.py`). The 25 worst rows, silent errors first, are listed
in the output so the fixes are obvious.

## Design

**Participants: 12 or more**, adults (18+), spread so every cell has someone:

| | 18–30 | 30–50 | 50+ |
|---|---|---|---|
| Women | 2+ | 2+ | 2+ |
| Men | 2+ | 2+ | 2+ |

Across them, at least two speakers from each of **Dhaka, Chattogram, Sylhet,
Barishal and Rajshahi** dialect areas (Khulna, Rangpur and Mymensingh are
welcome extras). Include people who use a feature phone or rarely type: they
are who the voice flow is for.

**Conditions: every speaker records all three** (order rotated between
speakers):

| Condition | Where | Rough level |
|---|---|---|
| `quiet` | Closed room, no fan noise near the phone | under 40 dB |
| `street` | Roadside or a market lane, normal traffic | 65–75 dB |
| `bus_tv` | Inside a bus or CNG, or a TV at normal volume about 2 m away | 60–70 dB |

(Any free sound-meter app is fine for a rough reading; note it in the
session's device field if you like.)

**Script: 106 prompts per condition**, served by the API so every phone uses
the same list (`GET /api/eval/prompts`, demo sites only):

- the 96 labelled commands in `data/test_commands.json`, each shown in
  **Bangla script**. Commands typed in Banglish or English carry the spoken
  Bangla text from `data/audio_eval_prompts.json` ("Ammu ke 500 taka pathao"
  is read as "আম্মুকে ৫০০ টাকা পাঠাও"), because bn-BD recognition writes Bangla
  script and the prompt is also the WER reference;
- 10 free-form tasks said in the speaker's own words ("send your mother 800
  taka for the bazar"), checked for intent, amount and recipient.

The order is shuffled per speaker and condition (same order on a rerun).
About 20–25 minutes per condition; offer a break between conditions.

Speakers who read comfortably read the prompt (`mode: read`). Others repeat
after the facilitator (`mode: repeat`), who reads it once in neutral Bangla;
the speaker then says it their own way.

## Consent

Every participant signs a consent form before recording. It must say, in
Bangla, that:

- the study tests whether the app understands spoken Bangla; it is not a test
  of the person;
- **no voice recording is saved**: the phone turns speech into text and only
  the text, the recognizer's confidence score and what the app understood are
  kept;
- they are identified only by a code (P01, P02 ...), an age band, gender and
  home district; no name, phone number or exact age is stored;
- the prompts use made-up names and numbers; they should not say real ones;
- taking part is voluntary, they can stop at any time without giving a
  reason, and their rows are deleted on request (by participant code);
- who to contact, and any token of thanks offered.

Keep the signed forms on paper, separate from the logs. The facilitator ticks
"The participant signed the consent form" in the app before starting; the app
will not start without it.

## Running a session

1. **Server.** Run the API on a demo site so the study endpoint exists:
   `cd api && DEMO_MODE=true uvicorn app.main:app --host 0.0.0.0 --port 8000`
   (or use the deployed demo site). Gemini stays as configured; the log
   records whether the LLM cross-check ran (`llm_used`). To measure the rule
   parser alone, start the server without `LLM_PROVIDER` and say so in the
   write-up. **Production must use a local model plus redaction of names and
   numbers before any LLM call**, not a cloud LLM on raw transcripts.
2. **Phone** (the Android phones in `docs/DEVICE_TESTS.md`):
   - APK straight into evaluation mode:
     `cd app && flutter build apk --release --dart-define=EVAL_MODE=true --dart-define=API_BASE=https://your-demo-host`
   - or open the demo web app in Chrome on the phone, unlock with PIN 1234,
     then **Settings (tune icon) → Evaluation mode (real speech)**.
   Allow the microphone when asked. The study always listens in Bangla
   (bn-BD), whatever the UI language.
3. **Setup screen:** participant code, age band, gender, dialect, condition,
   how they speak (read / repeat), phone model and Android version, consent
   tick. The app switches to demo user u1 (Rahima), whose contacts the labels
   refer to.
4. **Each prompt:** tap the mic, the speaker says it, the app shows what it
   heard, the confidence and what it understood. Then:
   - **Next**: keep it and move on. Wrong transcripts are the data: keep them.
   - **Again**: only when the *speaker* misread or stumbled, never because the
     app misheard. Only the last attempt counts.
   - **Skip**: the speaker cannot or does not want to say it.
   - "Test without a mic" is for checking the setup; typed rows are not counted.
5. **After each condition:** "Next condition (same participant)". After each
   participant: **Export log** (download icon). On web it downloads
   `bolo-audio-P03-....json`; in the APK it copies the JSON to the clipboard:
   paste it into a file. Logs live in memory until exported: export before
   closing the app.

Put the files in `data/eval_logs/` (git-ignored: transcripts stay off GitHub
unless you choose to publish them).

## Analysis

```bash
pip install -r ml/requirements.txt          # includes jiwer
python ml/evaluate_audio.py data/eval_logs/*.json
```

This writes `model/audio_metrics.json`; restart the API and the Accuracy tab
shows **1b. Real Bangla speech** with the breakdown by condition and dialect,
and whether the ≤ 1% target is met. Until then the tab shows the synthetic
sample (`data/eval_sample/audio_log_SAMPLE.json`), labelled "SAMPLE, not real
results"; delete `model/audio_metrics.json` to show "not run yet" instead.

To check a parser fix against the same speech without new recordings:

```bash
python ml/evaluate_audio.py data/eval_logs/*.json --reparse --out /tmp/after_fix.json
```

## What the results will point to

- **Number words and dialect spellings** the recognizer writes that
  `api/app/core/numbers.py` does not know yet ("পাঁচ শ", "দেড়শ") → add them.
- **Names** written differently from the alias lists in `data/seed.json`
  → add the spellings.
- **Where the confidence threshold sits:** if silent wrong amounts cluster
  just above 0.6, raise `Voice.minConfidence` (the confirm step is cheap; a
  wrong amount is not).
- **Noise:** if `bus_tv` fails far more than `quiet`, prefer push-to-talk
  with a visible transcript in noisy places (already the design) and say so in
  the onboarding.

## Publishing the results

Report: number of speakers per cell, utterances, the overall table and the
tables by condition, dialect and age (straight from `audio_metrics.json`),
the silent wrong amount rate against the 1% target, the 10 worst failures with
their fixes, and the limits (phones used, the LLM setting, read vs repeat).
