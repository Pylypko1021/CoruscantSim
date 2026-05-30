---
description: "Run Coruscant stable autoresearch batch via coordinator + subagents with keep/revert and early-stop policy."
---
Use agent Coruscant Autoresearch.

Run stable optimization in this folder with:
- iteration budget: 20
- early stop: 10 consecutive reverts
- execution mode: foreground only (no detached/background)
- strict rule: keep only if new_score < best_previous_score, else revert parameter block

Operate only in:
- train.py
- results.tsv
- program.md

After each iteration report:
- iteration number
- proposed params
- score
- keep/revert
- current best score + params

Do not start background tasks; execute and stream progress in this chat.

At completion return:
- final best score
- final best params
- top 10 rows from results.tsv sorted by score
