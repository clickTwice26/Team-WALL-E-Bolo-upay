# Demo video script (3–5 minutes)

Record on an Android phone if possible (voice + fingerprint), plus the web link on a laptop for the dashboard and accuracy tabs. The middle of the video is the three scenarios in [`SCENARIOS.md`](SCENARIOS.md), each started from the **Demo scenarios** card on Home (one tap: it resets the demo data, so the live demo never depends on typing).

| Time | Show | Say (summary) |
|---|---|---|
| 0:00–0:30 | Title card, then the home screen | "In 2025, Tk 81 crore was stolen through MFS in Bangladesh and 91% was never recovered. MFS providers handled about 700,000 disputes. Bolo upay stops scams and mistakes before the money leaves." |
| 0:30–1:00 | Tap Bolo upay, say "আম্মুকে দেড় হাজার টাকা পাঠাও" | Bangla number words understood (দেড় হাজার = 1,500). GREEN: the ladder shows "fingerprint or PIN". Confirm with the fingerprint. |
| 1:00–1:50 | **Scenario 1: Fake upay employee** | On a call, "upay office" asks for ৳5,000 to a new number. RED: the ladder jumps to the 30-second hold. Tap "Why?": caller posing as upay staff, new number, phone call. "upay never calls for your PIN, OTP or money." Tap Cancel: ৳5,000 kept. Say "this is a scam" to the agent: it goes to a person, urgent. |
| 1:50–2:20 | **Scenario 2: Wrong recipient** | "rahim ke 500 taka pathao": two Rahims, so it asks. "We never guess a person or an amount." |
| 2:20–2:50 | **Scenario 3: Unusually large amount** | "rahim store ke 3500 taka": two safety questions, then "You usually send ৳360. Did you mean ৳350?" Tap ৳350. |
| 2:50–3:20 | Dashboard tab | Cancelled after warning, money protected, the Impact card (simulation, labelled), model health. |
| 3:20–3:50 | Accuracy tab | Parser: wrong amount without asking 0%. Scam shield: 95.3% of simulated scams flagged versus 63.1% for rules alone, 1.5% of honest transfers held. Synthetic data, honest about limits. |
| 3:50–4:30 | Architecture (docs/PIPELINE.md) and the ladder figure in the report | Flutter app, FastAPI, calibrated gradient boosting with SHAP reasons, optional LLM cross-check (a local model in production), Docker + HTTPS. Next: pilot with real users and governed data (docs/PILOT.md). |

Tips: speak clearly and close to the mic; if speech recognition mishears, show that you can fix the text (that is part of the design). Keep the "prototype" ribbon visible.
