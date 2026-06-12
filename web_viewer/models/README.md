# Army models

Low-poly GLB models by **Quaternius** (https://quaternius.com), licensed
**CC0 1.0** (public domain) — free for any use, no attribution required
(but appreciated, hence this note). Downloaded via the
trebeljahr/quaternius-showcase mirror.

| File | Source pack / model | Role in the viewer |
|---|---|---|
| `infantry.glb` | Cyberpunk pack — Enemy_2Legs_Gun | infantry corps marker |
| `armor.glb` | Cyberpunk pack — Enemy_Large_Gun | armor divisions marker |
| `aircraft.glb` | Ultimate Spaceships — Striker | strike wing marker |
| `fleet.glb` | Ultimate Spaceships — Executioner | orbital fleet marker |

Replace any of these files with your own GLB and the viewer picks it up
on reload (`web_viewer/src/rts.js` auto-loads them, with a procedural
fallback when a file is missing). Meshopt-compressed GLBs are supported.

`preview/` holds review candidates (gitignored); `../models.html` is a
grid viewer to compare them.
