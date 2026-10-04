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

| Rubric (chosen on dev, round-2 labels) | Dev F1 (n=84) | **Test precision** | **Test recall** | **Test F1** (n=71) |
|---|---|---|---|---|
| v1 (frozen before labeling) | 0.00 | | | |
| **v2 = v2c (frozen before test)** | 0.56 | **0.37 [0.19, 0.59]** | **0.35 [0.18, 0.57]** | **0.36** |
| Baseline: no author and no date | 0.51 | 0.47 | 0.35 | 0.40 |

**Gate (test precision >= 0.70): not met.** The test split was evaluated once;
the number is reported as is. On test, the rubric does not beat the best
one-signal baseline.

## Test split (one-time evaluation)

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

