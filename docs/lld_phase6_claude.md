# Low-Level Design — Personal Finance App (Phase 6: Chat History Persistence)

**Status: M1 and M2 built and verified (2026-07-30). M3-M5 designed, not yet built.**

Companion to `hld_claude.md` and `lld_phase4_claude.md` (the chatbot this phase extends). Not an original `CLAUDE.md` roadmap item — a user-requested evolution of Phase 4: "I kinda like how my experience is with ChatGPT or Claude chat — keeping history." Today, chat history is in-memory only (`frontend/src/Chat.tsx` React state, resent each turn, no DB table) — a deliberate Phase 4 scope-down, not an oversight. This phase makes it persistent, with multiple named, browsable, switchable conversations, the way ChatGPT/Claude's own UI works.

## 1. Architecture

Unlike most of this app's calculation-heavy phases, this feature computes nothing new — it's pure persisted UI/conversation state layered on top of the existing Phase 4 tool-calling loop (`app/chat/service.py::answer_question`, `app/chat/tools.py`). None of it touches financial data or "never guess" concerns; the only design questions are data-model shape and how much UI to build before shipping.

Key decisions, confirmed with the user before writing this doc (each via `AskUserQuestion`, each the recommended default):

1. **Schema designed for the full end state now, shipped incrementally.** Both tables below (`ChatConversation`, `ChatMessage`) exist starting at Milestone 1, even though multi-conversation browsing doesn't land in the UI until Milestone 3. Avoids migrating the schema twice — this app already did that once for `CategoryRule.account_id` (`lld_phase2_claude.md` §12) and it required a SQLite table rebuild; better to get the shape right up front here since there's no legacy data to migrate around yet.
2. **`tool_calls` persists with each assistant message**, not just the prose reply. Reopening a past conversation must still show the supporting data table under each answer — that's Phase 4's core "every number visible, not just asserted" principle (`lld_phase4_claude.md` §1), and it would be undermined if history-reload only restored text.
3. **Conversation titles are the first user message, truncated.** No LLM call to generate a title — consistent with this project's standing rule never to use the model for something code can do directly.
4. **Delete is a hard delete.** No `is_deleted`/archive flag. This is single-user local data; a client-side confirmation step is the safeguard, not a recovery mechanism.

## 2. Data Model (full end-state schema, present from Milestone 1)

```python
class ChatConversation(Base):
    __tablename__ = "chat_conversations"
    id: int (PK)
    title: str                      # first user message, truncated to ~60 chars
    created_at: datetime
    updated_at: datetime            # bumped on every new message; drives list ordering

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: int (PK)
    conversation_id: int (FK chat_conversations.id, indexed)
    role: str                       # "user" | "assistant"
    content: str
    tool_calls_json: str | None     # JSON-encoded list[ToolCallOut], null for user messages
    created_at: datetime
```

No foreign key from `ChatMessage` back into financial tables (`transactions`, `categories`, etc.) — a persisted chat message is a historical record of what was asked and answered at the time; it must **not** update if the underlying transaction data changes later (e.g. a category gets renamed after the fact). This mirrors how `clean_description`/`category_id` overrides on `Transaction` already work: persisted state is a snapshot, not a live view.

`ChatMessage.conversation_id` cascades on delete (Milestone 5) — deleting a conversation deletes its messages, enforced at the ORM/DB level (`ondelete="CASCADE"`), not by the router remembering to clean up manually.

## 3. Backend (introduced across milestones, detailed per-milestone in §5)

`backend/app/chat/history.py` (new module, mirrors the existing `<domain>/aggregates.py` + `routers/<domain>.py` split already used by every other feature):
- `create_conversation(session, first_message) -> ChatConversation`
- `append_message(session, conversation_id, role, content, tool_calls=None) -> ChatMessage`
- `list_conversations(session) -> list[ChatConversation]` — ordered by `updated_at` desc
- `get_conversation_messages(session, conversation_id) -> list[ChatMessage]` — ordered by `created_at` asc
- `rename_conversation(session, conversation_id, title) -> ChatConversation`
- `delete_conversation(session, conversation_id) -> None`

`answer_question` (existing, Phase 4) gains one new optional parameter: `conversation_id: int | None`. When `None`, a new conversation is created from the incoming message before the tool-calling loop runs; the resulting `conversation_id` is returned to the caller so the router can include it in the HTTP response. `answer_question`'s own tool-calling logic is otherwise untouched — persistence wraps it, it doesn't thread through it.

## 4. API

| Endpoint | Behavior | Introduced |
|---|---|---|
| `POST /chat` | unchanged shape, plus optional `conversation_id` in the request and always-present `conversation_id` in the response | M1 |
| `GET /chat/conversations/{id}/messages` | full message history for one conversation, in order, each with its `tool_calls` | M2 |
| `GET /chat/conversations` | list all conversations: `{id, title, updated_at}`, sorted by `updated_at` desc | M3 |
| `PATCH /chat/conversations/{id}` | `{title}` — rename | M4 |
| `DELETE /chat/conversations/{id}` | hard delete, cascades to its messages | M5 |

## 5. Milestones

Each milestone is independently shippable, independently testable, and depends only on the previous one — per the user's usual "one milestone at a time, approve before continuing" build style.

### M1 — Backend persistence, no visible UI change

Every chat turn gets written to the database, but the frontend behaves exactly as it does today (page refresh still starts a blank chat). This is deliberately invisible — it proves the persistence layer works before any UI depends on it.

- **Data model**: both tables created (§2).
- **API**: `POST /chat` accepts optional `conversation_id`; response always includes one (newly created if none was passed). Internally: persist the user's message, run the existing tool-calling loop unchanged, persist the assistant's reply + its `tool_calls`.
- **Frontend**: `Chat.tsx` starts passing back the `conversation_id` it received on the *next* request in the same browser session (an in-memory variable, not yet `localStorage`) — purely so multi-turn conversations land in one `ChatConversation` row instead of a new one per message. No visible change.
- **Acceptance test**: backend test asserting a `POST /chat` call creates exactly one `ChatConversation` + 2 `ChatMessage` rows (user + assistant); a second call with the same `conversation_id` appends to the same conversation instead of creating a new one; a live check querying `finance.db` directly after a real browser exchange confirms the rows exist with the correct `tool_calls_json`.

**Built and verified 2026-07-30.** 4 new backend tests (140 total passing), tsc/oxlint/vitest clean. Live-verified two ways: (1) direct `curl` calls to `POST /chat`, first without `conversation_id` then with the returned id, confirmed via raw `sqlite3` query against `finance.db` that both turns landed in one `ChatConversation` row with correct `tool_calls_json` on a tool-triggering question; (2) real browser exchange in the Chat tab (two turns, second one referencing the first by name) independently confirmed via the same raw-SQL check. `history.py` M1 scope only implements `create_conversation`/`append_message` — `list_conversations`/`get_conversation_messages`/`rename_conversation`/`delete_conversation` are deferred to M2-M5 rather than stubbed out now. Test rows deleted from `finance.db` after verification. Backend dev server was restarted (not trusted to `--reload`, per [[dev_server_gotchas]]) before live verification, since the new tables and `chat/history.py` module predated the running process.

### M2 — Resume on page load (single continuous history)

Refreshing the page no longer loses your conversation.

- **API**: `GET /chat/conversations/{id}/messages`.
- **Frontend**: on mount, `Chat.tsx` checks `localStorage` for a saved `conversation_id`; if present, fetches and renders its full history (prose + tool-call tables) before allowing new input; if absent (first-ever visit), starts empty exactly as today. Every new message updates the `localStorage` pointer.
- **Acceptance test**: send 2-3 messages, refresh the browser tab, confirm all prior messages and their tool-call tables reappear in order; a brand-new browser profile (no `localStorage` entry) still gets a clean empty chat with no error.

**Built and verified 2026-07-30.** Added `history.get_conversation_messages` and `GET /chat/conversations/{id}/messages` (404 if the id doesn't exist), plus a `ChatMessageOut` schema. `Chat.tsx` reads a `chat_conversation_id` `localStorage` key on mount; if present, fetches and renders the full history (disabling input with a "Loading conversation..." state until it resolves) before allowing new input; a fetch failure (e.g. a stale id pointing at a deleted conversation) clears the `localStorage` key and falls back to an empty chat rather than surfacing an error. 2 new backend tests (142 total), tsc/oxlint/vitest clean. Live-verified in the browser: sent 2 messages, navigated away and back (a full remount), and the same 2 exchanges reappeared in order with no console errors -- independently confirmed via raw SQL that the reloaded conversation's rows matched exactly. The very first navigation of the session (no `localStorage` entry yet) also confirmed the plain empty-state path still works unchanged. Test rows deleted from `finance.db` afterward.

### M3 — Conversation list + explicit "New Conversation"

The ChatGPT-style browsing experience: see past conversations, switch between them, start a new one on purpose.

- **API**: `GET /chat/conversations`.
- **Frontend**: a conversation list (sidebar or dropdown, matching this app's existing plain-Tailwind style, no new UI library) showing title + relative last-updated time; clicking one loads it via M2's endpoint and updates the `localStorage` pointer; a "New Conversation" button clears the active thread and the pointer, so the *next* message naturally starts a fresh `ChatConversation` via M1's existing "no `conversation_id` passed" path — no new create endpoint needed.
- **Acceptance test**: have 2+ conversations from real use; confirm the list shows both with correct titles and ordering (most recently active first); switching loads the right messages; clicking "New" and sending a message creates a third, distinct conversation rather than appending to whichever was last open.

### M4 — Rename a conversation

- **API**: `PATCH /chat/conversations/{id}`.
- **Frontend**: inline click-to-edit title in the list, reusing the exact pattern already used for transaction descriptions/notes in `App.tsx` (click text → input → save on blur/Enter, Escape to cancel) rather than inventing a new editing convention.
- **Acceptance test**: rename persists across a page reload; submitting a blank title is rejected client-side and reverts to the previous title (never silently saved as empty).

### M5 — Delete a conversation

- **API**: `DELETE /chat/conversations/{id}`.
- **Frontend**: a delete affordance per conversation in the list, gated behind a confirmation step (a native `confirm()` or an inline "are you sure" toggle — not a silent one-click delete, since this is a hard delete with no undo per §1's design decision).
- **Acceptance test**: deleting removes the conversation from the list and its messages from the database (verified via direct query, not just "it disappeared from the UI"); deleting the currently-open conversation clears the active view back to empty/New rather than showing a broken reference to a conversation that no longer exists.

## 6. Explicit Non-Goals (this phase)

- No cross-device sync — this is a local-only app (per `PROJECT_CONTEXT.md`'s Privacy section); history lives in the same local `finance.db` as everything else.
- No LLM-generated conversation titles (§1, decision 3) — first-message truncation only.
- No conversation search/full-text search across history.
- No soft-delete/archive/undo (§1, decision 4).
- No export (PDF/markdown/etc.) of a conversation.
- No sharing a conversation between multiple "users" — this app has no multi-user concept (`hld_claude.md` §7's existing non-goal already covers this).

## 7. Open Questions

- Should very old conversations ever be pruned/archived automatically (e.g. after a year)? Not addressed here — revisit only if local DB size actually becomes a practical concern; premature to design a retention policy before there's any evidence it's needed.
- Should the message list ever be paginated for a very long-running single conversation? Deferred until real usage shows it matters — this app's transaction table already handles its full dataset without pagination at current scale, and chat history is likely to be smaller.
