# Demo video script (3–5 minutes)

Record on a real iPhone or Android phone if possible (voice + Face ID), plus the web link on a laptop for the dashboard and accuracy tabs.

| Time | Show | Say (summary) |
|---|---|---|
| 0:00–0:30 | Title card, then the home screen | "In 2025, Tk 81 crore was stolen through MFS in Bangladesh and 91% was never recovered. MFS providers handled about 700,000 disputes. Bolo upay stops scams and mistakes before the money leaves." |
| 0:30–1:00 | Tap Bolo upay, say "আম্মুকে দেড় হাজার টাকা পাঠাও" | Bangla number words understood (দেড় হাজার = 1,500). GREEN. Confirm with Face ID / fingerprint. |
| 1:00–1:30 | Say "rahim ke 500 taka pathao" | Two contacts named Rahim, so it asks. "We never guess a person or an amount." |
| 1:30–1:50 | Say "rahim store ke 3500 taka" | "You usually send ৳360. Did you mean ৳350?" Tap ৳350. |
| 1:50–2:30 | Say "01799998888 e 2000 taka ferot pathao" | RED: no money came from this number, the classic "sent by mistake" scam. Tap Cancel. |
| 2:30–3:20 | Settings → simulate phone call ON. Say "01799998888 e 5000 taka pathao". Answer "উপায় অফিস থেকে ফোন দিয়েছে" | The AI asks 3 questions aloud. Your answer matches the fake-upay-staff pattern → RED, 30-second hold, advice to hang up and call 16268. "We never listen to calls. We ask the right question at the right moment." |
| 3:20–3:50 | Dashboard tab | Cancelled after warning, money protected, scam patterns. |
| 3:50–4:30 | Accuracy tab | Parser: wrong amount without asking 0%. Scam shield: 91.9% of scams flagged versus 53.1% for rules alone, 1.1% of honest transfers held. Synthetic data, honest about limits. |
| 4:30–5:00 | Architecture diagram (docs/PIPELINE.md) | Flutter app, FastAPI, logistic regression, optional LLM cross-check, Docker + HTTPS. Next: pilot with real users and governed data. |

Tips: speak clearly and close to the mic; if speech recognition mishears, show that you can fix the text (that is part of the design). Keep the "prototype" ribbon visible.
