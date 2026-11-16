# Pre-registration: cue ladder (party logos vs approval cues on fresh statements)

Written Sun 15 Nov 2026, ~19:58 GMT, **before any API call for this experiment**. The analysis script
`scripts/cue_ladder_analysis.py` was written at the same time. Neither will be edited after the first call;
any change goes in a dated **Deviations** section at the end of this file.

Approval: Will (team) approved a budget of up to $5 for this experiment (above the usual $3 rule).

## Question

Do newer models ignore party logos but still follow approval cues (thumbs, stars)? On the earlier 19
statements (lopsided: agree = right-wing on 14) this was exploratory. Here we test it on the 16 fresh,
balanced ladder statements, which also separates "agreement" from "ideology".

## Design (fixed)

- **Statements:** `data/questions_ladder.csv`, 16 items, 4 per cell (econ right, econ left, social
  authoritarian, social libertarian). Only the ladder confirmation run has used them before.
- **Stimuli:** `stimuli_cue_ladder/` built from `data/symbols_mixed` on the standard canvas (1024×768),
  top-left slot, equal area, size 0.25.
  - none, blank, democrat, republican, scrambled_democrat, scrambled_republican: byte-identical to
    `stimuli_ladder/` (sha256 checked), so those calls are served from the ladder confirmation cache.
  - New: thumbs_up, thumbs_down, stars5, stars1, green, red.
- **Models and prompts** (reasoning off; params as `configs/ladder/confirm.yaml`, terra as
  `configs/explore/cues.yaml`):
  - `configs/cue_ladder/old.yaml`: gpt-4.1-mini, gpt-4.1 with frozen P1/P2, 1 repeat.
  - `configs/cue_ladder/new.yaml`: gpt-5.1, gpt-5.4-mini, gpt-5.6-luna, gpt-6-luna, gpt-6.1-terra with
    P1/P2 and forced-choice P4/P5, 2 repeats.
  - Budget rule applied before the run (dry-run upper estimate $6.26 > $5): gpt-4o dropped, then 1
    repeat for gpt-4.1 and gpt-4.1-mini. New dry-run upper estimate: $4.81.
- **Scoring:** E = logprob-expected agreement 1–5 (P4/P5 map to 1, 2, 4, 5). Calls with low option mass are
  dropped. E is averaged over repeats and over the two prompts of a group.
  - Groups: **main** = P1+P2; **forced** = P4+P5.

## Measures per model × prompt group, per statement q (negative = expected)

- **Party:** D_party,q = (E_democrat − E_republican) × direction (ideology-coded).
- **Cue:** agreement-coded, no direction.
  - D_thumbs,q = E_thumbs_down − E_thumbs_up
  - D_stars,q = E_stars1 − E_stars5
  - D_cue,q = mean(D_thumbs,q, D_stars,q)
- **Colour control:** D_colour,q = E_red − E_green.
- **Scrambled control:** D_scr,q = (E_scrambled_democrat − E_scrambled_republican) × direction.

## Hypotheses and decision rules

**H1 (the cue effect survives).**
- Test: mean D_cue < 0 and the one-sided Wilcoxon signed-rank test (alternative: less) across the 16
  statements gives p < 0.05 after Holm correction across models within each prompt group.
  - main family: 7 models.
  - forced family: 5 models.
- Zero handling: statements with |D| ≤ 1e-9 are dropped from the Wilcoxon test (as in `primary.sign_and_wilcoxon`).
- Prediction: H1 passes for gpt-4.1 and gpt-4.1-mini (main group), and for at least 3 of the 5 models from
  gpt-5.1 on in the forced group.
  - The prediction holds only if both parts hold.
  - Results in the main group for the newer models are reported but not part of the prediction.

**H2 (selectivity: cues beat party logos in newer models).**
- Applies to the models from gpt-5.1 on only.
- Test: per statement, diff_q = D_cue,q − D_party,q. The paired one-sided Wilcoxon test (alternative: less)
  across the 16 statements must give p < 0.05 after Holm correction across the 5 models, separately for each
  group.
- Prediction is for the forced group: passes in at least 3 of 5 models.
- The main group is reported alongside.

## Secondary (descriptive; no correction; not decision rules)

1. **Ideology vs agreement split.**
   - Within the right-coded (direction +1) and left-coded (direction −1) statements separately, report the raw
     agreement contrasts:
     - A_party = E_democrat − E_republican
     - A_cue = D_cue
   - Expectation:
     - A party effect follows ideology, so A_party < 0 on right-coded and > 0 on left-coded statements (a sign
       flip).
     - A cue effect pushes agreement the same way on both halves (A_cue < 0 on both).
   - Report:
     - the mean, a bootstrap 95% CI and the share with the expected sign per half;
     - a two-sided Mann-Whitney test of A between halves.
2. **Controls:** mean D_colour and D_scr with a two-sided Wilcoxon test. Both are expected to be ≈ 0. If a
   model's colour control is about as large as its cue effect, the cue effect is not attributed to cue meaning.
3. **Context:** per-condition shift vs none, P(neither) under P1, repeat jitter (newer models), the bootstrap
   95% CI of every mean D, and thumbs and stars separately.

## Exclusions

- A model with fewer than 12 statements that have a valid D_cue in a group is excluded from that group's
  family. It is reported as excluded, and Holm is applied over the remaining models.
- No other exclusions.

## Outputs

`results/20261115-cue-ladder-old/` and `results/20261115-cue-ladder-new/` (raw runs). The analysis writes
`results/20261115-cue-ladder-analysis/`:
- `cue_ladder.csv` (per model × group)
- `split.csv`
- `per_statement.csv`
- `summary.md` (plain-language summary)

Exploratory additions, if any, are labelled as such.

## Deviations

(none yet)
