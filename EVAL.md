# Evaluation

Labels come from **two LLMs (no human validation)**: A = Google
`gemini-3.5-flash-lite`, B = Cloudflare `@cf/openai/gpt-oss-120b`, blind to all
scores and signals (protocol: LABELING.md, plan: ANALYSIS_PLAN.md). Ground
truth = items where both agree on ok or low.

## Summary

| | Round 1 (300-char excerpt) | Round 2 (2,000 chars of main text) |
|---|---|---|
| Labeler agreement (Cohen's kappa) | 0.47 | 0.66 |
| Agreed items | 141 | 155 (13 items not labeled by B: daily quota) |

| Rubric | Development | **Test precision** | **Test recall** | **Test F1** | n |
|---|---|---|---|---|---|
| v2 (= v2c), round-2 test | dev F1 0.56 | 0.37 [0.19, 0.59] | 0.35 [0.18, 0.57] | 0.36 | 71 |
| **v3, round-3 fresh held-out test** | CV precision 0.72, recall 0.33 | **0.57 [0.25, 0.84]** | **0.19 [0.08, 0.40]** | **0.29** | 114 |

**Gate (test precision >= 0.70): not met in either round.** Each test split was
evaluated once and is reported as is.

**Usefulness criterion (pre-registered: test F1 above every baseline):** met by
rubric v3 on round 3 (F1 0.29 vs best baseline 0.12), not by v2 on round 2 (0.36
vs 0.40). Rubric v3 is conservative: specificity 0.97 (3 of 93 ok pages flagged),
recall 0.19 (4 of 21 low pages caught).

Round-3 labeler agreement was lower than round 2 (Cohen's kappa 0.42 vs 0.66;
114 of 150 items agreed).

## Round 2 test split (rubric v2, one-time evaluation)

<!-- rubric v2 (frozen) sha256:25ecb5a18100; 155 labels -->
## Split: test (n = 71, unsure excluded)

| Metric (class = low) | Value | 95% CI (Wilson) |
|---|---|---|
| Precision | 0.37 | [0.19, 0.59] |
| Recall | 0.35 | [0.18, 0.57] |
| F1 | 0.36 | |
| Specificity | 0.76 | |
| Share labeled low | 0.28 | |

Confusion matrix (rows = hand label, columns = scored band):

| label \ band | ok | mixed | low |
|---|---|---|---|
| ok | 35 | 4 | 12 |
| low | 9 | 4 | 7 |
| unsure | 0 | 0 | 0 |

Baselines on the same items:

| Method | Flagged | Precision | Recall | F1 |
|---|---|---|---|---|
| **SlopWatch rubric** | 19 | **0.37** | **0.35** | **0.36** |
| any affiliate link | 2 | 0.00 | 0.00 | 0.00 |
| no author and no date | 15 | 0.47 | 0.35 | 0.40 |
| 'best X' listicle | 5 | 0.00 | 0.00 | 0.00 |
| random (same flag rate) | 19 | 0.28 | 0.27 | 0.27 |

### Largest errors (up to 10)

- false negative: labeled **low**, scored **ok** (no signals fired) https://directdawai.com/blog/gas-acidity-indigestion-remedies
- false negative: labeled **low**, scored **ok** (no signals fired) https://indiaclear.com/aadhar-card-free-download-e-aadhaar-2019-uidai-gov-in/
- false negative: labeled **low**, scored **ok** (no signals fired) https://lifeinsurance.adityabirlacapital.com/articles/savings-insurance/how-to-begin-your-financial-investments/
- false negative: labeled **low**, scored **ok** (no signals fired) https://qa.cus.zetapp.in/blog/best-online-shopping-credit-cards-in-india-2024
- false negative: labeled **low**, scored **ok** (no signals fired) https://redcliffelabs.com/myhealth/dengue/ways-to-increase-platelet-count-in-dengue-naturally/
- false negative: labeled **low**, scored **ok** (no signals fired) https://runkituk.co.uk/best-carbon-plate-running-shoes-2026-uk/
- false negative: labeled **low**, scored **ok** (no signals fired) https://www.sidebysideyouth.org/
- false negative: labeled **low**, scored **ok** (no signals fired) https://www.webmd.com/obesity/healthy-weight
- false negative: labeled **low**, scored **ok** (no about or contact page linked) https://www.fda.gov/regulatory-information/search-fda-guidance-documents/obesity-and-overweight-developing-drugs-and-biological-products-weight-reduction
- false negative: labeled **low**, scored **mixed** (no about or contact page linked; thin main text (0 chars)) https://www.roblox.com/


## Round 3 fresh held-out test (rubric v3, one-time evaluation)

<!-- rubric v3 (frozen) sha256:7e8922723598; 114 labels -->
## Split: all (n = 114, unsure excluded)

| Metric (class = low) | Value | 95% CI (Wilson) |
|---|---|---|
| Precision | 0.57 | [0.25, 0.84] |
| Recall | 0.19 | [0.08, 0.40] |
| F1 | 0.29 | |
| Specificity | 0.97 | |
| Share labeled low | 0.18 | |

Confusion matrix (rows = hand label, columns = scored band):

| label \ band | ok | mixed | low |
|---|---|---|---|
| ok | 77 | 13 | 3 |
| low | 11 | 6 | 4 |
| unsure | 0 | 0 | 0 |

Baselines on the same items:

| Method | Flagged | Precision | Recall | F1 |
|---|---|---|---|---|
| **SlopWatch rubric** | 7 | **0.57** | **0.19** | **0.29** |
| any affiliate link | 9 | 0.11 | 0.05 | 0.07 |
| no author and no date | 13 | 0.15 | 0.10 | 0.12 |
| 'best X' listicle | 10 | 0.10 | 0.05 | 0.06 |
| random (same flag rate) | 7 | 0.18 | 0.06 | 0.09 |

### Largest errors (up to 10)

- false negative: labeled **low**, scored **ok** (no signals fired) https://flypped.com/health-fitness/dolo-650-tablet-uses
- false negative: labeled **low**, scored **ok** (no signals fired) https://hitechdiagnosticcentre.com/vitamin-d-deficiency-test/
- false negative: labeled **low**, scored **ok** (no signals fired) https://jamesandco.in/best-laptop-under-50000-for-students/?srsltid=AU7gw4VRE1emNAdcVpfrqCbDwbZRbj-RBSQoO3vYuhuLrAhgF3BeZ0Kp
- false negative: labeled **low**, scored **ok** (no signals fired) https://shuddhihiims.com/ayurvedic-treatment-for-high-blood-pressure/
- false negative: labeled **low**, scored **ok** (main text covers 50% of the query's words) https://www.bajajfinservmarkets.in/stocks/how-to-start-investing-in-stocks-with-little-money
- false negative: labeled **low**, scored **ok** (main text covers 50% of the query's words) https://www.fda.gov/vaccines-blood-biologics/vaccines/emergency-use-authorization-vaccines-explained
- false negative: labeled **low**, scored **ok** (the site sells products on this page (cart, buy button or product markup)) https://budgettech.in/best-laptops-under-50000/
- false positive: labeled **ok**, scored **low** (no named author; no author or date; title and headings cover 25% of the query's words; main text covers 50% of the query's words) https://support.google.com/accounts/answer/58585?hl=en
- false negative: labeled **low**, scored **ok** (the site sells products on this page (cart, buy button or product markup)) https://www.cruiseac.com/home-air-conditioners/split-inverter-ac/varioqool-3d/cwcvbk-vq3d185/
- false positive: labeled **ok**, scored **low** (no named author; no author or date; title and headings cover 0% of the query's words; main text covers 0% of the query's words) https://www.kotak811.bank.in/insights/savings/how-much-to-save-for-emergency-fund

