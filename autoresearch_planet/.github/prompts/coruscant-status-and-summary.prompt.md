---
description: "Check Coruscant autoresearch status from results.tsv and running processes."
---
Use agent Coruscant AR Researcher.

Tasks:
1. Read results.tsv.
2. Return:
- total rows
- current best row
- last 10 rows
- whether proposals are repeatedly non-improving
3. Check whether train.py process is active or idle.
4. Return recommendation:
- continue
- stop and restart
- adjust mutation strategy
