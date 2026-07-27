# Low-Level Design — Personal Finance App (Phase 5: Savings Goals, Vacation Planner, Financial Runway, Scenario Analysis)

**Status: complete and independently verified** (2026-07-27), against the real transaction database — see §5.

Companion to `hld_claude.md`, `lld_claude.md` (Phase 1), `lld_phase2_claude.md`, and `lld_phase4_claude.md`. Covers CLAUDE.md's final roadmap phase.

## 1. Architecture

Unlike Phases 3-4, this phase needs genuinely new persisted, user-entered data rather than pure aggregation over transactions. Two of its four sub-features (financial runway, "can I afford X") require knowing how much money the user currently has, and the app has no way to derive that: every CSV import so far has been a bounded date range, never a full account history from account-opening, so summing transactions gives only the *net change* over the imported window, not a real current balance. Per CLAUDE.md's "never guess financial data," this is explicit user input, never inferred.

Design decisions confirmed with the user before building:
1. **Current balance**: one manually-entered total (`CurrentBalance`, effectively single-row), not per-account, not derived.
2. **Vacation planner**: not a separate feature — a vacation is just a `SavingsGoal` with a name, target amount, and target date.
3. **Goal progress**: `saved_so_far_cents` is a manual field the user updates themselves — the app never guesses which dollars are earmarked for which goal, especially with multiple simultaneous goals.
4. **UI**: a fourth "Planning" tab, alongside Transactions/Dashboard/Chat.

Scenario analysis reuses Phase 4's `estimate_category_reduction_savings` rather than reinventing it — this phase composes that number onto a goal's timeline or the runway figure via `apply_scenario_to_goal` / `apply_scenario_to_runway`, it doesn't recompute the underlying category-average logic.

## 2. Data Model (first new tables since Phase 1)

```python
class SavingsGoal(Base):
    id, name, target_amount_cents, target_date (nullable), saved_so_far_cents (default 0)

class CurrentBalance(Base):
    id, amount_cents, updated_at
```

`CurrentBalance` is effectively single-row: the API always reads/upserts "the" row via `_get_balance_row`. `GET /balance` returns `configured: false` if no row exists — a missing balance is an incomplete-setup state, deliberately never defaulted to 0, since $0 would misleadingly imply "you have no money" rather than "you haven't told the app yet."

## 3. Backend

`backend/app/planning/aggregates.py` (mirrors the `dashboard/aggregates.py` / `chat/tools.py` business-logic-separate-from-routing split):

- `average_monthly_expense` / `average_monthly_net_savings`: average `monthly_summary` rows over the trailing window (reused, zero-filled convention already established).
- `get_current_balance_cents`: shared by the router (`GET /runway`) and the chat tool (`get_financial_runway`) so the balance lookup isn't duplicated.
- `compute_runway` / `_project_runway`: `runway_months = balance / avg_expense`, or `None` if the balance isn't configured (an incomplete-setup state) or avg expense is 0 (no historical signal — never infinite runway). `projected_end_date` extrapolates from the **latest transaction date** in the data, not wall-clock "today" — same convention as `dashboard.aggregates.latest_transaction_date`.
- `project_goal_timeline` / `_project_goal`: three explicit states — `already_met` (remaining ≤ 0), `not_on_track` (avg net savings ≤ 0 — never a negative or infinite month count), `on_track` (a real projected date).
- `apply_scenario_to_runway` / `apply_scenario_to_goal`: composition helpers — take the `monthly_savings_cents` Phase 4's `estimate_category_reduction_savings` already computed and reapply it against the base average (reducing expense for runway, adding to net savings for a goal), returning the same `RunwayOut`/`GoalProjectionOut` shapes so the frontend renders "before vs. after" with one component.

`backend/app/routers/planning.py`: `GET/POST /goals`, `PATCH/DELETE /goals/{id}`, `GET /goals/{id}/projection`, `GET/PUT /balance`, `GET /runway`, `POST /scenario` (resolves `category_name` via the same `resolve_category_id` Phase 4 already built in `chat/tools.py` — reused, not duplicated).

Two new chat tools (`get_savings_goals`, `get_financial_runway`) so the existing chatbot can also answer PROJECT_CONTEXT.md's example question "Can I afford a $4,000 vacation next summer?" — both thin wrappers over the same `planning/aggregates.py` functions the REST endpoints use.

## 4. API

| Endpoint | Behavior |
|---|---|
| `GET /goals` | list all goals |
| `POST /goals` | create `{name, target_amount_cents, target_date?, saved_so_far_cents?}` |
| `PATCH /goals/{id}` | update any field |
| `DELETE /goals/{id}` | remove |
| `GET /goals/{id}/projection?months=6` | timeline projection |
| `GET /balance` | `{configured, amount_cents, updated_at}` |
| `PUT /balance` | `{amount_cents}` — upserts |
| `GET /runway?months=6` | runway projection |
| `POST /scenario` | `{category_name, reduction_percent, months, goal_id?}` — returns the plain savings estimate plus, if `goal_id` given, the accelerated goal projection, else the extended runway |

## 5. Success Criteria — verified against the real database

- **Savings goal timeline, not a guess**: created a real goal ($10,000 target) against the actual 6-month transaction history. Average net savings over that window was independently computed via raw SQL as **-$380.18/month** (income minus expense, transfers excluded, same convention as `monthly_summary`) — the app correctly reported `not_on_track` rather than fabricating a timeline. This is the more meaningful test case than an always-positive on-track example: the app has to be willing to say "no" honestly.
- **Financial runway, using a real manually-entered balance**: set balance to $3,000 (via the actual UI, not the API directly). App reported `avg_monthly_expense_cents = 492938` and `runway_months = 1.0143263453010318`. Independently recomputed via raw SQL directly against `finance.db` (a script sharing zero code with the app, run from outside the watched backend directory): **exact match** on both numbers, down to the full float precision of the division.
- **Scenario analysis reuses Phase 4, doesn't reinvent it**: ran "reduce Dining & Drinks by 25% over 6 months" against the goal above. App reported an estimated $314.25/month savings, based on an independently-reverified average dining spend of $1,256.99/month (exact match to Phase 3/4's already-tested `estimate_category_reduction_savings`), composed onto the goal's -$380.18/month base to give -$65.93/month — correctly still `not_on_track`, confirmed by hand.
- **Chatbot can answer goal/runway questions**: `get_savings_goals` and `get_financial_runway` tool-dispatch unit-tested (`test_chat.py`); both call the identical `planning/aggregates.py` functions as the REST endpoints — one source of truth, two surfaces, per Phase 4's existing architecture.
- Full backend test suite: 114/114 passing (92 carried over from Phase 4 + 22 new: 13 aggregate-level, 3 chat-tool-dispatch, 6 router CRUD/scenario). `tsc -b` + `oxlint` clean.

## 6. Explicit Non-Goals (this phase)

- No per-account balance tracking or reconciliation — one manual total only.
- No multi-currency support.
- No automatic re-allocation of savings across multiple goals — each goal's `saved_so_far_cents` is independently user-maintained.

## 7. Gotcha Encountered During This Phase (environment, not code)

Verifying the new endpoints live was repeatedly blocked by `uvicorn --reload` appearing to serve stale code even immediately after a clean restart with no errors in the startup log. Root cause, finally isolated: running `python -c "..."` or `pytest` *from inside the watched `backend/` directory* while the reloader is running writes to `__pycache__`/`.pytest_cache` inside that same tree, which the file watcher picks up as a change and silently restarts the server mid-verification — racing every diagnostic command against its own trigger. Fix: run verification/debugging scripts for the *running* app from **outside** the watched directory (e.g. the session scratchpad, invoking the venv's `python.exe` by full path) rather than `cd`-ing into `backend/` to run one-off checks while a dev server with `--reload` is live. This combines with the earlier-documented orphaned-process gotcha ([[phase4-status]]) as the two dev-workflow issues worth checking first whenever a running server seems to disagree with the code on disk.
