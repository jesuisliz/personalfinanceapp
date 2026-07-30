# LLD: UI Polish Pass 2 (remaining cosmetic backlog)

Continuation of the 2026-07-30 cosmetic-only pass (see `ui_dark_theme` memory / `ui_polish_backlog` memory). Covers the four items left from the original layout review. No new features, no data model changes.

## 1. Card hierarchy

**Problem:** `Card` (in `ui.tsx`) is one flat style (`bg-surface border border-hairline rounded-2xl p-4`) used for everything — `StatTile` (headline numbers: income/expense/net/savings rate, current balance, runway) and supporting content (charts, ranked lists, transaction tables) look identical. Nothing tells the eye "this number is the point, this is supporting detail."

**Fix:** Add a `variant` prop to `Card` (`"default" | "elevated"`, default unchanged). `StatTile` switches to `variant="elevated"`:
- `elevated`: `border-hairline-strong` (vs `border-hairline`) + a subtle drop shadow (`shadow-[0_8px_24px_-16px_rgba(0,0,0,0.6)]`) so stat tiles sit slightly forward of the page.
- `StatTile`'s value text bumps from `text-2xl` to `text-3xl` — the number itself becomes the most prominent text on any tab.

Single change point (`ui.tsx`) — every tab that already uses `StatTile` (Dashboard, Planning) picks this up automatically, no per-tab edits needed.

## 2. Layout width

**Problem:** `App.tsx`'s outer wrapper is `max-w-5xl mx-auto p-6` for every tab. Dashboard's 2-column chart/list grids and the Transactions table are data-dense and cramped at ~1024px; Chat and Planning already self-constrain narrower (`max-w-5xl` and `max-w-3xl` respectively) for reading comfort.

**Fix:** Widen the outer container to `max-w-7xl`. Because Chat (`max-w-5xl`) and Planning (`max-w-3xl`) already wrap their own content in a narrower cap, they're visually unaffected — only Dashboard and Transactions (which have no inner cap) actually gain the extra width. This is a one-line change with no side effects on the two tabs that don't need it.

## 3. Custom category dropdown

**Problem:** The per-row category picker in the Transactions table is a native `<select>` with a color dot placed *beside* it (`App.tsx` ~line 481-501) — the dot can't live inside the closed control or next to each option, since native `<option>` elements can't render arbitrary markup.

**Fix:** New `CategoryDropdown` component (`frontend/src/CategoryDropdown.tsx`), dependency-free (plain button + absolutely-positioned panel, matching this app's no-icon-library/no-headless-ui convention):
- Closed state: a button styled like `inputClass`, showing the selected category's dot + name (or "Uncategorized" and no dot), with a small chevron.
- Open state: a bordered panel listing "Uncategorized" plus every category, each row showing its dot + name; click selects and closes.
- Closes on outside click or Escape. No keyboard arrow-navigation (native `<select>` has this for free; a custom one doesn't get it without real work) — this is the one real regression versus the native control, worth being upfront about. Typing to jump to an option is also lost. Given this list is ~20 categories and used for mouse-driven point edits in a table, I think that trade-off is acceptable, but flagging it since it's a genuine capability loss, not just a style change.
- Adds one new icon (`IconChevronDown`) to `icons.tsx`, following the existing inline-SVG pattern.
- Replaces the native `<select>` + separate dot `<span>` block in the Transactions table only. The Transactions *filter bar*'s category `<select>` (top of the tab) has no dot today and is out of scope — it's a different control (a filter, not a per-row edit) and adding dots there wasn't part of the original backlog note.
- `handleCategoryChange` signature changes from `(txnId, value: string)` to `(txnId, categoryId: number | null)` — cleaner now that the caller has a real value instead of a stringified `<select>` value, and it's the only call site.

## 4. Dashboard account filter icon

**Problem:** Dashboard's Account filter uses a text label (`<span>Account</span>`) instead of the icon-only convention adopted for the Transactions filter bar (`IconBank` + no label, since the select's own default option already says "All accounts").

**Fix:** Apply the same treatment: drop the text label, prefix `IconBank`. Scope note — Dashboard also has a **Month** select styled identically (text label + select) right above the category/merchant cards. Since the backlog note only called out "Account," but leaving Month as text-label-only while Account goes icon-only would look inconsistent on the same tab, I'd fold Month into this too (`IconCalendar`, no label) — same one-line-per-filter change, same justification (the select already states "All months"). Flagging this as a small scope addition rather than assuming it's wanted.

## Order of implementation

Independent changes, no ordering dependency. Will do 1 → 2 → 4 → 3 (simplest/lowest-risk first, custom dropdown last since it's the only genuinely new component). Each gets: implement → `tsc -b` + oxlint + vitest → live browser verify → update `ui_dark_theme` memory → git commit — one commit per item, not one giant commit.
