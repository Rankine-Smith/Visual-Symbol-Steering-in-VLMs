# Symbols

Drop one image per symbol here. The filename stem becomes the condition label in the results
(`usa.png` → `usa`). PNG is best; JPG and WEBP also work.

You don't need to resize or crop anything. The tool trims borders, scales every symbol to the same
pixel area, places it in the same corner, and builds blank and scrambled controls automatically.

Pilot set (suggested):
- `usa.png`: Flag of the United States
- `china.png`: Flag of the People's Republic of China
- `hammer_sickle.png`: Hammer and sickle (strong "positive control" cue)

Easiest source: Wikimedia Commons. Search "Flag of China.svg", open the file page, and click a PNG
size such as 1,000 px. Save the image and rename it.

If you add a symbol, also add a row to `keywords.csv` so the "did the model see it?" check knows what
words to look for.
