---
name: verify-financial-number
description: Independently verify a computed financial value shown by the app (a dashboard total, chat answer, runway/goal projection, scenario estimate) — used whenever confirming a calculation is correct, not just that code ran without error. Triggers on "verify", "check this number", "did you check off the success criteria", or any point where a computed total needs confirming before reporting a feature as done.
---

# Verify a Financial Number Independently

This project's core principle is "accuracy over features, never guess financial data" (`CLAUDE.md`). A verification that re-calls the same aggregate function it's trying to check proves the code is wired up consistently — it does not prove the calculation is correct. This was caught mid-project (Phase 3: the user asked "did you check off all the success criteria?" after a same-code-path check had been reported as verification) and has been the standard since.

## 1. The check must share zero code with the thing being checked

Never verify by calling the same Python function (even indirectly) that produced the displayed number. Instead:
- Query `backend/finance.db` directly with raw SQL (via Python's `sqlite3` module, or an equivalent), re-deriving the same figure from first principles.
- Match the app's actual business rules by hand in the SQL — e.g. this project's "real spending" filter excludes `is_transfer = 1` **and** anything categorized "Transfers" (see `app/dashboard/aggregates.py::_load_real_transactions`); an independent check has to encode that same exclusion itself, in SQL, not by importing the Python function that already does it.
- If the feature involves a trailing-N-month window, replicate the exact windowing convention (this project anchors "trailing N months" to the **latest transaction date in the data**, not wall-clock today — get this from `MAX(date)` in SQL, matching `latest_transaction_date`'s behavior, don't assume "today").

## 2. Where to run the check — the dev-server trap

If a `uvicorn --reload` dev server is running and watching `backend/`, running a verification script *from inside* that directory (even a throwaway `python -c "..."`) writes to `__pycache__`/`.pytest_cache` inside the watched tree and can silently trigger a reload mid-check, making the server serve stale code right when you're trying to confirm it isn't. See the `dev_server_gotchas` memory for the full diagnosis.

**Run verification scripts from outside the watched directory** — e.g. the session scratchpad — invoking the venv's Python by full path:

```
"<repo>/backend/venv/Scripts/python.exe" "<scratchpad>/verify_something.py"
```

Never `cd` into `backend/` to run a one-off check while a `--reload` server for this project is live.

## 3. Prove the rule matters, not just that the numbers happen to match

For anything involving a filter or exclusion (transfers, category scoping), also compute the **naive** version without the filter and show the two differ meaningfully. A filtered and unfiltered number that happen to match either means the filter had no real transactions to act on (worth noting) or the filter isn't actually being applied (a real bug the match-only check would hide). Phase 3's transfer-exclusion check did this: naive July totals were $17,983/$13,384 vs. the correctly-filtered $7,392/$5,071 — proving the exclusion had real effect, not just checking the filtered number in isolation.

## 4. Test the honest-refusal case, not just the easy positive example

If the feature can produce a "no," prefer verifying that state over a trivially-positive one — it's the more meaningful test of whether the app is willing to say "not enough data," "not on track," or "already met" rather than fabricating a number. Phase 5 deliberately verified a goal that was genuinely not on track (negative average net savings) rather than only demonstrating the on-track case.

## 5. Report the actual matched numbers, not just "verified"

State both values side by side (e.g. "app: 492938 cents, independent SQL: 492938 cents — exact match") so the evidence is visible, not asserted. If they don't match, stop and investigate the discrepancy before reporting anything as done — don't round off or hand-wave a mismatch.

## 6. Clean up afterward

- Delete the throwaway verification script from the scratchpad once done.
- If verification required creating real records in the actual app database (a test goal, a manually-set balance, a demo transaction) rather than an isolated in-memory test fixture, delete or reset them afterward via the app's own API where possible — this is the user's live personal financial app, not a disposable test environment, and it should be left exactly as it was found aside from the feature you were asked to build.
