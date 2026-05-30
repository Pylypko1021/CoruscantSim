# Copilot Instructions for Coruscant Autoresearch (local root)

Use `Coruscant Autoresearch` for optimization tasks in this folder:
- train.py
- results.tsv
- program.md

Rules:
- edit only parameter block in train.py
- run exactly one experiment per proposal
- keep if `new_score < best_previous_score`, else revert
- keep parameters in ranges from program.md

Validation after each run:
- command succeeded
- score printed
- results.tsv appended

Execution mode:
- do not start detached/background optimization tasks
- run in foreground and report iteration progress in current chat
