# REVIEW.md

| # | Where | What is wrong | How you'd notice it | How you fixed it |
|---|---|---|---|---|
| 1 | `compute_late_minutes` | Uses naive `replace` which fails for IST logic. | A punch at 09:35 IST would compare incorrectly to UTC. | Used timezone-aware IST conversion. |
| 2 | `list_employees` | `skip = page * page_size` | Page 1 skips the first 20 records. | Changed to `(page - 1) * page_size`. |
| 3 | `punch_in` | Lacks atomicity; uses check-then-insert. | Two simultaneous requests create two documents for one date. | Added Compound Unique Index and try/except block. |
| 4 | `compute_work_hours` | Uses standard `round()` (Banker's rounding). | 2.225 rounds to 2.22 instead of 2.23. | Implemented `Decimal` with `ROUND_HALF_UP`. |
| 5 | `compute_overtime` | Fails to handle overnight logic or the 30-min threshold. | Punches 20 mins after shift end incorrectly show as OT. | Added 30-min threshold and overnight window logic. |