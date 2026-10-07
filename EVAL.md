# Evaluation

Labels come from **two LLMs (no human validation)**: A = Google
`gemini-3.5-flash-lite`, B = Cloudflare `@cf/openai/gpt-oss-120b`, blind to all
scores and signals (protocol: LABELING.md, plan: ANALYSIS_PLAN.md). Ground
truth = items where both agree on ok or low.

## Summary

| | Round 1 (300-char excerpt) | Round 2 (2,000 chars of main text) | Round 3 (fresh) | Round 4 (fresh queries) |
|---|---|---|---|---|
| Labeler agreement (Cohen's kappa) | 0.47 | 0.66 | 0.42 | 0.53 |
| Agreed items | 141 | 155 (13 items not labeled by B: daily quota) | 114 of 150 | 102 of 128 |

| Rubric | Development | **Test precision** | **Test recall** | **Test F1** | n |
|---|---|---|---|---|---|
| v2 (= v2c), round-2 test | dev F1 0.56 | 0.37 [0.19, 0.59] | 0.35 [0.18, 0.57] | 0.36 | 71 |
| v3, round-3 fresh held-out test | CV precision 0.72, recall 0.33 | 0.57 [0.25, 0.84] | 0.19 [0.08, 0.40] | 0.29 | 114 |
| **v4, round-4 fresh held-out test** | CV precision 0.80, recall 0.29 | **0.88 [0.53, 0.98]** | **0.30 [0.16, 0.51]** | **0.45** | 102 |

**Gate (test precision >= 0.70): met by rubric v4 on round 4** (point estimate
0.88; the 95% interval is wide, lower bound 0.53, because only 8 pages were
flagged). Not met by v2 (round 2) or v3 (round 3). Each test set was evaluated
once and is reported as is.

**Usefulness criterion (pre-registered: test F1 above every baseline): not met
on round 4.** The one-line baseline "no author and no date" scored F1 0.47 vs
the rubric's 0.45, by flagging far more pages (28 vs 8) at much lower precision
(0.43 vs 0.88). Rubric v3 met this criterion on round 3 (F1 0.29 vs 0.12); v2 did
not on round 2. Rubric v4 is conservative: specificity 0.99 (1 of 79 ok pages
flagged), recall 0.30 (7 of 23 low pages caught).

Round 4 used 30 new Google India queries, collected separately
(data_round4/), so its pages and queries share nothing with development data.
Rounds 2 and 3 are spent and are development data for v4. Signals changed for
round 4 (pages under 300 characters of main text are not scored; new
`official_source` signal), so the round-2 and round-3 rows above are the
results as measured at the time, not recomputed.

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

## Round 4 fresh held-out test (rubric v4, one-time evaluation)

<!-- rubric v4 (frozen) sha256:87d60918426f; 102 labels -->
## Split: all (n = 102, unsure excluded)

| Metric (class = low) | Value | 95% CI (Wilson) |
|---|---|---|
| Precision | 0.88 | [0.53, 0.98] |
| Recall | 0.30 | [0.16, 0.51] |
| F1 | 0.45 | |
| Specificity | 0.99 | |
| Share labeled low | 0.23 | |

Confusion matrix (rows = hand label, columns = scored band):

| label \ band | ok | mixed | low |
|---|---|---|---|
| ok | 65 | 13 | 1 |
| low | 8 | 8 | 7 |
| unsure | 0 | 0 | 0 |

Baselines on the same items:

| Method | Flagged | Precision | Recall | F1 |
|---|---|---|---|---|
| **SlopWatch rubric** | 8 | **0.88** | **0.30** | **0.45** |
| any affiliate link | 6 | 0.50 | 0.13 | 0.21 |
| no author and no date | 28 | 0.43 | 0.52 | 0.47 |
| 'best X' listicle | 7 | 0.71 | 0.22 | 0.33 |
| random (same flag rate) | 8 | 0.23 | 0.08 | 0.12 |

### Largest errors (up to 10)

- false negative: labeled **low**, scored **ok** ('best X' listicle pattern) https://kitchendeals.in/best-mixer-grinder-for-south-indian-cooking
- false negative: labeled **low**, scored **ok** ('best X' listicle pattern) https://www.herzindagi.com/your-picks/home-solutions-electronics/top-washing-machine-under-30000-powerful-efficient-and-budget-friendly-9305
- false negative: labeled **low**, scored **ok** (no signals fired) https://www.mymoneymantra.com/fixed-deposits
- false negative: labeled **low**, scored **ok** (the site sells products on this page (cart, buy button or product markup); thin main text (330 chars); contains affiliate links (2)) https://desiutility.com/appliances/kitchen/mixer-grinder-guide
- false negative: labeled **low**, scored **ok** (the site sells products on this page (cart, buy button or product markup); 'best X' listicle pattern; no about or contact page linked) https://www.cashify.in/webstories/best-budget-smartwatch-in-india
- false negative: labeled **low**, scored **ok** (main text covers 0% of the query's words; thin main text (594 chars)) https://www.financialexpress.com/life/technology-aadhaar-card-update-2025-how-to-change-address-in-aadhaar-card-online-check-step-by-step-guide-here-3896139/
- false negative: labeled **low**, scored **ok** (title and headings cover 33% of the query's words; no about or contact page linked) https://www.scribd.com/document/942106504/How-To-Improve-Your-Haemoglobin-Levels-Naturally-12-New
- false negative: labeled **low**, scored **ok** (the site sells products on this page (cart, buy button or product markup)) https://ambraneindia.com/collections/power-banks-under-2000?srsltid=AU7gw4Wp3ZkF0nv3MQQB21-aFo5uaX-6wSBANKRnRFvB4TX7tIGieSiL
- false negative: labeled **low**, scored **mixed** (no named author; no author or date) https://religaredigital.in/apply-new-pan-card/
- false negative: labeled **low**, scored **mixed** (no named author; no author or date) https://www.shriramfinance.in/fd-schemes/50000-fd-senior-citizens-interest-rate-for-5-year

## Audit judge C on round 4 (secondary, declared before C labeled anything)

The ground truth above is "A and B agree", where A is a small model
(gemini-3.5-flash-lite). A stronger model, judge C (`gemini-3.7-flash`, on
Vertex AI; same guide, same prompt, same 2,000 characters, temperature 0),
labeled the same 128 round-4 pages blind. C never defines ground truth and was
not used to fit or change anything (ANALYSIS_PLAN.md, 2026-10-07).

| Check | Result |
|---|---|
| Cohen's kappa C vs A / C vs B | 0.72 / 0.52 |
| A+B agreed labels that C confirms | **94 of 102 (92%)** |
| A+B "ok" that C calls low / unsure | 5 / 1 of 79 |
| A+B "low" that C calls ok / unsure | 1 / 1 of 23 |
| Rubric v4 precision with C as reference | **0.89 [0.56, 0.98]** (primary: 0.88) |
| Rubric v4 recall with C as reference | 0.21 [0.11, 0.36] (primary: 0.30) |

Reading: the stronger judge largely confirms the ground truth, and the rubric's
precision holds against it. Recall is lower against C, which calls more pages
low (39 of 128 vs A+B's 23 agreed). Against C's labels two one-line baselines
reach a slightly higher F1 than the rubric (0.33): "'best X' listicle" (F1 0.37,
precision 0.90 on 10 flagged) and "no author and no date" (F1 0.34). Rubric v4
gives listicles a negative weight, fitted on development data; this audit
suggests that weight is wrong on fresh data. Not acted on: round 4 is spent and
nothing is refitted on it.

<!-- rubric v4 (frozen) sha256:87d60918426f; 128 labels; reference = audit judge C, secondary -->
### Rubric v4 against judge C's labels: split all (n = 122, unsure excluded)

| Metric (class = low) | Value | 95% CI (Wilson) |
|---|---|---|
| Precision | 0.89 | [0.56, 0.98] |
| Recall | 0.21 | [0.11, 0.36] |
| F1 | 0.33 | |
| Specificity | 0.99 | |
| Share labeled low | 0.32 | |

Confusion matrix (rows = hand label, columns = scored band):

| label \ band | ok | mixed | low |
|---|---|---|---|
| ok | 67 | 15 | 1 |
| low | 23 | 8 | 8 |
| unsure | 5 | 1 | 0 |

Baselines on the same items:

| Method | Flagged | Precision | Recall | F1 |
|---|---|---|---|---|
| **SlopWatch rubric** | 9 | **0.89** | **0.21** | **0.33** |
| any affiliate link | 7 | 0.57 | 0.10 | 0.17 |
| no author and no date | 32 | 0.38 | 0.31 | 0.34 |
| 'best X' listicle | 10 | 0.90 | 0.23 | 0.37 |
| random (same flag rate) | 9 | 0.32 | 0.07 | 0.12 |
