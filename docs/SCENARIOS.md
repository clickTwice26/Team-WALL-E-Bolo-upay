# Three scenarios: problem → prevention → value

The three cases the judges asked to see (Problem relevance, Judge 2). Each one runs **in one tap** from the **Demo scenarios** card on the Home screen of the demo site (it resets the demo data first, so the numbers below are what you see). The demo video follows these three, in this order.

All figures marked *simulation* come from the synthetic test set and `data/impact_assumptions.json` (see the Impact card on the Dashboard). They show the pipeline behaves as designed, not real-world results.

## 1. Fake upay employee (the call scam)

| | |
|---|---|
| **What the user says** | "upay office theke phone kore bollo 01799998888 e 5000 taka pathate" while on a phone call (the scenario turns the call signal on) |
| **What the system finds** | Scam words: a caller posing as upay staff (hard rule) · a number never paid before · an amount unusual for this user · an active phone call |
| **Level and approval** | **RED** → 30-second hold, a warning to tick by hand, then PIN. The ladder on the screen shows the hold step, and "Why?" lists the reasons |
| **Advice on screen** | "upay never calls to ask for your PIN, OTP or money. If in doubt, hang up and call 16268." |
| **Taka at risk** | **৳5,000**, gone for good once sent: 91.3% of MFS fraud money in Bangladesh was never recovered in 2025 (Tk 81.32 crore of fraud, Bangladesh Bank via New Age) |
| **Outcome** | The user cancels → ৳5,000 stays in the account and the decision appears on the Dashboard as "cancelled after warning" |
| **How often it is caught** *(simulation)* | 95.5% of simulated fake-official scams are flagged. Across all scam kinds at a realistic 1% prevalence: per 1,000,000 transfers, 9,529 of 10,000 scams flagged, 8,403 held at RED, about **Tk 3.2 crore protected** (mid assumptions) |

If the user later says "this is a scam" to the Bolo agent, the chat goes to a person in the support console's **urgent** queue.

## 2. Wrong recipient ("Which Rahim?")

| | |
|---|---|
| **What the user says** | "rahim ke 500 taka pathao" |
| **What the system finds** | Two contacts match "Rahim": Rahim bhai (brother) and Rahim Store (shop) |
| **Level and approval** | No guess: the app asks "Which Rahim?" and lists both. Only after the user picks one does the risk check and the PIN step run |
| **Taka at risk** | **৳500** to the wrong person, which becomes a dispute ticket and a call to the call centre |
| **Outcome** | The user taps the right Rahim; the money goes where they meant |
| **Value** *(simulation)* | MFS providers handled about 700,000 disputes worth Tk 153.98 crore. With our assumptions (35% caused by a wrong number or amount, half of those caught by the mistake checks, upay's 10% share, Tk 300 per ticket): about **12,250 disputes avoided and Tk 36.75 lakh saved per year** for upay (range 2,100–36,750 and Tk 3.15 lakh–1.84 crore) |

## 3. Unusually large transfer (an extra zero)

| | |
|---|---|
| **What the user says** | "rahim store ke 3500 taka" |
| **What the system finds** | The user usually sends Rahim Store about ৳360, so ৳3,500 is ~10× the usual amount |
| **Level and approval** | **YELLOW** → two short safety questions, then "You usually send this person about ৳360. Did you mean ৳350?" with one-tap buttons for ৳350 or keeping ৳3,500, then PIN |
| **Taka at risk** | **৳3,150** overpaid (৳3,500 instead of ৳350) |
| **Outcome** | The user taps ৳350 |
| **Value** | Counted in the same dispute estimate as scenario 2: these are the "wrong amount" disputes |

## What it costs honest users

Warnings are not free, and we report the cost next to the benefit: at 1% scam prevalence, 12.8% of honest payments see a YELLOW or RED step and 1.5% are held at RED *(simulation)*. The Impact card shows the extra minutes and the share of honest payments that might be given up, and every warning has a "This warning seems wrong?" button that feeds the monthly threshold review (`docs/FAILURE_POLICY.md`).
