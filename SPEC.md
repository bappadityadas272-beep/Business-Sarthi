# SPEC: what we are building and why

> Status: design complete, implementation not started. See `CHECKPOINTS.md` for live progress.

## 1. Problem

A first-time or small shop owner takes a loan, opens a shop, and has no reliable way to answer:

- Where should I set up? How much should I invest? How much will I sell?
- What should I stock, and when should I reorder?
- Am I growing, stuck, or in trouble, and what should I do next?
- Which government scheme or loan fits me?
- How do I get advice in my own language without paying a consultant?

Existing tools mostly cover one slice. Ledger and billing apps (for example Khatabook, OkCredit, Vyapar) record what has already happened. Scheme and loan portals (for example myScheme, Udyami Mitra) list funding options. Per their public pages, none gives a first-time owner a forecast at set-up or a regular, data-driven review afterwards. (Competitor statements are based on public product pages at the time of writing and must be re-checked before being repeated.)

Four failure patterns drive the story (owner "Ramesh", a first-time kirana owner):

| Case | What happens |
|---|---|
| Losses pile up | Sales fall short of costs and nobody warned him |
| Same margin, no growth | The shop runs but never moves forward |
| EMI missed, debt grows | The repayment date arrives before the cash does |
| Wrong stock, lost sales | One shelf overflows while another sits empty |

## 2. Users

| User | Needs | Constraints |
|---|---|---|
| **Primary: first-time or small shop owner** (kirana first) | Simple guidance, local language, voice input, low effort per day | May have a low-end phone, patchy data, limited literacy in English, little time |
| Secondary: institution (bank, NGO, MSME body), later | Sponsor the tool for their borrowers, see anonymised aggregate health | Needs consent and privacy |

Design consequence: every screen must work with **large touch targets, minimal typing, voice or one-tap entry, and the owner's language**.

## 3. Core idea (the "hero loop")

```
Forecast (before investing) -> Run (log sales and stock) -> Review (every 3 months) -> Act (grow / hold / pivot) -> back to Forecast with real data
```

A competitor can copy any one feature. The loop is harder to copy because every other feature makes the forecast better, and the forecast makes every other feature matter.

## 4. Features: what, why, priority

Priority: P0 = demo path, P1 = important, P2 = nice to have. Each feature has a short ID used in `CHECKPOINTS.md`.

| ID | Feature | What it does | Why it exists (problem it removes) | Priority |
|---|---|---|---|---|
| F1 | **Forecast at set-up** | From shop type, location, size and budget, returns monthly revenue range (P10/P50/P90), gross profit, break-even revenue and rough payback range | "How much will I sell? How much should I invest?" Owners guess; wrong guesses cause early losses | P0 |
| F2 | **Right place, right products** | Scores a chosen location from map data (nearby competitors, residential density, schools, transit) and suggests a starter product mix | "Where should I set up?" and "what should I stock?" | P1 |
| F3 | **Smart stock and assets** | Tracks stock by category, computes reorder points, flags dead stock, keeps a simple asset list | "Poor inventory management": overflowing and empty shelves | P0 |
| F4 | **Schemes and loans, matched** | Matches the owner to schemes and loans they likely qualify for, with source links and a "verify on the official page" notice | "Which scheme fits me?" Research shows low scheme awareness | P1 |
| F5 | **3-month review** | Re-forecasts from real sales, computes health indicators, returns **grow / hold / pivot** with reasons and next steps | "Stuck at the same margin" and "how do I expand?" | P0 |
| F6 | **Alerts and SOS** | Rule-based early warnings (sales dip, low stock, EMI due, cash shortfall) and a guided SOS help flow | "Losses pile up" and "EMI missed" | P0 |
| F7 | **Advice in your language** | Grounded chatbot (text and voice input) answering from the shop's own data and the scheme knowledge base, in Hindi, English and Hinglish first | Language barrier and costly consultants | P0 |
| F8 | **Investment planner and expansion simulator** | Splits a budget into stock, fixtures, deposit and cash reserve; later simulates expansion options with payback ranges | "How much to invest?" and "how to expand?" | P1 (planner), P2 (simulator) |
| F9 | **Pricing and margin helper** | Shows current margin versus target and flags low-margin categories | "What price should I keep?" | P2 |

Notes:
- The public pitch counts eight blocks; F8 and F9 refine the "Forecast", "Review" and "Stock" blocks. Nothing here changes the pitch.
- Business models (freemium, quarterly plan, loan referrals, supplier tie-ups, institutional licence) are **proposed only** and are out of scope for the prototype. They are listed in the README.

## 5. Owner journey (screens in order)

1. Sign in with a phone number (mock OTP in the prototype) and choose a language.
2. Give consent (what is stored and why).
3. Tell the idea: shop type, location pin, budget, rent, staff. Voice or text.
4. See the **location score** and starter product mix.
5. See the **set-up forecast** (range chart, break-even, payback range) and the **investment split**.
6. Launch: daily entry screen (sales by category; stock in and out; expenses).
7. Dashboard: today's snapshot, alerts, next review date, EMI countdown.
8. Every 3 months: **review screen** with grow / hold / pivot, reasons, and actions.
9. Anytime: schemes and loans list, chatbot, SOS button.

## 6. Scope

**In scope (prototype):** all features F1 to F9 at least at a basic level, running on synthetic and demo data, one language pair (Hindi and English) plus Hinglish understanding, web app (mobile-first), local deployment or a simple host.

**Out of scope (for now):**
- Real payments, real lending, or any financial transaction.
- Production-grade security, real SMS delivery, regulatory approval.
- Integrations with UPI, billing or accounting apps (listed as "later").
- Human responders behind SOS. In the prototype, SOS is a guided help flow plus a shareable summary.
- Claims of measured impact. The 81% survival figure is a **target to test in a pilot**, not a result.

## 7. Success measures

**Prototype (what "done" looks like):**
- The demo path works end to end on the seeded demo shop "Ramesh Kirana" (see `ARCHITECTURE.md`, demo script).
- The forecast beats a seasonal-naive baseline by at least 10% on WAPE on held-out synthetic shops, and its P10 to P90 band covers 75% to 85% of actuals (our own targets; see `ML_PLAN.md`).
- Chatbot answers on a 30-question evaluation set are grounded (cite the knowledge base or a tool result) in at least 90% of cases.

**Pilot (future, not part of this build):**
- Share of pilot shops still open at 12 and 24 months, compared with a matched comparison group.
- The pitch scenario assumes 10% fewer closures for tech tools alone and 40% for Business Sarthi (cautious case 20%), from a 70% five-year survival baseline. These are **assumptions to test**, not findings.

## 8. Evidence base (why we believe this helps)

| Source | Finding used |
|---|---|
| Singh and Wasdani (2016), ADBI WP 581 | Low awareness and collateral are main barriers to MSME finance; 49 of 85 surveyed owners knew no scheme |
| Sajna and Dharmaraj (2024), IJISS | Most of 396 surveyed owners had little or no scheme awareness |
| Salasty et al. (2025), SIJASH | Owners learn about schemes mainly from friends and relatives |
| Murad (2015), IJACSA | Catchment and demand analysis with GIS informs retail location |
| McKenzie and Woodruff (2017) | Better business practices predict higher survival and sales growth in small firms |
| MSME ministry fact sheet (Jan 2026, via PIB) | MSMEs: 31.1% of GDP, 35.4% of manufacturing output, 48.58% of exports, 38.9 crore jobs (jobs figure not cross-checked against a second source) |
| Policy Edge (2026) | About 70% of Indian firms survive beyond five years (firm size not specified) |

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Little real shop data, so forecast credibility is limited | Be explicit that the prototype trains on synthetic data; design the pipeline to refit on pilot data; show ranges, not point promises |
| Owners may not log sales daily | One-tap or voice entry, daily nudge, weekly catch-up entry, and the model degrades gracefully with gaps (see `ML_PLAN.md`) |
| Chatbot may hallucinate | Tool-grounded answers, retrieval with citations, refusal when no source, evaluation set |
| Scheme rules change | `last_verified` dates, source URLs, "verify on the official page" notice, a re-verification checklist |
| Loan referral revenue could bias advice | Keep advice rules independent of any referral partner; disclose partnerships; documented in `DECISIONS.md` |
| Privacy | Consent record, minimal personal data, delete-my-data endpoint, no real data in the prototype |

## 10. Glossary

- **P10 / P50 / P90:** the 10th, 50th and 90th percentile of the forecast. "80% of the time we expect actuals between P10 and P90."
- **Break-even revenue:** monthly revenue at which gross profit equals fixed costs.
- **DSCR:** debt service coverage ratio, monthly operating profit divided by the monthly EMI. Below 1.0 means the shop cannot cover its loan payment.
- **EMI:** equated monthly instalment on a loan.
- **ROP:** reorder point, the stock level at which a reorder should be placed.
- **WAPE:** weighted absolute percentage error, a forecast accuracy measure that handles zero-sales days better than MAPE.
- **Pinball loss:** the loss function used to train and score quantile forecasts.
- **Kirana:** a small neighbourhood grocery shop.
