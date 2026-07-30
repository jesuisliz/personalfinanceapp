# Low-Level Design — Personal Finance App (Phase 4: Financial Chatbot)

**Status: built, unit-verified, and live-validated with a real `OPENAI_API_KEY` as of 2026-07-27 — all 6 tools exercised live through the actual Chat UI, two real bugs found and fixed in the process (see §6). Updated 2026-07-28: a category-taxonomy change (`lld_phase2_claude.md` §12) broke `get_category_transactions` for two categories; fixed, live-reverified, full suite 128/128 (see §9). Updated again 2026-07-28: multi-month questions could non-deterministically truncate at the tool-call round cap; `month` made optional so "all time" is one call instead of N; full suite 132/132 (see §10). Updated 2026-07-30: added a 7th tool, `get_merchant_transactions`, after a real question ("How much did I move to Vanguard?") revealed the model was summing transactions itself and ignoring a stated trailing-months window; full suite 157/157 (see §11).**

Companion to `hld_claude.md` / `lld_claude.md` (Phase 1), `lld_phase2_claude.md` (Phase 2), and the Phase 3 dashboard (no written doc — see `phase3_status` memory). Covers the OpenAI-backed chatbot: CLAUDE.md's Phase 4 roadmap item, answering questions like "Where is my money going?", "How much did I spend eating out?", "What categories increased?", "How much could I save by reducing dining?"

## 1. Architecture: OpenAI Tool-Calling, Not Prompt-Stuffing

CLAUDE.md's AI section is explicit: *"Use the OpenAI API to interpret user questions... Do not use the LLM to calculate totals. All calculations must come from backend code."* That constraint rules out just describing the user's data in a prompt and letting the model reason freely over it — the model must never be the one doing arithmetic.

The design is an **OpenAI tool-calling loop**: the model is given a fixed set of backend functions ("tools") it can call. It never sees raw transaction data unless it explicitly asks for it via a tool; every number in its final answer traces back to a tool result the backend actually computed against `finance.db`. The system prompt states this rule directly: never sum/average/estimate a number yourself — call a tool for any aggregation; you may only describe or compare numbers a tool has already returned (comparing two backend-computed numbers, e.g. "$600 > $400", is narration, not calculation).

Loop (`backend/app/chat/service.py::answer_question`):
1. Build messages: system prompt + recent history (capped to the last 20 messages) + the new user message.
2. Call `gpt-4o-mini` with the fixed tool schema.
3. If the response includes tool calls: execute each against the real database, append the assistant's tool-call message and each tool's result message, and call the model again.
4. Repeat until the model returns a plain answer with no further tool calls, or 5 rounds pass (a runaway-loop guard) — capped, not infinite.
5. Return the final text plus the ordered list of every tool call made (name, arguments, result) — the frontend renders this alongside the reply so every number is independently visible, not just asserted in prose.

## 2. Tool Schema

Defined in `backend/app/chat/tools.py::build_tool_schemas`, rebuilt fresh per request so the `category_name` enum always reflects the database's current categories (never hardcoded, never stale):

| Tool | Backed by | Purpose |
|---|---|---|
| `get_monthly_summary` | `dashboard/aggregates.py::monthly_summary` | Income/expense/net per trailing month |
| `get_category_breakdown` | `category_breakdown` | Spending by category for one month |
| `get_top_merchants` | `top_merchants` | Top merchants by spend for one month |
| `get_category_transactions` | `category_transactions`, or `non_spending_category_transactions` for `"Transfers"`/`"Credit Card Payment"` (see §9) | The individual transactions in one category. `month` is optional (see §10) — pass a specific `YYYY-MM` for one month, or omit it for every transaction in that category across all time in a single call |
| `get_category_trends` | `category_trends` *(new)* | Full category breakdown for each of the trailing N months, so the model can see which categories rose or fell — it reads numbers, it doesn't sum them |
| `estimate_category_reduction_savings` | `estimate_category_reduction_savings` *(new)* | Backend-computed monthly/annual savings from reducing one category's spend by X%, based on real average spend over N trailing months |

`category_name` parameters use a reserved value `"Uncategorized"` (mapped to `category_id IS NULL` via `resolve_category_id`) rather than a real category row, matching the convention already established by the Phase 3 dashboard's category drill-down.

An unrecognized category name raises inside `resolve_category_id`; `dispatch_tool_call`'s caller (`answer_question`) catches any exception per tool call and turns it into `{"error": "..."}` as the tool's result — visible to the model (which can retry with a valid name from its enum) and to the user (rendered as a small red note), never a crash.

## 3. API

`POST /chat`

Request: `{message: str, history: [{role, content}]}`
Response: `{reply: str, tool_calls: [{name, arguments, result}]}`

No `GET` endpoint and no persistence — see §4.

## 4. Data Model Additions: None

Deliberate choice, confirmed with the user before building: chat history is **in-memory only**, held in frontend React state and resent each turn. No new database table. Refreshing the page resets the conversation. This was scoped down from "persist to DB" specifically to match what Phase 4's roadmap item actually asks for, not to over-build a saved-chat-log product.

## 5. Frontend

`frontend/src/Chat.tsx` — a message list (user bubbles right-aligned blue, assistant left-aligned gray, errors as inline red system messages) + text input + send button, matching the existing app's plain Tailwind style (no chat library). Each assistant reply's `tool_calls` render as small supporting tables beneath it — one renderer per known tool-result shape (monthly summary, category breakdown, merchants, transactions, category trends per month, the savings estimate), falling back to pretty-printed JSON for anything unrecognized. Wired into `App.tsx` as a third tab alongside Transactions and Dashboard.

## 6. Success Criteria

**Verified now (no API key required):**
- Full backend test suite passes (92/92) with **zero real OpenAI network calls** — the tool-calling loop is tested via a fake client (`backend/tests/test_chat.py`) that returns canned responses, covering: an immediate final answer, one tool-call round then a final answer (asserting the tool actually ran against real in-memory data), the 5-round cap being respected, and an unknown-category tool error being surfaced as `{"error": ...}` rather than crashing.
- Every one of the 6 tools independently unit-tested via `dispatch_tool_call` for correct routing and JSON-safe output shape; `category_trends` and `estimate_category_reduction_savings` independently unit-tested in `test_dashboard.py` (zero-fill behavior, percent-of-average math, the `Uncategorized` special case).
- `resolve_category_id` tested for the found / not-found / `Uncategorized` cases.
- Missing `OPENAI_API_KEY` → confirmed **live**, in the actual running app (not just a test): `POST /chat` returns HTTP 400 with `"OPENAI_API_KEY is not configured. Add it to backend/.env."`, and the Chat tab renders that message as an inline error bubble rather than crashing. The rest of the app (Transactions, Dashboard) was confirmed unaffected in the same session.
- `tsc -b` and `oxlint` clean on the frontend.

**Live-verified 2026-07-27, once the user added a real key** — all 6 tools exercised through the actual running Chat tab, not just unit tests:
- `get_category_breakdown` / `get_category_transactions`: "How much did I spend on Dining & Drinks / Groceries last month?" → $1,579.68 and $910.23 respectively, each independently cross-checked via raw SQL (zero shared code, run from outside the watched `backend/` directory) — **exact match** both times.
- `get_top_merchants`, `get_monthly_summary`, `get_category_trends`, `estimate_category_reduction_savings`, `get_savings_goals`, `get_financial_runway`: each called correctly with sensible arguments through natural-language questions; `get_savings_goals`/`get_financial_runway` correctly reported the honest "no goals configured" / "balance not set" states rather than fabricating numbers — the harder, more meaningful test case per this project's verification conventions.
- `tsc -b` and `oxlint` still clean; full backend suite 116/116 (114 + 2 new regression tests).

**Two real bugs found by this live testing and fixed the same session (not something a fake-client unit test could have caught):**
1. The chatbot had no anchor for "today" — asked live, it guessed a training-data month (`2023-09`) instead of the data's real latest month, silently returning nothing for "last month" questions. Fixed by grounding the system prompt in `latest_transaction_date` each request.
2. Tool results are integers in cents; the model was *told* to convert to dollars in the system prompt but, in a multi-month `get_category_trends` narration, converted some entries correctly and others not at all (a 100x error — `85824` narrated as "$85,824" instead of $858.24). Fixed at the root: `chat/service.py::_cents_to_dollars` now converts every tool result to dollars **before** the model ever sees it, removing the conversion from its job entirely rather than trusting prompt-following.

**Known residual limitation, not fully fixable by architecture (documented, not silently accepted):** even after the cents/dollars fix, the same multi-month trends question showed the model transcribing a couple of already-correct dollar figures with a dropped digit (a 10x slip, e.g. $853.49 narrated as "$85.35") — a narration-fidelity slip, not a calculation or unit error; the underlying tool call and the UI's own rendered tables are always exactly correct regardless. This is the reason Phase 4 deliberately renders each tool's raw result alongside the prose reply (§5) — treat the prose as a summary and the table beneath it as the number of record.

## 7. Explicit Non-Goals (this phase)

- No persisted chat history / no new DB table (§4).
- No AI-assisted merchant categorization — CLAUDE.md's AI section mentions this as a future possibility, but it isn't a Phase 4 roadmap bullet and was already explicitly deferred in Phase 2 (§10 of `lld_phase2_claude.md`).
- No streaming responses — synchronous request/response is sufficient for this question set and simpler to implement and test.

## 8. Gotcha Encountered During This Phase (environment, not code)

Verifying the missing-API-key path live took much longer than it should have because of a genuinely orphaned `uvicorn --reload` process from earlier in the day: its **parent** process was invisible to `Get-Process`/`taskkill` (already gone), but a **child worker it had spawned** was still alive and still bound to port 8000, silently serving stale code (missing the new `/chat` route) underneath every newly-started server. Windows' own port-ownership tools (`netstat`, `Get-NetTCPConnection`) kept attributing the port to the dead parent PID, which was misleading. The fix was enumerating the full process tree (`Get-CimInstance Win32_Process ... | Select ProcessId, ParentProcessId, CommandLine`) to find the actual live child and kill it directly. Generalizable lesson: if a freshly-restarted dev server doesn't reflect a code change, don't assume the file watcher is the culprit — check for orphaned child processes still holding the port, not just the PID the launcher tool reports.

## 9. 2026-07-28 Bug — `get_category_transactions` always empty for non-spending categories, plus a new stale-reload variant

**User-reported symptom:** filtering the Transactions tab for June + "Credit Card Payment" showed real rows, but asking the chatbot the same question returned only a partial/wrong subset (3 of 10), then — immediately after the first fix attempt — zero.

**Root cause, layer 1 (environment):** the `uvicorn --reload` dev server never picked up an unrelated same-session edit to `dashboard/aggregates.py` at all — no `WatchFiles detected changes` log line ever appeared for that file, unlike every other edit in the session. Best guess: the edit landed inside the debounce window of a reload already in progress for a different file and was silently dropped. This is a new variant of the stale-dev-server problem already documented in `phase3_status`/`dev_server_gotchas` memory (orphaned child processes, ghost sockets) — this time the reloader's file watcher itself missed an edit with no orphaned process involved at all. **Generalizable lesson:** don't trust a missing crash/error as proof a `--reload` server has the latest code — after any edit, check the log for an explicit `WatchFiles detected changes in '<file>'. Reloading...` line naming *that exact file*; if it's absent, kill the whole process tree (`Get-CimInstance Win32_Process -Filter "Name = 'python.exe'"` to find every PID in the tree, not just the one the launcher reports) and start fresh rather than trusting the reloader.

**Root cause, layer 2 (a real, separate bug, only visible once layer 1 was fixed):** `get_category_transactions` is built on `category_transactions()`, which is specifically "the drill-down behind `category_breakdown`'s spending total" (§2/original design). Once `lld_phase2_claude.md` §12 generalized the spending-exclusion filter to cover `"Credit Card Payment"` as well as `"Transfers"`, asking the chatbot about either of those two categories by name always returned `[]` — correct given `category_transactions`'s contract (no spending total exists for a non-spending category to drill into), but not what a user asking "what were my credit card payments" wants.

**Fix:** a new `non_spending_category_transactions()` in `aggregates.py` — a direct lookup by category + month, no spending-exclusion filter, showing both directions of money movement (not just the expense side `category_transactions` shows). `chat/tools.py::dispatch_tool_call` routes `get_category_transactions` to this function specifically when `category_name` is `"Transfers"` or `"Credit Card Payment"`; every other category's behavior is unchanged.

**Verification (both layers, both tool call and prose, per this project's verification skill):**
- Before any fix: tool call returned 3 of the true 10 June credit-card-payment transactions (the stale server was still running pre-`Credit Card Payment` logic, which only excluded `is_transfer=True` rows tagged `"Transfers"` — an artifact of layer 1, not layer 2).
- After the server restart (layer 1 fixed) but before the routing fix (layer 2 still present): tool call correctly, but unhelpfully, returned `[]`.
- After both fixes: tool call returned all 10, matching an independent raw-SQL count exactly (same dates, descriptions, and cents amounts). The model's prose also correctly converted every one of the 10 cents amounts to dollars — no transcription errors this time (contrast §6's residual limitation, which is about narration density, not this bug).
- Regression check: the same live query for a normal category ("dining in June") still worked correctly at the tool-call layer (41 transactions, $1,579.68, independently SQL-verified exact match) — but its **prose** reported $1,983.05, a number matching neither the tool's own total nor any other tool call in that response. This is the already-documented §6 residual narration-fidelity limitation recurring, not a regression from this session's changes; noted here for completeness since it surfaced during this same verification pass, not newly introduced or newly fixed.

Regression tests added: `test_dispatch_get_category_transactions_for_credit_card_payment_bypasses_spending_exclusion`, `test_dispatch_get_category_transactions_dining_still_excludes_transfers` (`test_chat.py`); `test_non_spending_category_transactions_includes_both_directions`, `test_non_spending_category_transactions_scoped_by_account` (`test_dashboard.py`). Full suite: 128/128.

## 10. 2026-07-28, later still — "all months" questions could silently truncate

**User-reported symptom:** asked the chatbot about Auto Loan payments (a category spanning all 7 months of the current data, `lld_phase2_claude.md` §13) "across all months," the answer didn't include all of them.

**Root cause:** `get_category_transactions` required a single `month`, so a question spanning multiple months forced the model to call it once per month — 7 calls for 7 months. The tool-calling loop's round cap (`MAX_TOOL_ROUNDS = 5`, §1) allows **multiple** tool calls within a single round (the model can request a batch in one completion, and `answer_question`'s inner loop executes all of them before the next round) — but nothing forces the model to batch them that way. If it serializes one month per round instead, 7 months needs 7 rounds, exceeding the cap, and the loop returns whatever partial answer it has. This is non-deterministic: it depends entirely on whether the model happens to batch multiple months into one round. A live retry of the identical question actually succeeded once (the model batched all 7 into fewer rounds) before the real fix was made — proving the bug is about *reliability*, not "it's always broken."

**Fix:** rather than raising the round cap (a number that would need to keep growing as more months of transaction history accumulate — not a real fix, just a bigger version of the same latent gap), made `month` optional. `category_transactions()` and `non_spending_category_transactions()` (`dashboard/aggregates.py`) now accept `month: str | None`; omitting it returns every matching transaction across all time in a single call. The tool schema's description now explicitly tells the model to omit `month` whenever a question spans multiple months rather than looping.

**Verification:** live-reprodued the failure isn't possible on demand (non-deterministic by nature), so verification instead confirms the fix removes the *mechanism* entirely: a live query asking for "every single Auto Loan payment across all months, do not limit to one month" produced exactly **one** tool call with no `month` argument, returning all 7 payments correctly — deterministic now, not a matter of the model getting lucky with batching. 3 new regression tests (`test_dispatch_get_category_transactions_all_months_when_month_omitted` in `test_chat.py`; `test_category_transactions_all_time_when_month_omitted`, `test_non_spending_category_transactions_all_time_when_month_omitted` in `test_dashboard.py`). Full suite: 132/132.

The dashboard's own drill-down endpoint (`GET /dashboard/categories/transactions`, `routers/dashboard.py`) still requires `month` — unchanged, since the frontend's category drill-down UI is always scoped to one clicked month. Only the chat tool's schema makes `month` optional; the underlying functions merely gained the *capability*, which the dashboard router simply doesn't use.

## 11. 2026-07-30 — `get_merchant_transactions` (merchant-name search gap)

**Built and verified 2026-07-30.**

**User-reported symptom:** asked the chatbot "How much did I move to Vanguard for the past 6 months?" It answered $8,500 — the correct number — but investigating *how* it got there surfaced two real problems, not visible from the correct-looking answer alone:

1. **The LLM did the arithmetic itself.** No existing tool returns a merchant-scoped total. The model called `get_category_transactions("Interest & Investments")`, got back 8 raw rows (mixed with unrelated interest-income rows from other accounts, coincidentally none matching "Vanguard" in this data), and summed the 8 Vanguard ones in its own prose. This is exactly the arithmetic §1/the system prompt says the model must never do — it happened to add correctly this time, but nothing enforces that.
2. **"Past 6 months" was never actually applied.** The model passed `month: null` (all-time), not a 6-month window — there's no tool parameter for a trailing-N-month restriction scoped to a merchant. The answer only looked right because this database's transaction history happens to start in January, so "all time" and "the last 6-7 months" are the same set of rows right now. With older history, this same question would silently over-count.

**Fix:** a new tool, `get_merchant_transactions`, backed by a new `dashboard/aggregates.py::merchant_transactions`:

- `merchant_search: str` (required) — case-insensitive substring match against `clean_description or description`, the same matching rule already used by the Transactions page's own Merchant filter (`App.tsx`'s `merchantSearchLower` logic) — one matching convention, not a second one invented for chat.
- `months: int | None` — trailing N months (e.g. 6), mirroring `get_monthly_summary`/`get_category_trends`'s existing trailing-window convention; omit/null for all-time, mirroring `get_category_transactions`'s existing all-time convention (§10).
- `account_id: int | None` — same optional scoping every other tool already has.

Unlike `category_transactions`, this does **not** filter through `_load_real_transactions` (which excludes `is_transfer` rows and `NON_SPENDING_CATEGORY_NAMES`). A merchant/payee search is about a real-world counterparty — "how much went to Vanguard" — not a spending-category total, so it should include the money whether or not it happens to be flagged as an internal transfer.

`dispatch_tool_call` returns a dict, not a bare list: `{"total_cents": ..., "transaction_count": ..., "transactions": [{"date", "description", "amount_cents"}, ...]}`. `total_cents` is summed in backend code before the model ever sees it — this is the actual fix for problem 1, not just a prompt reminder. `_cents_to_dollars` (already generic/recursive) converts both `total_cents` and every row's `amount_cents` with no special-casing needed.

Frontend: a new `ToolResultTable` case in `Chat.tsx` for `get_merchant_transactions` — a total/count caption line plus a `MiniTable` of the matching transactions, matching the existing per-tool rendering pattern.

**Tests added:** 7 in `test_dashboard.py` (substring match against both `description` and `clean_description`, trailing-months scoping, all-time when `months` omitted, inclusion of `is_transfer` rows — the one deliberate behavioral difference from `category_transactions` — account scoping, empty-data case), 2 in `test_chat.py` dispatch (`total_cents`/`transaction_count` computed correctly, trailing-months respected), 1 orchestration test asserting the tool result already contains the total before the model ever narrates it. Full suite: 157/157. tsc/oxlint/vitest clean.

**Live verification:** re-asked the exact reported question ("How much did I move to Vanguard for the past 6 months?") against the live server. Before the fix: $8,500 across 8 transactions, `month: null` (all-time), the model's own arithmetic. After the fix: the model called `get_merchant_transactions({merchant_search: "Vanguard", months: 6})` and reported **$8,000 across 7 transactions** — independently confirmed via raw SQL (`WHERE description LIKE '%vanguard%' AND date >= '2026-02-01'` → 7 rows, sum -800000 cents, exact match). The excluded 8th transaction (2026-01-05, outside the trailing 6-month window) proves the date scoping is now real, not coincidental. Repeated in the actual Chat UI: the sidebar-rendered reply, caption line ("-$8,000.00 across 7 transactions"), and transaction table all matched. The backend dev server needed a full restart mid-session — a `--reload` cycle logged picking up `aggregates.py` but never logged a corresponding line for `tools.py`, so per [[dev_server_gotchas]] it was not trusted; killed and restarted fresh before testing. Test conversations created during verification were deleted from `finance.db` afterward — careful to leave two other conversations untouched that were created in the same time window but didn't match any message this session actually sent (apparently the user's own concurrent testing in a separate browser tab).
