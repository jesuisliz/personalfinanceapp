# LLD: Transactions Filter Bar Redesign

Status: proposed, awaiting approval
Scope: Transactions tab only, frontend-only, no backend/API changes, no new dependencies

## Current problems (`App.tsx:273-378`)

Everything — 6 filter controls, a checkbox, and 3 unrelated data actions
(Import CSV, Detect Transfers, Export CSV) — lives in one `flex-wrap` row.
Specific issues:

1. **Filters and actions are mixed together.** Import/Detect/Export aren't
   filters, but they wrap into the same line as "Month" and "Amount",
   so the row reads as one long undifferentiated list of controls.
2. **Every control has a redundant text label** (`Account`, `Category`,
   `Month`) even though the select's own default option already says
   "All accounts" / "All categories" / "All months" — the label repeats
   what the control already shows.
3. **The amount-range hint breaks the row's rhythm.** The italic
   "expenses are negative" text next to Min/Max adds variable-width text
   into a control row, so wrapping is unpredictable depending on window width.
4. **No way to clear filters at once.** With Account + Category + Month +
   Merchant + Amount all set, resetting means touching five separate
   controls one at a time.

## Proposed structure

Split into two visually distinct rows:

**Row 1 — filter bar**, wrapped in a subtle bounded container
(`bg-surface-2/50 border border-hairline rounded-xl px-3 py-2`) so it reads
as one toolbar, not loose controls floating on the page:

- Account, Category, Month selects: drop the standalone text label,
  add a small leading icon instead (same inline-SVG pattern as
  `icons.tsx`) — icon communicates the field at a glance without
  spending horizontal space on a label that duplicates the select's
  own "All ___" text.
- Merchant search: drop the label, keep the existing placeholder,
  add a leading search icon.
- Amount range: keep Min/Max placeholders as-is; replace the inline
  italic hint text with a small info icon that shows the same
  explanation via `title` on hover — keeps the row's width stable
  instead of an always-visible text fragment.
- Uncategorized-only checkbox: unchanged (a checkbox needs its label).
- **New: "Clear filters" button**, right-aligned, only rendered when at
  least one filter is active (account/category/month/merchant/amount/
  uncategorized-only ≠ default). Resets all six pieces of filter state
  in one click. This is a small functional addition, not purely cosmetic
  — flagging it separately in case you'd rather hold it for a different
  pass, but it's a natural fit for the same edit.

**Row 2 — actions bar**, directly below, visually separated (its own
`mb-4`, no shared container with the filters): Import CSV, Detect
Transfers, Export CSV, and the `uploadStatus` message — unchanged from
today except now grouped on their own line instead of trailing off the
filter row.

## New icons needed

Five additions to `frontend/src/icons.tsx`, same style as the existing set
(`viewBox 0 0 16 16`, stroke `currentColor`, size 14):

| Icon | Used for |
|---|---|
| `IconBank` | Account select |
| `IconTag` | Category select |
| `IconCalendar` | Month select |
| `IconSearch` | Merchant input |
| `IconInfo` | Amount-sign hint (replaces the inline italic text) |

## Out of scope for this pass

- Dashboard's Account selector (`Dashboard.tsx:184-199`) is a single
  control, not a cluttered row — left as-is. Could pick up the same
  icon-instead-of-label treatment later for visual consistency if wanted.
- No new filter types, no multi-select, no filter chips/tags UI.
- No change to how filtering logic works (`visibleTransactions` in
  `App.tsx:166-175`) — this is a layout/grouping change only, aside from
  the new Clear-filters button which calls the existing setters.

## Files touched

- `frontend/src/icons.tsx` (5 new icon components)
- `frontend/src/App.tsx` (filter bar markup restructured into two rows,
  Clear-filters button added)

No changes to `Dashboard.tsx`, `Chat.tsx`, `Planning.tsx`, or any backend file.
