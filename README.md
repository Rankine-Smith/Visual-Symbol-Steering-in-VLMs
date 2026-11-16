# Visual Symbol Injection Silently Steers Multimodal Judgments

By Will Rankine Smith and Shayan Navab.

Code, stimuli and summary results for our Apart Research AI x Epistemics sprint project (13–16 Nov 2026).

**Summary.** We put a small, task-irrelevant symbol in the corner of an image that shows a political statement. The symbol is a party logo, a flag or an approval cue such as a thumbs-down. The text prompt never mentions the symbol; it only asks the model for its own view on a 5-point scale. We read the expected agreement from the answer token's logprobs and compare each symbol with no symbol, a grey box and a pixel-scrambled copy of the same symbol, across OpenAI and xAI vision-language models.

**Paper:** [PAPER LINK]

## Headline results

- **Party logos move older models toward the party, and the effect is gone from gpt-5.1 on.** In gpt-4.1-mini and gpt-4.1, the Democrat logo against the Republican logo moves answers toward that party's side by 0.7–0.9 points on the 1–5 scale: D −0.88 and −0.71 in the ladder confirmation (decision rule fixed in advance, Holm p ≤ 0.039), and −0.85 and −0.69 in the pre-registered cue ladder. gpt-4.1-mini's effect was first confirmed in our pre-registered test (p = 0.015). Scrambled logos with the same colours do nothing (D +0.01, +0.08). From gpt-5.1 on, the party contrast is near zero: |D| ≤ 0.05 with a neutral option. The one hint under forced choice is gpt-5.1, at −0.26 (p = 0.065).
- **Approval cues still move most models.** A thumbs-down or one-star cue, against a thumbs-up or five-star cue, lowers agreement in gpt-4.1-mini (D −2.61) and gpt-4.1 (−1.54). It also lowers agreement under forced choice in gpt-5.1 (−0.44), gpt-5.4-mini (−0.53) and gpt-6.1-terra (−0.20), all with Holm p ≤ 0.003. This is pre-registered hypothesis H1, and it is supported.
- **gpt-4.1 names the logo yet denies influence** (exploratory). Asked what is in the top-left corner, it names the party logo in 22 of 22 conversations per logo. Asked whether anything in the image influenced its answer, it says no (P(Yes) = 0.00), although the logo moved its answers.

[docs/experiments-overview.md](docs/experiments-overview.md) is the full experiment log. It marks every result as pre-registered or exploratory and keeps the null results and caveats.

## Repo map

```
src/vcb/            package: stimulus composer, API client + cache, logprob scoring, analyses, CLI (python -m vcb)
scripts/            stand-alone analyses and stimulus generators (cue_ladder_analysis.py, ladder_analysis.py,
                    scale_scores.py, compass_scores.py, make_*_stimuli.py, ...)
app.py              Streamlit UI for browsing runs (optional)
config.yaml         default config: the pilot and the first pre-registered confirmation run
config_*.yaml       configs for the day-1 follow-ups (Grok, newer models, awareness, large symbols, ...)
configs/            configs for the later runs: cue_ladder/, ladder/, explore/, awareness/, awareness_b1/
data/               statement sets (questions_*.csv, candidates.csv; questions.csv = 11-item pilot set),
                    symbol images (symbols*/), statement screening summary (screen/screen.csv)
examples/stimuli/   12 example stimuli (statement n01, every cue-ladder condition)
prereg/             the two pre-registrations and the cue-ladder hash file, unchanged
results/            summary tables behind the reported numbers, plus the per-call scores.csv the analyses read
docs/               experiments-overview.md: the full experiment log
```

Paths inside `docs/experiments-overview.md` and the pre-registrations use the original layout:
`documents/` is now `docs/`, and `PREREGISTRATION*.md` and the hash file are now in `prereg/`. Many run folders
cited there are not in this repo, because they held only raw API logs. `results/` keeps the summaries and the
inputs needed to rerun the main analyses.

## Quickstart

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .

# API calls only: put your key in .env (never commit it). Grok runs also need GROK_API_KEY.
echo "OPENAI_API_KEY=sk-..." > .env

# Regenerate stimuli (no API calls). Rebuilds stimuli_cue_ladder/ byte-identically to the images we ran.
python -m vcb --config configs/cue_ladder/old.yaml compose

# Run one experiment: check the call count and cost first, then run (cached and resumable)
python -m vcb --config configs/cue_ladder/old.yaml run --dry-run      # 768 calls, about $0.6–0.9
python -m vcb --config configs/cue_ladder/old.yaml run --run-id my-cue-ladder-old

# Rerun the analyses from the included CSVs (no API calls, no key needed)
python scripts/cue_ladder_analysis.py                        # -> results/20261115-cue-ladder-analysis/
python scripts/ladder_analysis.py 20261115-ladder-confirm    # -> results/20261115-ladder-confirm/ladder.csv
python scripts/scale_scores.py                               # -> results/20261115-scale-scores/
python scripts/compass_scores.py                             # -> results/20261115-compass/
python scripts/ladder_analysis.py 20261115-ladder-screen
python scripts/pilot_mixed_analysis.py
python scripts/paraphrase_analysis.py
python scripts/checks_b1_summary.py
python scripts/awareness_cues_analysis.py
```

Run the scripts from the repo root. All nine offline analyses above reproduce the committed outputs byte for byte;
check with `git status` after rerunning. `compass_scores.py` also writes `compass.json`, which is gitignored.
`awareness_corner.py`, `model_probe.py` and `temperature_probe.py` make API calls.

## Pre-registration

| File | SHA-256 |
|---|---|
| `prereg/PREREGISTRATION.md` (confirmation run, written 2026-11-14 before `results/20261114-173050`) | `343f0a84b2a905d1320462a4e9fc4a52bbb566ad22e83d518468ad1dfbbd8eea` |
| `prereg/PREREGISTRATION_cue_ladder.md` (cue ladder, written 2026-11-15 before any call) | `bc9fa15b2745959f469e3e17b9fe2da78a4dd79686b33c577f1d91346fdc0659` |
| `prereg/cue_ladder_prereg_hashes.txt` (hashes taken 2026-11-15T19:58:41Z, before the first cue-ladder call) | `b03346d1805fc2c1f7c677f7e6300a0fa9d698b6983d4cbe9891f2f5e7c56dd3` |

The hash file records the SHA-256 of the cue-ladder pre-registration, `scripts/cue_ladder_analysis.py` and
`configs/cue_ladder/{old,new}.yaml` before the run. All four still match. Check them with
`shasum -a 256 prereg/PREREGISTRATION_cue_ladder.md scripts/cue_ladder_analysis.py configs/cue_ladder/*.yaml`.
No hash was taken for `PREREGISTRATION.md` at the time: the file was last modified at 17:22 on 14 Nov, before
the confirmation run started at 17:30. The hash above was computed at release.

## Pre-existing code

None. All code and data in this repo were written during the sprint. The earliest file is dated 14 Nov 2026,
and the sprint started on 13 Nov. The project had no git history, so this rests on file creation dates.
The third-party libraries in `requirements.txt` are used as dependencies and are not vendored.

## AI-assisted development

The code, analyses and documentation were developed with AI coding assistance (Claude Code). Every result
comes from real, logged API calls; nothing in `results/` is simulated.

## Licence

Code and documentation: MIT, see [LICENSE](LICENSE). The party logos, flags and the presidential portrait in
`data/symbols*/` belong to their respective owners. They are included only as research stimuli.
