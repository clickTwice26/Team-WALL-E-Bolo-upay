# Voice guard (R10)

The voice guard looks for signs that someone is being talked through a payment: a scammer on
the line, on the loudspeaker, or standing next to them. It is **an extra check next to the PIN
and never replaces it.** Voices can be cloned and recordings can be replayed, so a matching
voice never lowers the risk or the authentication. Only a warning sign can raise them.

## What the phone measures

| Signal | How | Status |
|---|---|---|
| `hesitation` (0..1) | The share of the spoken command spent in pauses of 0.3 s or longer. It comes from the speech recognizer's sound-level stream (`speech_to_text` `onSoundLevelChange`): the speech window runs from the first loud sample to the last one, and "quiet" means closer to the noise floor than to speech (`VoiceGuard.pauseRatio`). The result is null for a command shorter than 1.5 s or with no clear voice above the noise. | **Measured on Android.** Not measured on the web: the Web Speech API reports no levels. |
| `speaker_echo` (yes/no) | The phone is in a call (R11 call detection: GSM, or WhatsApp/IMO through the audio mode) **and** call audio is on the loudspeaker (`AudioManager`). This is the classic "the scammer talks the victim through it on speaker" pattern. | **Measured on Android** once call detection is allowed. |
| `voice_mismatch` (yes/no) | This command was not spoken by the enrolled owner. | **Pending:** always null. |
| `second_voice` (yes/no) | Two different speakers were heard in one command. | **Pending:** always null. |

Why hesitation comes from sound levels and not from audio: on Android the `speech_to_text`
recognizer holds the microphone, so a second recorder cannot run alongside it. The levels are
numbers, one every few tens of milliseconds. They are kept in memory for one command and thrown
away; no audio is ever recorded.

The pending signals sit behind the `SpeakerCheck` interface in `app/lib/services/voice_guard.dart`.
Today `NotMeasured` answers null, so the app sends them as "not measured". A real on-device
model can be dropped in without changing the payment flow or the server.

## What is sent

`POST /api/assess` takes an optional `voice_signals` object:

```json
{"hesitation": 0.31, "speaker_echo": false, "voice_mismatch": null, "second_voice": null}
```

The app sends only scores and yes/no values. It never sends audio, voice prints (embeddings) or
the sound-level series. A missing object or a null value means "not measured" and counts as 0 or
no. The web app sends nothing, because nothing is measured there. The server stores the
measured values with the assessment and writes them, with no other personal data, to the
`event: assess` log line.

## How the server uses them

- **Model inputs:** `VOICE_FEATURES` in `api/app/core/features.py`. The risk model is trained with
  monotonic constraints (`ml/train_risk.py`), so these signals can only push the score up. "Not
  measured" and "no" are both 0, the lowest value, so a missing signal or a matching voice never
  lowers anything (tested in `api/tests/test_voice_guard.py`).
- **Hard rule** (`api/app/core/risk.py`): `voice_mismatch` or `second_voice` moves a GREEN
  payment to at least YELLOW, which means the PIN (a fingerprint alone is refused). On its own it
  never makes a payment RED, because a wrong voice is not proof of a scam.
- **Reasons:** each signal has a Bangla and English reason that the user sees with the warning.
- **Training data:** `ml/simulate.py` simulates the signals with stated assumptions, not
  measurements. Most payments are "not measured": the command is typed, the user is on the web,
  or no voice print is enrolled. Coerced scams sometimes show long pauses, a call on the
  loudspeaker or a second voice. Honest payments rarely do, and a rare false "not the owner"
  stands for the speaker model's false rejects. The signals use their own random stream, so the
  rest of the simulated data is unchanged, and the before/after numbers compare the same payments:

| Same 1,426 simulated test payments | Before (18 inputs) | With voice cues (22 inputs) |
|---|---|---|
| PR-AUC / Brier, served model | 0.979 / 0.030 | 0.984 / 0.026 |
| Scams flagged (YELLOW or RED) | 95.3% | 94.0% |
| Scams held (RED) | 84.0% | 87.7% |
| Honest payments held (RED) | 1.5% | 1.5% |
| Honest payments warned | 12.8% | 11.2% |

  The thresholds are re-tuned on the earlier time slice, and this time they trade a little YELLOW
  coverage for more RED holds and fewer warnings to honest users. Because the signals are
  simulated, these numbers only show that the pipeline uses the signals as designed.

## What is left, and why

The speaker model could not be built in the time. It needs a model download, a conversion and
on-device checks, none of which can be done without a phone.

1. **Speaker model.** A small speaker-embedding model, ECAPA-TDNN (a few MB), converted from
   PyTorch to TFLite and run with `tflite_flutter`. It gives `voice_mismatch` (cosine distance to the
   voice print) and `second_voice` (two clusters of window embeddings in one command).
2. **Audio capture.** `speech_to_text` gives no raw audio. Capture 16 kHz PCM with `record`
   and feed the same buffer to on-device speech recognition (shared with R13) and to the speaker
   model, so only one recorder runs. The audio stays in memory and is dropped after each command.
3. **Opt-in enrollment** from 3 spoken phrases. The voice print is encrypted in secure storage
   (Android Keystore) and never uploaded. The user can delete it or enroll again at any time.
4. **Anti-spoofing.** The user reads aloud a random 4-digit challenge, which defeats a replayed
   recording, plus a replay-detection score. This runs only for enrolled users.
5. **Measurement.** Equal error rate and false-reject rate on the R1 recordings, used with
   consent. The threshold should favour few false rejects: a false reject only costs a PIN entry,
   but each one annoys a real user.
6. **Real-phone checks.** These rows go in the device test table:
   - Calibrate hesitation on real honest commands. The 0.3 s pause, the 35% level cut and the
     3 dB minimum range are first guesses.
   - Check that `speaker_echo` reads the loudspeaker state correctly in the stock dialer and in
     WhatsApp on Android 10, 13 and 14 (`isSpeakerphoneOn` and `communicationDevice`).
   - Check whether the recognizer gets the microphone at all while a call is active. Android
     may silence other apps during a call; the user can still type.
   - Inspect the network traffic to show that no audio, voice print or level series leaves the phone.

## Privacy reasoning

- **Minimum data.** Only four numbers or yes/no values leave the phone, and only for a
  payment. That is enough to raise a warning, but not enough to identify or re-create a voice.
- **Never a replacement for the PIN.** Voices can be cloned. A match is therefore ignored, and a
  mismatch only asks for the PIN that would protect the payment anyway. The voice guard can add
  friction, but it can never remove it.
- **Fair to people the model gets wrong.** Speaker models do worse with accents, age, illness
  and noise. A false "not the owner" costs a PIN entry. It never blocks the payment or makes it RED.
- **Consent.** Call detection is explained in Bangla and English before Android asks for the
  permission. Voice enrollment will be opt-in.
- **LLMs.** The voice signals never go to an LLM. The prototype's optional LLM (Gemini or
  another provider) only parses the command text. In production that step should use a local model
  plus redaction of names and numbers, so no command text leaves upay's own systems.
