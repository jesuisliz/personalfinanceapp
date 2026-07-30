# LLD: Chat Empty State

Status: proposed, awaiting approval
Scope: Chat tab only, frontend-only, no backend/API changes, no new dependencies

## Current problem (`Chat.tsx:325-332`)

When there's no conversation loaded (first visit, or after clicking "New
Conversation"), the message pane renders one line of muted text
top-left inside a `min-h-[300px]` card — the rest of the box is empty
black space with nothing to look at or do. This is the same "unfinished
screen" issue flagged for the filter bar, just on Chat.

## Proposed change

Replace the single line of text with a centered empty state:

- `IconMessageCircle` (already exists in `icons.tsx`, just used at a
  larger size here) as a visual anchor, muted color.
- Short heading ("Ask about your spending") + the existing explanatory
  line, both centered.
- **Suggested-question chips** — small clickable buttons using the four
  example questions already written into `CLAUDE.md`'s Phase 4 roadmap
  ("Where is my money going?", "How much did I spend eating out?",
  "What categories increased?", "How much could I save by reducing
  dining?") rather than inventing new copy. Clicking one fills the
  input with that question and focuses it — it does **not** auto-send,
  so you still get to review/edit before it hits the chat backend.

Layout mechanics: the message `Card` becomes a flex column
(`flex flex-col`) so the empty-state content can be vertically centered
within the existing `min-h-[300px]`, instead of pinned to the top.
The loading state and the populated message list are unaffected in
behavior — just re-flowed to fit the same flex-column container.

## Files touched

- `frontend/src/Chat.tsx` only (new empty-state markup, a small
  `handleSuggestedQuestion` helper, an input ref for focus-on-click)

No new files, no changes to `App.tsx`, `Dashboard.tsx`, `Planning.tsx`,
`icons.tsx`, or any backend file.
