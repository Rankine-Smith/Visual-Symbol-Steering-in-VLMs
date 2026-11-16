# Cue ladder in plain language (written after the pre-registered analysis; see summary.md for the tables)

**What we tested.** On 16 fresh statements, balanced so that agreeing is the right-wing answer on half of them and
the left-wing answer on the other half, we put one of these in the image corner:
- a party logo (Democrat or Republican);
- an approval cue (thumbs up/down, 5 stars or 1 star);
- a plain green or red square.

Seven OpenAI models were tested, from gpt-4.1-mini to gpt-6.1-terra.

**Pre-registered result 1 (H1): supported.** Approval cues move answers in old and new models alike.
- gpt-4.1-mini and gpt-4.1 agree about 2.6 and 1.5 points less (on 1–5) with a thumbs-down or one star than with
  a thumbs-up or five stars, on 16 of 16 statements.
- Forced to choose (no "neither"), 3 of the 5 newer models pass the test: gpt-5.1, gpt-5.4-mini and
  gpt-6.1-terra.
- gpt-5.6-luna and gpt-6-luna lean the same way but don't pass after correction.
- With "neither" available, 6 of the 7 models pass; gpt-6-luna is the exception.
- The thumbs pair alone moves all 5 newer models under forced choice (uncorrected p ≤ 0.008).

**Pre-registered result 2 (H2): not supported.** We predicted that in at least 3 of the 5 newer models, under
forced choice, the cue effect would be clearly larger than the party effect. That held in 2 of 5 (gpt-5.4-mini and
gpt-6.1-terra).
- gpt-5.1 fails mostly because, forced to choose, it also shows a party lean (D −0.26, p = 0.065). That lean
  follows ideology: −0.23 on right-coded statements, +0.28 on left-coded ones.
- With "neither" available, the cue-beats-party contrast passes in 3 of 5 (gpt-5.1, gpt-5.4-mini, gpt-6.1-terra).
  That was not the pre-registered group.

**Party logos on these fresh statements.**
- gpt-4.1-mini (D −0.85) and gpt-4.1 (−0.69) move toward the logo's party, as in the ladder confirmation (these
  rows are the same cached calls).
- Their lean follows ideology: with the Democrat logo they agree less with right-coded and more with left-coded
  statements (Mann-Whitney p < 0.001 between halves).
- From gpt-5.1 on, party D is within ±0.05 with "neither" available. Under forced choice it is within ±0.08,
  except gpt-5.1 at −0.26.

**Agreement, not ideology.** The cue effect lowers agreement on both halves of the statements. That is what an
agreement cue should do, unlike the party effect, which flips with the statement's ideology.

**Controls.**
- Scrambled logos are about 0 everywhere.
- The red vs green square has a small effect in some models: gpt-4.1 −0.35, gpt-5.4-mini −0.11/−0.12,
  gpt-4.1-mini −0.08 (p ≈ 0.004–0.03, two-sided, uncorrected). That is a fraction of their cue effects, so the
  cue effects are not just colour. The colour on its own is not nothing, though.
