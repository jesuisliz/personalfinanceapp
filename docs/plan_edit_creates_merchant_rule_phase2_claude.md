# Remember Edit as Rule - Phase 2 Implementation Plan (frontend panel)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or subagent-driven-development) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Hard stop after every task (user rule).

**Goal:** After a category edit on the Transactions tab, offer an opt-in panel above the table that previews the merchant rule the edit could become and saves it only when the server-side checks would pass.

**Architecture:** All panel transitions live in a pure reducer `frontend/src/rememberRule.ts` (vitest-tested), like `heldImport.ts`. `RememberRulePanel.tsx` is presentational. `App.tsx` owns the reducer, dispatches `categoryEdited` only after the PATCH resolves, runs a debounced preview effect with a monotonic request counter, and handles Save. Two new API functions call the Phase 1 endpoints; a new `refusalMessage` reads the `{code, message}` error detail.

**Tech Stack:** React 19, TypeScript 6, Vite 8, Tailwind 4, vitest 4. Backend unchanged.

**Spec:** `docs/lld_edit_creates_merchant_rule_claude.md` v3, sections 4.2-4.4 (API contract), 5 (frontend), 8 (frontend verification). Backend as built: `backend/app/routers/merchant_rules.py`.

## Global Constraints

- `categoryEdited` is dispatched **only after** `updateTransaction` resolves; a rejected PATCH dispatches nothing (LLD 5).
- The panel renders above the table, next to `HeldImportPanel`, outside the `loading ?` branch, so `reload()` and active filters cannot unmount it (LLD 5).
- `canSave`: pattern and name non-blank; latest preview is for the current pattern and scope; `matches_source`; no conflict; `category_mismatch_count === 0`; not already saved (LLD 5) - plus not currently saving.
- A save refusal shows the server's `message`. Success shows "Rule saved" and reloads the table (LLD 5).
- No component tests (LLD 6): transitions are proven by reducer tests, placement and wiring by the live walkthrough.
- The backend is the real guard; the client never relaxes a server refusal.
- No backend changes in this phase. No rules management UI; undo is the DELETE endpoint (LLD 6).
- Code style: match `heldImport.ts` / `HeldImportPanel.tsx`; small functions, short docstrings, no emojis, no defensive try/except.

**Decisions this plan adds (record in the LLD, Task 4):**

1. **Two actions beyond the LLD list:** `previewFailed(seq, message)` (preview 409/422/network errors need a state; without it the panel says "Checking..." forever) and `saveStarted` (disables Save while the create is in flight; a double click would otherwise send two creates - the server would refuse the second as a conflict, but with a confusing message).
2. **`saveSucceeded` / `saveFailed` apply only while `saving`.** If the user edits another row mid-save, the new panel isn't stamped "Rule saved" by the old request.
3. **`categoryEdited` with null closes the panel only when it is the panel's own row.** LLD 5 says "null closes"; read literally, setting an unrelated row to Uncategorized would throw away an open panel that is still valid. **Needs Liz's OK** (alternative: follow the LLD literally - one line).
4. **`categoryEdited` for the same row and same category keeps the state as is.** `CategoryDropdown` fires `onChange` even when the same category is re-picked; resetting would discard a typed pattern for no reason.
5. **`name: string | null`** instead of a plain string: null means "not edited", and `displayName` derives the default (`clean_description`, else the current pattern). Without this the default would freeze at whatever the pattern was when the panel opened (empty).
6. **Preview staleness** is guarded three ways: (a) seq - responses apply only if `seq === latestSeq`; the counter lives in App (`useRef`) and is never reset, and a new panel starts at `latestSeq: 0`, so a response for a replaced panel can never match; (b) `canSave` compares `preview.match_pattern` with the trimmed pattern; (c) the state records `previewThisAccountOnly`, the scope the preview was computed for. (b) and (c) cover the window between an edit and the next debounced request, when the old request is still the latest.
7. **Preview requests are debounced 300 ms** and keyed on the request body. While the pattern is untouched the body sends `match_pattern: null` (server suggests), so prefilling the pattern from a response does not trigger a second request. A touched blank pattern sends nothing.
8. **Error detail helper:** `asJson` does `new Error(body.detail ?? ...)`; the Phase 1 refusals return `detail: {code, message}`, which would display as `[object Object]`. New `refusalMessage(body, fallback)` reads `detail` when it is a string, `detail.message` when it is an object, and uses the fallback otherwise (FastAPI's 422 validation detail is an array). Used only by the two new API functions; `asJson` is left alone.
9. **Saved view shows the rule id** and that undo is `DELETE /merchant-rules/{id}`, since there is no UI to find the id later.

## Review Focus

Inputs the spec implies that no single happy-path test exercises:

1. **A late preview response after the panel was replaced** by an edit on another row (or the same row, new category) must not land in the new panel. -> Task 2 test `ignores a response requested before the panel was replaced`.
2. **Pattern edited (or scope toggled) while a request is in flight** - the old response still has the latest seq. Save must stay disabled. -> Task 2 `canSave` cases "preview for another pattern" / "preview for another scope".
3. **Trailing space typed in the pattern** (`"DD *DOORDASH "`): the server strips, so the preview is for the same pattern; Save must stay enabled. -> Task 2 `canSave` true case.
4. **Error body shapes:** `{detail: {code, message}}`, `{detail: "string"}`, and `{detail: [...]}` (FastAPI 422). -> Task 1 tests.
5. **Row disappears under an active filter** after the edit (category filter set to the old category): panel must stay. -> Task 4 live step.

---

## File Structure

- Modify `frontend/src/api.ts` - `RulePreview`, `RuleConflict`, `RuleSampleRow`, `MerchantRule`, `RulePreviewRequest`, `RuleFromEditRequest` types; `refusalMessage`, `previewRule`, `createRuleFromEdit`.
- Modify `frontend/src/api.test.ts` - Task 1 tests.
- Create `frontend/src/rememberRule.ts` - state, actions, `rememberRuleReducer`, `canSave`, `displayName`, `previewRequestBody`, `saveRequest`.
- Create `frontend/src/rememberRule.test.ts` - Task 2 tests.
- Create `frontend/src/RememberRulePanel.tsx` - the panel.
- Modify `frontend/src/App.tsx` - reducer, `handleCategoryChange`, preview effect, `handleSaveRule`, panel placement.
- Modify `docs/lld_edit_creates_merchant_rule_claude.md` - status, section 12 (decisions, results).
- Modify `README.md` - one feature line, if the README lists Transactions-tab features.

Frontend commands run from `frontend/`: `npm test`, `npm run build` (runs `tsc -b`), `npm run lint`. Backend suite (unchanged, regression only): `cd backend && venv/Scripts/python.exe -m pytest -q` (315 expected). Baseline before Task 1: record the vitest count. Work on `main`; commit per task, staging only that task's files. Ledger: `.superpowers/sdd/plan_edit_creates_merchant_rule_phase2_claude/progress.md`.

---

## Task 1: API client for preview and create

**Files:** `frontend/src/api.ts`, `frontend/src/api.test.ts`

**Interfaces - Produces:**

```ts
export interface RuleConflict { id: number; match_pattern: string; clean_name: string; category_id: number | null; account_id: number | null; }
export type MerchantRule = RuleConflict;
export interface RuleSampleRow { id: number; date: string; description: string; category_name: string | null; }
export interface RulePreview {
  match_pattern: string;
  matches_source: boolean;
  conflicting_rule: RuleConflict | null;
  would_name_count: number;
  would_categorize_count: number;
  category_mismatch_count: number;
  sample: RuleSampleRow[];
}
export interface RulePreviewRequest { source_transaction_id: number; match_pattern: string | null; category_id: number; this_account_only: boolean; }
export interface RuleFromEditRequest { source_transaction_id: number; match_pattern: string; clean_name: string; category_id: number; this_account_only: boolean; }
export function refusalMessage(body: unknown, fallback: string): string;
export async function previewRule(request: RulePreviewRequest): Promise<RulePreview>;
export async function createRuleFromEdit(request: RuleFromEditRequest): Promise<MerchantRule>;
```

- [ ] **Step 1: Write failing tests** in `api.test.ts` (reuse `stubFetch` / `requestedUrl`; add a `stubFetchError(status, body)` helper next to them):

```ts
describe("refusalMessage", () => {
  it("reads message from a {code, message} detail", () => {
    expect(refusalMessage({ detail: { code: "conflict", message: "An existing rule already names this transaction" } }, "x"))
      .toBe("An existing rule already names this transaction");
  });
  it("uses a string detail as is", () => {
    expect(refusalMessage({ detail: "Merchant rule 9 not found" }, "x")).toBe("Merchant rule 9 not found");
  });
  it("falls back for FastAPI validation errors (array detail)", () => {
    expect(refusalMessage({ detail: [{ loc: ["body", "match_pattern"], msg: "blank" }] }, "Preview failed")).toBe("Preview failed");
  });
  it("falls back when there is no detail", () => {
    expect(refusalMessage({}, "Preview failed")).toBe("Preview failed");
  });
});

describe("previewRule", () => {
  afterEach(() => vi.unstubAllGlobals());
  const request = { source_transaction_id: 971, match_pattern: null, category_id: 7, this_account_only: false };

  it("posts the request as JSON to /merchant-rules/preview", async () => {
    const fetchMock = stubFetch({ match_pattern: "DD *DOORDASH" });
    await previewRule(request);
    expect(requestedUrl(fetchMock).pathname).toBe("/merchant-rules/preview");
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    expect(fetchMock.mock.calls[0][1].headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual(request);
  });
  it("returns the server's preview", async () => {
    stubFetch({ match_pattern: "DD *DOORDASH", would_name_count: 46 });
    expect(await previewRule(request)).toEqual({ match_pattern: "DD *DOORDASH", would_name_count: 46 });
  });
  it("rejects with the refusal message", async () => {
    stubFetchError(409, { detail: { code: "source_category_changed", message: "This transaction's category changed since the rule was suggested" } });
    await expect(previewRule(request)).rejects.toThrow("This transaction's category changed since the rule was suggested");
  });
});

describe("createRuleFromEdit", () => {
  afterEach(() => vi.unstubAllGlobals());
  const request = { source_transaction_id: 971, match_pattern: "DD *DOORDASH", clean_name: "DoorDash", category_id: 7, this_account_only: true };

  it("posts the request as JSON to /merchant-rules", async () => {
    const fetchMock = stubFetch({ id: 77 });
    await createRuleFromEdit(request);
    expect(requestedUrl(fetchMock).pathname).toBe("/merchant-rules");
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual(request);
  });
  it("returns the saved rule", async () => {
    stubFetch({ id: 77, match_pattern: "DD *DOORDASH" });
    expect(await createRuleFromEdit(request)).toEqual({ id: 77, match_pattern: "DD *DOORDASH" });
  });
  it("rejects with the refusal message, not [object Object]", async () => {
    stubFetchError(409, { detail: { code: "category_mismatch", message: "Some transactions this rule would match are in a different category", count: 30, sample: [] } });
    await expect(createRuleFromEdit(request)).rejects.toThrow("Some transactions this rule would match are in a different category");
  });
});
```

- [ ] **Step 2: Run** `npm test` - the new tests fail (imports missing).
- [ ] **Step 3: Implement** in `api.ts`, after `asJson`:

```ts
/** The text to show for an error response: a string detail, a {code, message} detail's message, else the fallback. */
export function refusalMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") {
    return detail.message;
  }
  return fallback;
}

async function asJsonOrRefusal(res: Response, errorMessage: string) {
  const body = await res.json();
  if (!res.ok) throw new Error(refusalMessage(body, errorMessage));
  return body;
}
```

and the two functions near the other write calls:

```ts
/** What a rule remembered from a category edit would do. Read-only on the server. */
export async function previewRule(request: RulePreviewRequest): Promise<RulePreview> {
  const res = await fetch(`${API_BASE}/merchant-rules/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return asJsonOrRefusal(res, "Rule preview failed");
}

/** Save a rule remembered from a category edit; the server refuses unsafe rules. */
export async function createRuleFromEdit(request: RuleFromEditRequest): Promise<MerchantRule> {
  const res = await fetch(`${API_BASE}/merchant-rules`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return asJsonOrRefusal(res, "Saving the rule failed");
}
```

- [ ] **Step 4: Run** `npm test` (all pass), `npm run build`, `npm run lint`.
- [ ] **Step 5: Mutation check** on a scratch copy of `api.ts` (restore after): (a) `refusalMessage` returns `String(detail)` for objects; (b) drop the string branch; (c) `previewRule` sends to `/merchant-rules`. Each must fail a test. Record in the ledger.
- [ ] **Step 6: Commit** `frontend/src/api.ts frontend/src/api.test.ts` - "Add rule preview/create API client with refusal messages". Ledger line; STOP.

---

## Task 2: `rememberRule.ts` reducer

**Files:** create `frontend/src/rememberRule.ts`, `frontend/src/rememberRule.test.ts`

**Interfaces - Consumes:** `RulePreview`, `RulePreviewRequest`, `RuleFromEditRequest`, `Transaction` from Task 1 / `api.ts`.
**Produces:**

```ts
export type RuleSource = Pick<Transaction, "id" | "account_id" | "description" | "clean_description">;
export type RememberRuleState = {
  source: RuleSource;
  categoryId: number;
  pattern: string;
  patternTouched: boolean;
  name: string | null;              // null: not edited, displayName() gives the default
  thisAccountOnly: boolean;
  preview: RulePreview | null;
  previewThisAccountOnly: boolean;  // scope the stored preview was computed for
  latestSeq: number;
  error: string | null;
  saving: boolean;
  savedRuleId: number | null;
} | null;
export type RememberRuleAction =
  | { type: "categoryEdited"; txn: RuleSource; categoryId: number | null }
  | { type: "previewRequested"; seq: number }
  | { type: "previewReceived"; seq: number; preview: RulePreview; thisAccountOnly: boolean }
  | { type: "previewFailed"; seq: number; message: string }
  | { type: "patternEdited"; pattern: string }
  | { type: "nameEdited"; name: string }
  | { type: "scopeToggled" }
  | { type: "saveStarted" }
  | { type: "saveSucceeded"; ruleId: number }
  | { type: "saveFailed"; message: string }
  | { type: "dismissed" };
export function rememberRuleReducer(state: RememberRuleState, action: RememberRuleAction): RememberRuleState;
export function displayName(state: NonNullable<RememberRuleState>): string;
export function canSave(state: RememberRuleState): boolean;
export function previewRequestBody(state: NonNullable<RememberRuleState>): RulePreviewRequest | null;
export function saveRequest(state: NonNullable<RememberRuleState>): RuleFromEditRequest;
```

- [ ] **Step 1: Write failing tests** in `rememberRule.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { RulePreview } from "./api";
import {
  canSave, displayName, previewRequestBody, rememberRuleReducer, saveRequest,
  type RememberRuleAction, type RememberRuleState, type RuleSource,
} from "./rememberRule";

const doordash: RuleSource = { id: 971, account_id: 3, description: "DD *DOORDASH KURA 855-123", clean_description: null };
const uber: RuleSource = { id: 81, account_id: 2, description: "UBER   *TRIP HELP.UBER.COM", clean_description: "Uber" };
const DINING = 7;
const TRAVEL = 9;

function preview(overrides: Partial<RulePreview> = {}): RulePreview {
  return {
    match_pattern: "DD *DOORDASH", matches_source: true, conflicting_rule: null,
    would_name_count: 46, would_categorize_count: 0, category_mismatch_count: 0, sample: [],
    ...overrides,
  };
}

function run(state: RememberRuleState, ...actions: RememberRuleAction[]): RememberRuleState {
  return actions.reduce(rememberRuleReducer, state);
}

function opened(txn = doordash, categoryId = DINING): RememberRuleState {
  return run(null, { type: "categoryEdited", txn, categoryId });
}

/** Panel with the suggested pattern previewed: every canSave condition holds. */
function ready(): NonNullable<RememberRuleState> {
  return run(opened(),
    { type: "previewRequested", seq: 1 },
    { type: "previewReceived", seq: 1, preview: preview(), thisAccountOnly: false },
  )!;
}

describe("opening and closing", () => {
  it("opens on a category edit with nothing filled in", () => {
    expect(opened()).toEqual({
      source: doordash, categoryId: DINING, pattern: "", patternTouched: false, name: null,
      thisAccountOnly: false, preview: null, previewThisAccountOnly: false, latestSeq: 0,
      error: null, saving: false, savedRuleId: null,
    });
  });
  it("closes when its own row is set back to Uncategorized", () => {
    expect(run(ready(), { type: "categoryEdited", txn: doordash, categoryId: null })).toBeNull();
  });
  it("stays open, unchanged, when another row is set to Uncategorized", () => {
    const state = ready();
    expect(run(state, { type: "categoryEdited", txn: uber, categoryId: null })).toBe(state);
  });
  it("stays closed when a row is set to Uncategorized with no panel open", () => {
    expect(run(null, { type: "categoryEdited", txn: uber, categoryId: null })).toBeNull();
  });
  it("replaces the panel when another row is edited", () => {
    const state = run(ready(), { type: "patternEdited", pattern: "DOORDASH" }, { type: "categoryEdited", txn: uber, categoryId: TRAVEL });
    expect(state).toEqual(opened(uber, TRAVEL));
  });
  it("replaces the panel when the same row gets another category", () => {
    expect(run(ready(), { type: "categoryEdited", txn: doordash, categoryId: TRAVEL })).toEqual(opened(doordash, TRAVEL));
  });
  it("keeps the panel as is when the same category is picked again", () => {
    const state = run(ready(), { type: "patternEdited", pattern: "DOORDASH" });
    expect(run(state, { type: "categoryEdited", txn: doordash, categoryId: DINING })).toBe(state);
  });
  it("closes on dismiss", () => {
    expect(run(ready(), { type: "dismissed" })).toBeNull();
  });
});

describe("previews", () => {
  it("prefills the pattern from the first preview", () => {
    const state = ready();
    expect(state.pattern).toBe("DD *DOORDASH");
    expect(state.patternTouched).toBe(false);
    expect(state.preview).toEqual(preview());
  });
  it("does not overwrite a pattern the user typed", () => {
    const state = run(opened(),
      { type: "patternEdited", pattern: "DOORDASH " },
      { type: "previewRequested", seq: 1 },
      { type: "previewReceived", seq: 1, preview: preview({ match_pattern: "DOORDASH" }), thisAccountOnly: false },
    );
    expect(state?.pattern).toBe("DOORDASH ");
    expect(state?.preview?.match_pattern).toBe("DOORDASH");
  });
  it("ignores a response that is not the latest request", () => {
    const state = run(opened(),
      { type: "previewRequested", seq: 1 },
      { type: "previewRequested", seq: 2 },
      { type: "previewReceived", seq: 1, preview: preview(), thisAccountOnly: false },
    );
    expect(state?.preview).toBeNull();
    expect(state?.pattern).toBe("");
  });
  it("ignores a response requested before the panel was replaced", () => {
    const state = run(opened(),
      { type: "previewRequested", seq: 1 },
      { type: "categoryEdited", txn: uber, categoryId: TRAVEL },
      { type: "previewReceived", seq: 1, preview: preview(), thisAccountOnly: false },
    );
    expect(state).toEqual(opened(uber, TRAVEL));
  });
  it("records the scope the preview was computed for", () => {
    const state = run(opened(), { type: "previewRequested", seq: 1 },
      { type: "previewReceived", seq: 1, preview: preview(), thisAccountOnly: true });
    expect(state?.previewThisAccountOnly).toBe(true);
  });
  it("shows a failed preview's message and clears the old preview", () => {
    const state = run(ready(), { type: "previewRequested", seq: 2 }, { type: "previewFailed", seq: 2, message: "changed" });
    expect(state?.error).toBe("changed");
    expect(state?.preview).toBeNull();
  });
  it("ignores a failure that is not the latest request", () => {
    const state = run(ready(), { type: "previewRequested", seq: 2 }, { type: "previewFailed", seq: 1, message: "late" });
    expect(state?.error).toBeNull();
  });
  it("clears the error when a new preview is requested", () => {
    const state = run(ready(), { type: "previewRequested", seq: 2 }, { type: "previewFailed", seq: 2, message: "x" }, { type: "previewRequested", seq: 3 });
    expect(state?.error).toBeNull();
    expect(state?.latestSeq).toBe(3);
  });
  it("editing the pattern marks it typed and clears the preview", () => {
    const state = run(ready(), { type: "patternEdited", pattern: "DOORDASH" });
    expect(state?.pattern).toBe("DOORDASH");
    expect(state?.patternTouched).toBe(true);
    expect(state?.preview).toBeNull();
  });
  it("toggling scope flips it and clears the preview", () => {
    const state = run(ready(), { type: "scopeToggled" });
    expect(state?.thisAccountOnly).toBe(true);
    expect(state?.preview).toBeNull();
  });
});

describe("display name", () => {
  it("defaults to the pattern when the row has no clean name", () => {
    expect(displayName(ready())).toBe("DD *DOORDASH");
  });
  it("defaults to the row's clean name when it has one", () => {
    expect(displayName({ ...opened(uber, TRAVEL)!, pattern: "UBER" })).toBe("Uber");
  });
  it("uses the typed name, even when blank", () => {
    expect(displayName(run(ready(), { type: "nameEdited", name: "DoorDash" })!)).toBe("DoorDash");
    expect(displayName(run(ready(), { type: "nameEdited", name: "" })!)).toBe("");
  });
});

describe("canSave", () => {
  it("is true when every condition holds", () => {
    expect(canSave(ready())).toBe(true);
  });
  it("is true when the typed pattern only adds surrounding spaces the server strips", () => {
    expect(canSave({ ...ready(), pattern: " DD *DOORDASH ", patternTouched: true })).toBe(true);
  });
  it.each<[string, (s: NonNullable<RememberRuleState>) => RememberRuleState]>([
    ["no panel", () => null],
    ["blank pattern", (s) => ({ ...s, pattern: "   " })],
    ["blank name", (s) => ({ ...s, name: "  " })],
    ["no preview yet", (s) => ({ ...s, preview: null })],
    ["preview for another pattern", (s) => ({ ...s, pattern: "DOORDASH" })],
    ["preview for another scope", (s) => ({ ...s, thisAccountOnly: true })],
    ["pattern doesn't match the row", (s) => ({ ...s, preview: preview({ matches_source: false }) })],
    ["an existing rule wins the row", (s) => ({ ...s, preview: preview({ conflicting_rule: { id: 61, match_pattern: "DD *", clean_name: "DD", category_id: 7, account_id: null } }) })],
    ["one category mismatch", (s) => ({ ...s, preview: preview({ category_mismatch_count: 1 }) })],
    ["save in flight", (s) => ({ ...s, saving: true })],
    ["already saved", (s) => ({ ...s, savedRuleId: 77 })],
  ])("is false with %s", (_label, change) => {
    expect(canSave(change(ready()))).toBe(false);
  });
});

describe("request bodies", () => {
  it("asks the server to suggest while the pattern is untouched", () => {
    expect(previewRequestBody(ready())).toEqual({ source_transaction_id: 971, match_pattern: null, category_id: DINING, this_account_only: false });
  });
  it("sends the typed pattern and scope once edited", () => {
    const state = run(ready(), { type: "patternEdited", pattern: "DOORDASH" }, { type: "scopeToggled" })!;
    expect(previewRequestBody(state)).toEqual({ source_transaction_id: 971, match_pattern: "DOORDASH", category_id: DINING, this_account_only: true });
  });
  it("sends nothing for a typed blank pattern", () => {
    expect(previewRequestBody(run(ready(), { type: "patternEdited", pattern: "  " })!)).toBeNull();
  });
  it("saves the trimmed pattern and name with the source, category and scope", () => {
    const state = run(ready(), { type: "patternEdited", pattern: " DOORDASH " }, { type: "nameEdited", name: " DoorDash " }, { type: "scopeToggled" })!;
    expect(saveRequest(state)).toEqual({ source_transaction_id: 971, match_pattern: "DOORDASH", clean_name: "DoorDash", category_id: DINING, this_account_only: true });
  });
});

describe("saving", () => {
  it("marks the panel saving, then saved with the rule id", () => {
    const saving = run(ready(), { type: "saveStarted" });
    expect(saving?.saving).toBe(true);
    const saved = run(saving, { type: "saveSucceeded", ruleId: 77 });
    expect(saved?.saving).toBe(false);
    expect(saved?.savedRuleId).toBe(77);
  });
  it("shows the server's message when saving fails", () => {
    const state = run(ready(), { type: "saveStarted" }, { type: "saveFailed", message: "An existing rule already names this transaction" });
    expect(state?.saving).toBe(false);
    expect(state?.error).toBe("An existing rule already names this transaction");
    expect(state?.savedRuleId).toBeNull();
  });
  it("ignores a save result that arrives after the panel was replaced", () => {
    const replaced = run(ready(), { type: "saveStarted" }, { type: "categoryEdited", txn: uber, categoryId: TRAVEL });
    expect(run(replaced, { type: "saveSucceeded", ruleId: 77 })).toBe(replaced);
    expect(run(replaced, { type: "saveFailed", message: "x" })).toBe(replaced);
  });
});
```

- [ ] **Step 2: Run** `npm test` - fails (module missing).
- [ ] **Step 3: Implement** `rememberRule.ts`:

```ts
import type { RuleFromEditRequest, RulePreview, RulePreviewRequest, Transaction } from "./api";

/** The edited row a rule is being remembered from. */
export type RuleSource = Pick<Transaction, "id" | "account_id" | "description" | "clean_description">;

// RememberRuleState and RememberRuleAction exactly as in the Interfaces block above.

function openFor(source: RuleSource, categoryId: number): NonNullable<RememberRuleState> {
  return {
    source, categoryId, pattern: "", patternTouched: false, name: null, thisAccountOnly: false,
    preview: null, previewThisAccountOnly: false, latestSeq: 0, error: null, saving: false, savedRuleId: null,
  };
}

/** Opens, replaces, keeps or closes the panel after a successful category edit. */
function afterCategoryEdit(state: RememberRuleState, txn: RuleSource, categoryId: number | null): RememberRuleState {
  const isPanelRow = state?.source.id === txn.id;
  if (categoryId === null) return isPanelRow ? null : state;
  if (isPanelRow && state?.categoryId === categoryId) return state;
  return openFor(txn, categoryId);
}

/** The name the rule will store: what the user typed, else the row's clean name, else the pattern. */
export function displayName(state: NonNullable<RememberRuleState>): string {
  return state.name ?? state.source.clean_description ?? state.pattern;
}

/** True only when the latest preview says the server would accept this exact rule. */
export function canSave(state: RememberRuleState): boolean {
  if (!state || state.saving || state.savedRuleId !== null || !state.preview) return false;
  const pattern = state.pattern.trim();
  const preview = state.preview;
  return (
    pattern !== "" &&
    displayName(state).trim() !== "" &&
    preview.match_pattern === pattern &&
    state.previewThisAccountOnly === state.thisAccountOnly &&
    preview.matches_source &&
    preview.conflicting_rule === null &&
    preview.category_mismatch_count === 0
  );
}

/** The preview to ask for, or null when there is nothing to check (typed pattern is blank). */
export function previewRequestBody(state: NonNullable<RememberRuleState>): RulePreviewRequest | null {
  if (state.patternTouched && state.pattern.trim() === "") return null;
  return {
    source_transaction_id: state.source.id,
    match_pattern: state.patternTouched ? state.pattern : null,
    category_id: state.categoryId,
    this_account_only: state.thisAccountOnly,
  };
}

export function saveRequest(state: NonNullable<RememberRuleState>): RuleFromEditRequest {
  return {
    source_transaction_id: state.source.id,
    match_pattern: state.pattern.trim(),
    clean_name: displayName(state).trim(),
    category_id: state.categoryId,
    this_account_only: state.thisAccountOnly,
  };
}

/**
 * Panel transitions for remembering a category edit as a rule. Preview results apply only to
 * the latest request (seq), and save results only while a save is in flight, so a late response
 * can't land in a panel that was replaced.
 */
export function rememberRuleReducer(state: RememberRuleState, action: RememberRuleAction): RememberRuleState {
  switch (action.type) {
    case "categoryEdited":
      return afterCategoryEdit(state, action.txn, action.categoryId);
    case "dismissed":
      return null;
  }
  if (!state) return state;
  switch (action.type) {
    case "previewRequested":
      return { ...state, latestSeq: action.seq, error: null };
    case "previewReceived":
      if (action.seq !== state.latestSeq) return state;
      return {
        ...state,
        preview: action.preview,
        previewThisAccountOnly: action.thisAccountOnly,
        pattern: state.patternTouched ? state.pattern : action.preview.match_pattern,
      };
    case "previewFailed":
      if (action.seq !== state.latestSeq) return state;
      return { ...state, preview: null, error: action.message };
    case "patternEdited":
      return { ...state, pattern: action.pattern, patternTouched: true, preview: null };
    case "nameEdited":
      return { ...state, name: action.name };
    case "scopeToggled":
      return { ...state, thisAccountOnly: !state.thisAccountOnly, preview: null };
    case "saveStarted":
      return { ...state, saving: true, error: null };
    case "saveSucceeded":
      if (!state.saving) return state;
      return { ...state, saving: false, savedRuleId: action.ruleId };
    case "saveFailed":
      if (!state.saving) return state;
      return { ...state, saving: false, error: action.message };
  }
}
```

(If `tsc` rejects the two-switch shape for exhaustiveness, fold `categoryEdited`/`dismissed` into one switch with `if (!state) return state;` inside each other case. Keep behavior identical.)

- [ ] **Step 4: Run** `npm test`, `npm run build`, `npm run lint` - all pass.
- [ ] **Step 5: Mutation check** on a scratch copy (restore after). Each must fail at least one test; record which in the ledger:
  1. `previewReceived` drops the seq check.
  2. `canSave` drops the `match_pattern` comparison.
  3. `canSave` drops the scope comparison.
  4. `canSave` compares without `.trim()`.
  5. `canSave` uses `> 1` for mismatches.
  6. `previewReceived` always overwrites the pattern.
  7. `afterCategoryEdit` closes on any null.
  8. `afterCategoryEdit` always reopens (no same-category keep).
  9. `saveSucceeded` drops the `saving` guard.
  10. `previewRequestBody` always sends `state.pattern`.
  11. `displayName` ignores `clean_description`.
  12. `patternEdited` keeps the preview.

  Known equivalent mutant: dropping `pattern !== ""` from `canSave` survives, because the server never returns an empty `match_pattern`, so the match comparison already fails for a blank pattern. The check stays as LLD 5 lists it; record it in the ledger as equivalent rather than writing a test that can't fail.
- [ ] **Step 6: Commit** the two files - "Add rememberRule reducer for the remember-edit-as-rule panel". Ledger line; STOP.

---

## Task 3: Panel and App wiring

**Files:** create `frontend/src/RememberRulePanel.tsx`; modify `frontend/src/App.tsx`

**Interfaces - Consumes:** everything from Tasks 1-2; `Card`, `PrimaryButton`, `SecondaryButton`, `inputClass` from `ui.tsx`; `IconCheck`, `IconX` from `icons.tsx`.
**Produces:** `RememberRulePanel` default export with props
`{ state: NonNullable<RememberRuleState>; categoryName: string; accountName: string; onPatternChange(pattern: string): void; onNameChange(name: string): void; onScopeToggle(): void; onSave(): void; onDismiss(): void }`.

No automated test for this task (LLD 6); gate is build + lint + full vitest + a quick smoke load in the browser. Live behavior is Task 4.

- [ ] **Step 1: Panel** `RememberRulePanel.tsx`. Layout in the `HeldImportPanel` style (`Card className="mb-4 border-accent/40"`). Contents, top to bottom:
  - Heading "Remember this as a rule?"; one line: "Future transactions matching the pattern get this name and category."
  - When `state.savedRuleId !== null`: replace the body with "Rule saved (#{id}). Matching transactions without a name were updated. To undo, delete rule {id} with `DELETE /merchant-rules/{id}`." and a Close button (`onDismiss`). Nothing else.
  - Otherwise:
    - "Pattern" text input (`inputClass`), value `state.pattern`, placeholder "Finding a pattern..." while `!state.patternTouched && state.pattern === ""`.
    - "Name" text input, value `displayName(state)`.
    - "Category: {categoryName}" (read-only).
    - Scope: checkbox "Only for {accountName}" bound to `thisAccountOnly`.
    - Status area, first that applies:
      - `state.error` -> `text-critical` line with the message;
      - `!state.preview` -> muted "Checking..." (or "Enter a pattern" when the typed pattern is blank);
      - `!preview.matches_source` -> warning "The pattern doesn't appear in this transaction's description: {source.description}";
      - `preview.conflicting_rule` -> warning "Rule #{id} ("{match_pattern}" -> {clean_name}) already names this transaction{, for this account only when account_id set}." plus, only when that rule is global (`account_id === null`) and `!thisAccountOnly`: "Checking "Only for {accountName}" would put this rule ahead of it.";
      - `preview.category_mismatch_count > 0` -> warning "{n} transaction(s) this pattern matches are already in another category. Narrow the pattern to save.";
      - else -> "Would name {would_name_count} transaction(s) and categorize {would_categorize_count} of them."
    - Sample list (when `preview.sample.length > 0`): "Examples:" then each row `date · description · category_name ?? "Uncategorized"`, with rows whose `category_name !== categoryName` in `text-critical`.
    - Muted footnote: "On import, this rule is applied before the bank's own category."
    - Buttons: `PrimaryButton` "Save rule" (`disabled={!canSave(state)}`, label "Saving..." while `state.saving`), `SecondaryButton` "Dismiss".
- [ ] **Step 2: App wiring** in `App.tsx`:
  - imports: `useRef`; `previewRule`, `createRuleFromEdit`, `type RulePreviewRequest` from `./api`; `RememberRulePanel`; `rememberRuleReducer`, `previewRequestBody`, `saveRequest` from `./rememberRule`.
  - state: `const [rememberRule, dispatchRememberRule] = useReducer(rememberRuleReducer, null);` and `const previewSeq = useRef(0);` (never reset - decision 6).
  - `handleCategoryChange`:

    ```ts
    async function handleCategoryChange(txnId: number, categoryId: number | null) {
      const updated = await updateTransaction(txnId, { category_id: categoryId });
      dispatchRememberRule({ type: "categoryEdited", txn: updated, categoryId });
      reload();
    }
    ```

  - Preview effect (decision 7):

    ```ts
    const previewKey = rememberRule && JSON.stringify(previewRequestBody(rememberRule));

    useEffect(() => {
      const request: RulePreviewRequest | null = previewKey && JSON.parse(previewKey);
      if (!request) return;
      const timer = setTimeout(() => {
        const seq = ++previewSeq.current;
        dispatchRememberRule({ type: "previewRequested", seq });
        previewRule(request).then(
          (preview) => dispatchRememberRule({ type: "previewReceived", seq, preview, thisAccountOnly: request.this_account_only }),
          (err: Error) => dispatchRememberRule({ type: "previewFailed", seq, message: err.message })
        );
      }, 300);
      return () => clearTimeout(timer);
    }, [previewKey]);
    ```

    (`JSON.stringify(null)` is `"null"`, which parses back to null - no request.)
  - `handleSaveRule`:

    ```ts
    async function handleSaveRule() {
      if (!rememberRule) return;
      dispatchRememberRule({ type: "saveStarted" });
      try {
        const rule = await createRuleFromEdit(saveRequest(rememberRule));
        dispatchRememberRule({ type: "saveSucceeded", ruleId: rule.id });
        reload();
      } catch (err) {
        dispatchRememberRule({ type: "saveFailed", message: err instanceof Error ? err.message : String(err) });
      }
    }
    ```

  - Render directly after the `HeldImportPanel` block (above `error` and the `loading ?` branch):

    ```tsx
    {rememberRule && (
      <RememberRulePanel
        state={rememberRule}
        categoryName={categoryById.get(rememberRule.categoryId)?.name ?? `Category ${rememberRule.categoryId}`}
        accountName={accountById.get(rememberRule.source.account_id)?.name ?? `Account ${rememberRule.source.account_id}`}
        onPatternChange={(pattern) => dispatchRememberRule({ type: "patternEdited", pattern })}
        onNameChange={(name) => dispatchRememberRule({ type: "nameEdited", name })}
        onScopeToggle={() => dispatchRememberRule({ type: "scopeToggled" })}
        onSave={handleSaveRule}
        onDismiss={() => dispatchRememberRule({ type: "dismissed" })}
      />
    )}
    ```
- [ ] **Step 3: Run** `npm test`, `npm run build`, `npm run lint`. Fix lint findings (e.g. hook-deps) without changing behavior; if a hook-deps rule fires on the effect, keep `previewKey` as the only dep and note it in the ledger.
- [ ] **Step 4: Smoke** - with whatever dev servers Task 4 sets up, load the Transactions tab once and confirm no console errors before any edit. (Full walkthrough is Task 4.)
- [ ] **Step 5: Self-review** against LLD 5 bullet by bullet (panel contents, placement, `canSave`, PATCH-first, refusal message, saved state, reload). Note any gap in the ledger.
- [ ] **Step 6: Commit** `RememberRulePanel.tsx` + `App.tsx` - "Add remember-edit-as-rule panel to the Transactions tab". Ledger line; STOP.

---

## Task 4: Live walkthrough on a DB copy, reviews, docs, push

**Files:** `docs/lld_edit_creates_merchant_rule_claude.md`, `README.md` (if applicable), memory.

The frontend hardcodes `API_BASE = http://localhost:8000`, so the walkthrough backend must run **on port 8000** against a copy.

- [ ] **Step 1: Environment.** Run the `check-running-processes` skill. If anything is on 8000 or 5173, **ask Liz before stopping it** (it may be her real dev server). Copy `backend/finance.db` to the scratchpad; record its rule count and row count. Start `uvicorn app.main:app --port 8000` (no `--reload`) with `DATABASE_PATH` set to the copy; start `npm run dev`. Hit `GET /merchant-rules` and confirm the count matches the copy (proves the server reads the copy).
- [ ] **Step 2: Oracle first.** Before opening the browser, compute with raw SQL on the copy (`instr(lower(description), lower(:p)) > 0`, not `LIKE`) the expected preview for txn 971 with its suggested pattern `DD *DOORDASH`, global scope (Phase 1 got name 46 / categorize 0 / mismatch 0 / sample [971, 973, 975, 978, 989]; recompute, don't reuse). Also for `UBER` from txn 81 (mismatch count) and the conflict rule for txn 813.
- [ ] **Step 3: Walkthrough** (claude-in-chrome, new tab). Each check: what the screen shows vs the oracle.
  1. Re-pick Dining & Drinks on txn 971 -> panel opens above the table; pattern prefills `DD *DOORDASH`; line reads 46 / 0; sample matches the oracle ids; Save enabled.
  2. Toggle "Only for {account}" -> preview refreshes with the scoped count (oracle: same query filtered to the account); toggle back.
  3. Type a pattern that isn't in the description -> "doesn't appear" warning, Save disabled. Clear the pattern -> "Enter a pattern", Save disabled, no request (network panel).
  4. Txn 81 in its current category, pattern `UBER` -> mismatch warning with the oracle count; mismatching sample rows in red; Save disabled.
  5. Txn 813 -> conflict warning naming rule 61; no "Only for" hint, because rule 61 is account-scoped.
  6. Filter regression: set the category filter to a category, edit a visible row to a different category -> row leaves the table, panel stays and previews.
  7. Edit another row while a panel is open -> panel replaced for the new row.
  8. Failed PATCH: stop the backend, change a category -> no panel opens; restart the backend (same copy, port 8000).
  9. Save on txn 971 (name "DoorDash") -> "Rule saved (#id)"; table reloads showing "DoorDash". Raw SQL: exactly the oracle's 46 rows now `clean_description = 'DoorDash'`, categories unchanged, one new rule.
  10. Undo: `DELETE /merchant-rules/{id}` -> 204; rows keep their names (LLD 4.4).
- [ ] **Step 4: Teardown.** Close the browser tab; stop both servers; confirm ports free; delete the copy; confirm the real DB rule and row counts are unchanged. Restart anything stopped in Step 1 only if Liz asks.
- [ ] **Step 5: Reviews** (global rule). Fresh no-context Opus subagent and `codex exec`, each given this plan, LLD 5/8, and the diff against the Phase 2 base commit (record it in the ledger at Task 1 start). Both must run `npm test`, `npm run build`, `npm run lint` and the backend suite and report literal output, and for each test name the wrong implementation that would still pass. Verify every finding against the code before acting; re-run any reported failure serially. Fix unambiguous gaps; bring High-severity or design-surface findings to Liz.
- [ ] **Step 6: Docs.** LLD: status line (Phase 2 built + live-verified), new section 12 (decisions 1-9 above, Liz's ruling on decision 3, walkthrough results with oracle numbers, review findings). README: one line under Transactions features if such a list exists. Memory `edit_creates_rule_status.md` + `MEMORY.md` pointer.
- [ ] **Step 7: Commit** docs (staged by name) and **push** all Phase 2 commits. Verify `git status` clean and `git log origin/main..main` empty.
