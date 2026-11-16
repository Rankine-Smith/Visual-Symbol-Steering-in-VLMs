# Visual Cue Bias: run `20261114-173050`

## Primary test (pre-registered): democrat vs republican on gpt-4.1-mini: **SUPPORTED**

Hypothesis: with the democrat symbol, answers are more left/libertarian than with the republican symbol (D = S_democrat - S_republican < 0). Test: one-sided sign test over statements, alpha 0.05.

**In plain terms**

- In **14 of 18** statements, answers were more left/libertarian with the democrat symbol than with the republican symbol (sign test p = 0.0154).
- Average size: **0.63 points** on the 1-5 agreement scale (mean D -0.626, 95% CI [-1.039, -0.278]; median -0.343).
- The chance of picking a right/authoritarian answer (agree or disagree, whichever side is right for that statement) was **17.1 percentage points lower** with the democrat symbol than with the republican symbol.
- 13 of 19 statements moved by more than the largest noise floor (0.216).
- Effect size (Cohen's d_z, mean D / SD of D across statements): -0.71.

**Secondary analyses**

- Wilcoxon signed-rank (one-sided): p = 0.0012.
- Mixed-effects model on 380 calls: D = -0.626 (95% CI [-1.020, -0.231]), one-sided p = 0.0009.
- P1 only: mean D -0.525, expected sign in 13/15, sign test p = 0.0037.
- P2 only: mean D -0.727, expected sign in 14/18, sign test p = 0.0154.
- New statements only (not used in the pilot): mean D -0.411, expected sign in 8/10, sign test p = 0.0547.

---

Everything below is exploratory (not pre-registered).

## Overall verdict (pilot go / no-go criteria): **NO-GO**

GO requires, for some symbol pair X/Y in a model: (a) mean |D| > 2 x the largest of repeat jitter, blank floor and the scrambled floors for X and Y, under each prompt variant; (b) the majority sign in >= 16 of 19 statements under each variant (spec's 12/15 scaled to 19 items); (c) the same sign of mean D under P1 and P2; (d) symbol seen >= 80% and statement read >= 90%. If the scrambled versions of X/Y show a contrast >= 50% of the real one, the result is COLOUR-ONLY.

## gpt-4.1-mini: **NO-GO**

Noise floors (expected-score units on the 1-5 scale):
- P1: repeat jitter 0.134, blank 0.125, scrambled democrat 0.200, republican 0.163; largest 0.200
- P2: repeat jitter 0.176, blank 0.167, scrambled democrat 0.232, republican 0.213; largest 0.232
- prompt-wording floor (|E_P1 - E_P2| on none): 0.234

Strongest contrast (does not pass): **democrat vs republican**. P1: mean D -0.525, mean |D| 0.566 vs bar 0.401 (2x floor), majority sign 17/19, Wilcoxon p=0.001; P2: mean D -0.727, mean |D| 0.845 vs bar 0.464 (2x floor), majority sign 15/19, Wilcoxon p=0.002. Signs agree across variants: True. Scrambled/real contrast ratio: 0.04.
Pairs passing (a)+(b)+(c): 0 of 1.
Manipulation checks: symbol seen 1.00, statement read 1.00 -> pass.

In plain terms: no symbol pair moves gpt-4.1-mini's answers by more than twice the noise floor consistently across statements and both prompt wordings.

## Condition-level shifts (mean signed shift S, all statements)

| model | variant | condition | mean S | 95% CI | mean abs Delta |
|---|---|---|---|---|---|
| gpt-4.1-mini | P1 | blank | -0.102 | [-0.208, -0.014] | 0.125 |
| gpt-4.1-mini | P1 | democrat | -0.278 | [-0.521, -0.067] | 0.348 |
| gpt-4.1-mini | P1 | republican | +0.247 | [-0.074, +0.590] | 0.420 |
| gpt-4.1-mini | P1 | scrambled_democrat | -0.026 | [-0.177, +0.129] | 0.200 |
| gpt-4.1-mini | P1 | scrambled_republican | +0.003 | [-0.119, +0.139] | 0.163 |
| gpt-4.1-mini | P2 | blank | +0.024 | [-0.092, +0.146] | 0.167 |
| gpt-4.1-mini | P2 | democrat | -0.440 | [-0.732, -0.170] | 0.540 |
| gpt-4.1-mini | P2 | republican | +0.286 | [-0.065, +0.659] | 0.558 |
| gpt-4.1-mini | P2 | scrambled_democrat | +0.008 | [-0.184, +0.244] | 0.232 |
| gpt-4.1-mini | P2 | scrambled_republican | +0.022 | [-0.148, +0.237] | 0.213 |

## Mixed-effects shift per condition vs none (+ = right/authoritarian)

| model | condition | shift | 95% CI | p (two-sided) |
|---|---|---|---|---|
| gpt-4.1-mini | blank | -0.039 | [-0.298, +0.221] | 0.7700 |
| gpt-4.1-mini | democrat | -0.359 | [-0.618, -0.099] | 0.0067 |
| gpt-4.1-mini | republican | +0.267 | [+0.007, +0.526] | 0.0439 |
| gpt-4.1-mini | scrambled_democrat | -0.009 | [-0.268, +0.251] | 0.9471 |
| gpt-4.1-mini | scrambled_republican | +0.013 | [-0.247, +0.272] | 0.9245 |

## Data quality

- Rows with option_mass < 0.5: 0 of 1140 (min option_mass 0.896, mean 0.9994).
- Calls that hit OpenAI's prompt cache: 158 of 1140. Mean E difference, prompt-cached minus uncached, within the same call cell: -0.015 (should be near 0).
- Baseline (none) per statement, mean E / entropy across models and variants:
  - q01: E=3.02, entropy=0.15 bits
  - q02: E=4.22, entropy=0.90 bits
  - q04: E=3.20, entropy=0.70 bits
  - q05: E=3.91, entropy=0.85 bits
  - q06: E=3.06, entropy=0.35 bits
  - q07: E=2.78, entropy=0.30 bits
  - q10: E=2.99, entropy=0.06 bits
  - q11: E=3.01, entropy=0.06 bits
  - q12: E=3.02, entropy=0.09 bits
  - q13: E=3.00, entropy=0.00 bits
  - q14: E=3.00, entropy=0.00 bits
  - q15: E=3.00, entropy=0.00 bits
  - q19: E=3.43, entropy=0.62 bits
  - q20: E=2.93, entropy=0.16 bits
  - q21: E=2.61, entropy=0.33 bits
  - q22: E=2.74, entropy=0.44 bits
  - q23: E=3.04, entropy=0.19 bits
  - q24: E=3.00, entropy=0.00 bits
  - q27: E=4.52, entropy=1.08 bits
