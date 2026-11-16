# Exp B1: manipulation checks (exploratory, frozen check prompts)

Describe: "Describe everything you can see in this image, including any small details." on the first 8 ladder statements per condition; transcribe: all 16 `none` images. Temperature 0. Keyword-coded.

| model | names_democrat | names_republican | names_thumbs_down | names_stars1 | none_false_positive (names any symbol-like element) | transcribed (ratio >= 0.9) | mean_transcription_ratio |
|---|---|---|---|---|---|---|---|
| gpt-4.1 | 8/8 | 8/8 | 8/8 | 8/8 | 0/8 | 16/16 | 1.0 |
| gpt-4o | 8/8 | 8/8 |  |  | 0/8 | 16/16 | 1.0 |
| gpt-5.1 | 8/8 | 8/8 |  |  | 0/8 | 16/16 | 1.0 |
| gpt-5.2 | 8/8 | 8/8 |  |  | 0/8 | 16/16 | 1.0 |
| gpt-5.4-nano | 0/8 | 8/8 |  |  | 1/8 | 16/16 | 1.0 |
| gpt-5.4-mini | 8/8 | 8/8 |  |  | 0/8 | 16/16 | 1.0 |
| gpt-5.4 | 8/8 | 8/8 |  |  | 0/8 | 16/16 | 1.0 |
| gpt-5.6-luna | 8/8 | 8/8 |  |  | 0/8 | 16/16 | 1.0 |
| gpt-5.6-terra | 8/8 | 8/8 |  |  | 0/8 | 16/16 | 1.0 |
