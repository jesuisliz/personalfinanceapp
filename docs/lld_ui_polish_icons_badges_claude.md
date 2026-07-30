# LLD: UI Polish — Icons + Category Color Badges

Status: proposed, awaiting approval
Scope: cosmetic only, frontend-only, no backend/API changes, no new dependencies

## Why this pass, and why first

From a live review of all four tabs (2026-07-30), the two changes with the best
"looks modern" payoff for the least effort are: the app has zero iconography
(every action is a text label), and the transactions table has no visual
scanning aid for category — you have to read every row's dropdown text. Both
are additive, low-risk, and don't touch data or layout structure, which makes
them a safe first milestone before anything structural (filter bar redesign,
Chat empty state, layout width).

## Part 1 — Icon set

**Approach:** inline SVG components, same pattern already used for the M5
delete-conversation trash icon (`Chat.tsx:312-314`) — no icon library added,
keeps the app dependency-free. New file `frontend/src/icons.tsx` exporting
small function components (`IconUpload`, `IconTransfer`, `IconDownload`, etc.),
16x16 default, `stroke="currentColor"`, so each icon inherits whatever text
color its container already uses (`text-ink-secondary`, `text-canvas` on
filled buttons, etc.) — no separate color wiring needed.

**Where icons get added (label text stays — icon is a prefix, not a replacement):**

| Location | Icon | File |
|---|---|---|
| Nav tab: Transactions | list | `App.tsx` TABS |
| Nav tab: Dashboard | bar-chart | `App.tsx` TABS |
| Nav tab: Chat | message-circle | `App.tsx` TABS |
| Nav tab: Planning | compass | `App.tsx` TABS |
| "Import CSV" button | upload | `App.tsx` |
| "Detect Transfers" button | arrows swapping | `App.tsx` |
| "Export CSV" button | download | `App.tsx` |
| Transfer review "Confirm" | check | `App.tsx` |
| Transfer review "Reject" | x | `App.tsx` |
| Chat "New Conversation" | plus | `Chat.tsx` |
| Chat "Send" | paper-plane / arrow-up | `Chat.tsx` |

Nothing in Dashboard or Planning changes in this part — those tabs don't have
action buttons that need icons yet.

## Part 2 — Category color badges

**Problem:** in the Transactions table, category is a plain native `<select>`
with text only. Finding "all my Dining transactions" visually means reading
every row.

**Approach:** a small colored dot rendered next to the category `<select>`,
not inside it — native `<option>` elements can't reliably render a colored
dot cross-browser, so a full custom dropdown component is out of scope for
this pass (noted below as a possible future upgrade).

**Color assignment — deterministic hash, not stored data:** no DB/schema
change. A new `frontend/src/categoryColor.ts` maps `category.id` to one of a
fixed set of ~10 curated muted swatches via a simple hash (`id % swatches.length`),
so a given category always renders the same dot color across the session
without persisting anything.

**Important distinction from the dataviz color rules:** [[ui_dark_theme]] /
the dataviz skill treats chart series colors as categorical data-identity and
requires running them through the CVD-separation validator before use. These
category dots are *not* a chart series — they're a UI wayfinding label, the
same role the violet accent color already plays (chrome-only, exempt from the
categorical gate). So the 10 swatches are chosen to be visually distinct from
each other and from the reserved semantic colors (income/expense/good/critical/accent),
but are **not** run through `validate_palette.js` and must never be reused as
an actual chart series color. If category-colored *charts* are wanted later
(e.g. a pie/donut by category), that's a separate piece of work that does need
the validator.

**Where the dot appears:** only the Transactions table category cell. The
Dashboard "Spending by category" bar list keeps its current single-hue
sequential blue — that encodes magnitude/ranking, which is the correct
convention per [[ui_dark_theme]], and mixing in per-category identity colors
there would undo that.

## Out of scope for this pass (noted for later)

- Custom dropdown component for category (would allow the color dot to live
  inside the picker itself, not just beside it)
- Filter bar redesign, Chat empty state, layout width changes — separate
  milestones per the earlier review
- Any change to chart colors/scaling (including the tiny-bars axis issue
  flagged separately)

## Files touched

- `frontend/src/icons.tsx` (new)
- `frontend/src/categoryColor.ts` (new)
- `frontend/src/App.tsx` (nav tabs, toolbar buttons, transfer review buttons, category cell)
- `frontend/src/Chat.tsx` (new-conversation button, send button, shared nav icons)
- `frontend/src/ui.tsx` (optional: small `CategoryDot` primitive if it keeps call sites cleaner)

No changes to `Dashboard.tsx`, `Planning.tsx`, or any backend file.
