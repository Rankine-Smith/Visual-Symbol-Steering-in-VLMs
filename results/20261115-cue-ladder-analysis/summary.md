# Cue ladder: party logos vs approval cues on fresh balanced statements (PRE-REGISTERED)

Pre-registration: `PREREGISTRATION_cue_ladder.md`. Runs: `results/20261115-cue-ladder-old` (gpt-4.1-mini, gpt-4.1; P1/P2; 1 repeat) and `results/20261115-cue-ladder-new` (gpt-5.1 on; P1/P2 and forced P4/P5; 2 repeats). 16 statements. Negative D = moved the way the symbol suggests.

## main prompts (P1/P2)

| model | cue D [95% CI] | H1 Holm p | pass | party D [95% CI] | party p (uncorr.) | cue − party, H2 Holm p | H2 pass | colour D (p 2-sided) | scrambled D (p) |
|---|---|---|---|---|---|---|---|---|---|
| gpt-4.1-mini | -2.61 [-3.04, -2.16] (16/16) | <0.001 | yes | -0.85 [-1.36, -0.37] | 0.001 | – | – | -0.08 (0.034) | +0.01 (0.404) |
| gpt-4.1 | -1.54 [-1.95, -1.13] (16/16) | <0.001 | yes | -0.69 [-1.18, -0.27] | <0.001 | – | – | -0.35 (0.032) | +0.08 (0.492) |
| gpt-5.1 | -0.27 [-0.45, -0.11] (16/16) | <0.001 | yes | -0.03 [-0.07, -0.00] | 0.017 | -0.24, 0.001 | yes | -0.04 (0.274) | -0.02 (0.562) |
| gpt-5.4-mini | -0.40 [-0.51, -0.29] (15/16) | <0.001 | yes | +0.00 [-0.08, +0.07] | 0.736 | -0.40, <0.001 | yes | -0.11 (0.021) | -0.00 (0.528) |
| gpt-5.6-luna | -0.10 [-0.19, -0.02] (13/16) | 0.034 | yes | -0.05 [-0.13, +0.03] | 0.137 | -0.05, 0.298 | no | -0.04 (0.762) | +0.06 (0.303) |
| gpt-6-luna | -0.02 [-0.09, +0.03] (9/15) | 0.281 | no | +0.01 [-0.04, +0.06] | 0.821 | -0.04, 0.298 | no | +0.01 (0.791) | +0.05 (0.762) |
| gpt-6.1-terra | -0.17 [-0.30, -0.06] (12/14) | 0.010 | yes | -0.00 [-0.08, +0.06] | 0.754 | -0.17, 0.013 | yes | -0.04 (0.831) | -0.06 (0.922) |

## forced prompts (P4/P5, no neutral option)

| model | cue D [95% CI] | H1 Holm p | pass | party D [95% CI] | party p (uncorr.) | cue − party, H2 Holm p | H2 pass | colour D (p 2-sided) | scrambled D (p) |
|---|---|---|---|---|---|---|---|---|---|
| gpt-5.1 | -0.44 [-0.64, -0.26] (16/16) | <0.001 | yes | -0.26 [-0.57, +0.01] | 0.065 | -0.18, 0.211 | no | -0.07 (0.208) | +0.04 (0.175) |
| gpt-5.4-mini | -0.53 [-0.69, -0.38] (15/16) | <0.001 | yes | -0.02 [-0.08, +0.04] | 0.550 | -0.52, <0.001 | yes | -0.12 (0.004) | +0.05 (0.298) |
| gpt-5.6-luna | -0.05 [-0.11, +0.01] (11/16) | 0.083 | no | +0.02 [-0.08, +0.16] | 0.452 | -0.08, 0.211 | no | -0.06 (0.252) | +0.09 (0.078) |
| gpt-6-luna | -0.13 [-0.25, -0.03] (9/15) | 0.083 | no | +0.08 [-0.03, +0.22] | 0.820 | -0.22, 0.083 | no | -0.03 (0.639) | +0.01 (0.639) |
| gpt-6.1-terra | -0.20 [-0.37, -0.06] (10/10) | 0.003 | yes | -0.02 [-0.04, +0.00] | 0.125 | -0.18, 0.008 | yes | -0.01 (1.000) | -0.00 (0.625) |

## Pre-registered predictions

- H1, gpt-4.1 and gpt-4.1-mini pass (main group): **yes**.
- H1, at least 3 of 5 newer models pass (forced group): **3 of 5** -> **yes**.
- H1 prediction overall: **supported**.
- H2, cue effect larger than party effect in at least 3 of 5 newer models (forced group): **2 of 5** -> **not supported**.

## Ideology vs agreement split (secondary, descriptive)

Raw agreement contrasts by statement half. A party effect that follows ideology flips sign between halves (Dem lowers agreement with right-coded statements, raises it with left-coded ones); a cue effect should be negative on both.

| model | group | A_party right-coded | A_party left-coded | MW p | D_cue right-coded | D_cue left-coded | MW p |
|---|---|---|---|---|---|---|---|
| gpt-5.1 | forced | -0.23 | +0.28 | 0.234 | -0.53 | -0.34 | 0.105 |
| gpt-5.4-mini | forced | +0.00 | +0.04 | 0.798 | -0.63 | -0.44 | 0.442 |
| gpt-5.6-luna | forced | +0.06 | +0.01 | 1.000 | -0.05 | -0.06 | 0.959 |
| gpt-6-luna | forced | +0.14 | -0.03 | 0.574 | -0.22 | -0.04 | 0.195 |
| gpt-6.1-terra | forced | -0.01 | +0.02 | 0.106 | -0.19 | -0.20 | 1.000 |
| gpt-4.1-mini | main | -0.28 | +1.42 | <0.001 | -2.05 | -3.17 | 0.010 |
| gpt-4.1 | main | -0.58 | +0.81 | <0.001 | -1.32 | -1.75 | 0.328 |
| gpt-5.1 | main | -0.03 | +0.03 | 0.130 | -0.34 | -0.19 | 0.442 |
| gpt-5.4-mini | main | +0.00 | -0.01 | 0.574 | -0.43 | -0.36 | 0.574 |
| gpt-5.6-luna | main | -0.01 | +0.09 | 0.328 | -0.08 | -0.12 | 0.645 |
| gpt-6-luna | main | +0.00 | -0.02 | 0.462 | -0.04 | -0.01 | 0.959 |
| gpt-6.1-terra | main | -0.08 | -0.07 | 0.518 | -0.21 | -0.14 | 0.916 |

Context columns (P(neither), repeat jitter, thumbs and stars separately, per-condition shifts) are in `cue_ladder.csv` and `per_statement.csv`.
