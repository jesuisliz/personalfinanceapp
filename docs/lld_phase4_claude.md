# Low-Level Design — Personal Finance App (Phase 4: Financial Chatbot)

**Status: built and unit-verified as of 2026-07-27; live validation with real questions deferred until a real `OPENAI_API_KEY` is added to `backend/.env`.**

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
| `get_category_transactions` | `category_transactions` | The individual transactions behind one category's total in one month |
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

**Deferred until a real `OPENAI_API_KEY` is added** (per user's explicit choice not to configure one yet):
- Each of CLAUDE.md's four example questions answered correctly through the live Chat tab, routed to the right tool(s) with the right arguments.
- Independent raw-SQL cross-check (bypassing all app code, same discipline as `feedback_independent_verification`) of at least one live answer per tool.
- Confirming every numeric claim in a real model reply traces to a tool result the user can see alongside it.

These are the actual next steps once a key is available — not forgotten, just correctly sequenced behind having something to test against.

## 7. Explicit Non-Goals (this phase)

- No persisted chat history / no new DB table (§4).
- No AI-assisted merchant categorization — CLAUDE.md's AI section mentions this as a future possibility, but it isn't a Phase 4 roadmap bullet and was already explicitly deferred in Phase 2 (§10 of `lld_phase2_claude.md`).
- No streaming responses — synchronous request/response is sufficient for this question set and simpler to implement and test.

## 8. Gotcha Encountered During This Phase (environment, not code)

Verifying the missing-API-key path live took much longer than it should have because of a genuinely orphaned `uvicorn --reload` process from earlier in the day: its **parent** process was invisible to `Get-Process`/`taskkill` (already gone), but a **child worker it had spawned** was still alive and still bound to port 8000, silently serving stale code (missing the new `/chat` route) underneath every newly-started server. Windows' own port-ownership tools (`netstat`, `Get-NetTCPConnection`) kept attributing the port to the dead parent PID, which was misleading. The fix was enumerating the full process tree (`Get-CimInstance Win32_Process ... | Select ProcessId, ParentProcessId, CommandLine`) to find the actual live child and kill it directly. Generalizable lesson: if a freshly-restarted dev server doesn't reflect a code change, don't assume the file watcher is the culprit — check for orphaned child processes still holding the port, not just the PID the launcher tool reports.
