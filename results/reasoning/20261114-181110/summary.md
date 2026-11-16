# Awareness, Method 3: reasoning traces (`20261114-181110`)

**Exploratory.** Model gpt-5-nano (Responses API, reasoning effort `medium`, summary `auto`), prompt P1 unchanged, 8 samples per statement x condition. Judge: gpt-4.1-mini at temperature 0.0 with a fixed rubric (`src/vcb/judge.py`).

- Samples: 912; answer parsed: 100.0%; reasoning summary present: 52.3%; mean reasoning tokens 449.
- Cost: $0.321.

> **Limitation.** Reasoning summaries are a lossy, provider-generated view of the model's reasoning, not the reasoning itself. A symbol that shaped the answer can be missing from the summary, and a mention in the summary does not prove it was used. Treat verbalisation rates as a lower bound on what the summary shows, not ground truth.

## 1. Is there a symbol effect with reasoning on?

Contrast democrat vs republican on sampled expected scores (D = S_x - S_y; expected sign -1):

- Statements in the expected direction: **11 of 15** (ties |D| <= 0.01 excluded); one-sided sign test p = 0.0592; Wilcoxon p = 0.0239.
- Mean D = -0.125 (95% CI -0.237 to -0.020); scrambled-pair mean D = -0.013.
- Mean signed shift S vs none: blank -0.046, democrat -0.151, republican -0.026, scrambled_democrat -0.086, scrambled_republican -0.072.
- Mean |Delta| vs none (sampling noise with 8 samples is large; compare with blank and scrambled): blank 0.138, democrat 0.217, republican 0.211, scrambled_democrat 0.164, scrambled_republican 0.230.
- Compared with the logprob model (gpt-4.1-mini, P1, run `20261114-173050`): mean D there -0.525; per-statement Spearman between the two models' D = -0.008.

## 2. Does the reasoning mention the symbol?

Shifted = the sample's answer moved in the symbol's direction relative to the modal `none` answer for that statement (Democrat logo: left/libertarian; Republican logo: right/authoritarian). Scrambled copies are scored with their source symbol's direction as a control. Blank: moved either way.

| group | n | mentions (dismissed + used) | mentioned & used | mentioned & dismissed |
|---|---|---|---|---|
| blank: moved | 22 | 0% | 0% | 0% |
| blank: not moved | 58 | 2% | 0% | 2% |
| none | 91 | 1% | 1% | 0% |
| scrambled: 'shifted' | 30 | 0% | 0% | 0% |
| scrambled: not shifted | 125 | 6% | 0% | 6% |
| symbol: not shifted | 109 | 24% | 14% | 10% |
| symbol: shifted | 42 | 26% | 17% | 10% |
| symbol=democrat | 73 | 32% | 19% | 12% |
| symbol=republican | 78 | 18% | 10% | 8% |

## In plain terms

With reasoning on, gpt-5-nano does not show a reliable democrat vs republican effect at this sample size (11/15 statements, p = 0.059).
**Verbalisation rate: 26%** of the 42 samples that shifted toward the symbol's side mention the symbol in their reasoning summary (17% treat it as relevant, 10% mention it and set it aside), against 24% of the 109 symbol samples that did not shift.

Caveats on these rates: they use only the 52% of samples that came back with a non-empty summary (by condition: blank 53%, democrat 48%, none 60%, republican 51%, scrambled_democrat 48%, scrambled_republican 54%). "Shifted" is mostly sampling noise at 8 samples: scrambled copies 'shift' in their source symbol's direction 16% of the time, against 20% for the real symbols, so most shifted symbol samples would have moved anyway.

Hand-check: 30 random cases are in `handcheck.csv` and the UI's Awareness tab.
