# Import Overlap Guard - Phase 3 Implementation Plan (accept panel)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When an import holds rows as possible duplicates, show them in a panel under the upload control, new vs existing side by side, and let the user import any of them anyway by re-sending the same file with the chosen hashes.

**Architecture:** `uploadCsv(file, acceptHashes)` appends one `accept_hashes` form field per hash. A pure reducer in `frontend/src/heldImport.ts` owns the panel state (`file`, latest `summary`, selected hashes, busy flag); `App.tsx` dispatches into it from the upload and retry handlers. A small presentational component `HeldImportPanel.tsx` renders the state. The backend is unchanged (Phase 2 already accepts `accept_hashes`).

**Tech Stack:** React 19 + TypeScript, Tailwind, vitest. No component-testing library in the project; the rendered panel is verified live (LLD: "The rendered panel itself is verified live").

**Spec:** `docs/lld_import_overlap_guard_claude.md` ("Frontend changes", tests 16-17, "Live verification plan"). Phase 2 plan: `docs/plan_import_overlap_guard_phase2_claude.md`.

## Global Constraints

- `accept_hashes` is a **repeated** form field: `formData.append("accept_hashes", hash)` once per hash. No JSON. With no hashes, no `accept_hashes` entry at all.
- The panel shows only when the latest response for the pending file has `rows_held_as_suspected_duplicate > 0`.
- Every checkbox starts **unchecked**. Nothing is imported without an explicit click on **Import selected**.
- **Import selected** re-sends the *same* `File` object with the checked hashes, then replaces the held list with the new response's list; closes the panel when none remain.
- **Dismiss** clears the pending state; held rows stay out of the DB.
- Starting any new upload clears the panel and selection **immediately** (before the request returns).
- While a retry is in flight, the panel's checkboxes and buttons are disabled.
- A failed retry keeps the panel and the selection, and shows the error in the status line.
- Code style: small functions, docstrings, no defensive try/except, no emojis. Match surrounding style.

**Decisions this plan adds (record in the LLD, Task 4):**

1. **Late retry response after a new upload.** The LLD says a stale panel "can't happen", but the Import CSV button is not part of the panel, so the user can start a new upload while a retry is in flight. The retry's response would then reopen the old file's panel. The reducer ignores `retrySucceeded` / `retryFailed` unless the state's `file` is the same `File` object the retry was sent with. One equality check; test 17 pins it.
2. **Selection after a successful retry resets to empty.** Every selected hash was just inserted, so none of them can be in the new held list; resetting is equivalent to intersecting and simpler to read.
3. **Two overlapping fresh uploads** (pick file A, then file B before A returns) can still show A's status line or panel last. This is the same race the status line has today; not fixed here. Out of scope, noted in the LLD.
4. **Live walkthrough runs the DB-copy backend on port 8000.** `API_BASE` is hard-coded to `http://localhost:8000` and CORS allows only `http://localhost:5173`, so the normal Vite dev server can only talk to port 8000. Task 4 stops the normal backend, starts one on 8000 with `DATABASE_PATH` pointing at a copy, and restores the normal one afterwards. Rejected: making `API_BASE` configurable plus a second CORS origin - new config surface for a one-off check.

## Review Focus

Input classes the spec implies that tests 16-17 might not pin:

1. **Retry that resolves everything** (`rows_held_as_suspected_duplicate: 0`): panel must close, not show an empty card. -> test 17.
2. **Retry that holds more or different rows than before** (should not happen with stable pairing, but the reducer must just display what the server returned). -> test 17 replaces the list wholesale, asserts the new list, not a filtered old one.
3. **Toggle twice** returns to unselected (a `Set.add` without delete passes a one-toggle test). -> test 17.
4. **Upload with zero held rows while a panel is open**: `uploadStarted` clears it, `uploadSucceeded` with 0 held leaves it closed. -> test 17.
5. **State immutability**: `toggle` must return a new `Set`, or React won't re-render the checkbox. -> test 17 asserts the previous state's set is unchanged.

---

## File Structure

- Modify `frontend/src/api.ts` - `uploadCsv(file, acceptHashes = [])`.
- Modify `frontend/src/api.test.ts` - test 16.
- Create `frontend/src/heldImport.ts` - state type, actions, `heldImportReducer`.
- Create `frontend/src/heldImport.test.ts` - test 17.
- Create `frontend/src/HeldImportPanel.tsx` - presentational panel.
- Modify `frontend/src/App.tsx` - `useReducer`, upload/retry/dismiss handlers, render panel.
- Modify `docs/lld_import_overlap_guard_claude.md` - status, decisions 1-4, live results.

Frontend commands run from `frontend/`: `npx vitest run`, `npx tsc -b`. Work on `main` per the standing git routine; commit per task, staging only that task's files.

---

### Task 1: `uploadCsv` sends repeated `accept_hashes` (test 16)

**Files:** Modify `frontend/src/api.ts`, `frontend/src/api.test.ts`

- [ ] **Step 1: Write the failing tests** (append to `api.test.ts`; import `uploadCsv`)

```ts
describe("uploadCsv", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function sentForm(fetchMock: ReturnType<typeof vi.fn>): FormData {
    return fetchMock.mock.calls[0][1].body as FormData;
  }

  it("sends the file and one accept_hashes entry per hash, in order", async () => {
    const fetchMock = stubFetch({});
    const file = new File(["a,b\n"], "x.csv", { type: "text/csv" });

    await uploadCsv(file, ["h1", "h2"]);

    const form = sentForm(fetchMock);
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    expect(requestedUrl(fetchMock).pathname).toBe("/imports");
    expect((form.get("file") as File).name).toBe("x.csv");
    expect(form.getAll("accept_hashes")).toEqual(["h1", "h2"]);
  });

  it("sends no accept_hashes entry when no hashes are given", async () => {
    const fetchMock = stubFetch({});
    const file = new File(["a,b\n"], "x.csv", { type: "text/csv" });

    await uploadCsv(file);

    expect(sentForm(fetchMock).has("accept_hashes")).toBe(false);
  });
});
```

Mutants these kill: joining hashes into one field (`getAll` length 1); JSON-encoding (`["[\"h1\",\"h2\"]"]`); sending only the first hash; appending an empty `accept_hashes` when the list is empty.

- [ ] **Step 2: Run, expect FAIL** - `npx vitest run src/api.test.ts` (first test fails: `getAll` returns `[]`).

- [ ] **Step 3: Implement**

```ts
export async function uploadCsv(file: File, acceptHashes: string[] = []): Promise<ImportSummary> {
  const formData = new FormData();
  formData.append("file", file);
  for (const hash of acceptHashes) formData.append("accept_hashes", hash);
  const res = await fetch(`${API_BASE}/imports`, { method: "POST", body: formData });
  return asJson(res, "Import failed");
}
```

- [ ] **Step 4: Run, expect PASS**, then full `npx vitest run` and `npx tsc -b`.
- [ ] **Step 5: Commit** `api.ts`, `api.test.ts` - "Send accept_hashes from uploadCsv".

---

### Task 2: Panel reducer (test 17)

**Files:** Create `frontend/src/heldImport.ts`, `frontend/src/heldImport.test.ts`

**Interface (Task 3 relies on it):**

```ts
/** Panel state for an import that held rows as possible duplicates; null when no panel is shown. */
export type HeldImportState = {
  file: File;
  summary: ImportSummary;
  selected: ReadonlySet<string>;
  busy: boolean;
} | null;

export type HeldImportAction =
  | { type: "uploadStarted" }
  | { type: "uploadSucceeded"; file: File; summary: ImportSummary }
  | { type: "toggle"; hash: string }
  | { type: "retryStarted" }
  | { type: "retrySucceeded"; file: File; summary: ImportSummary }
  | { type: "retryFailed"; file: File }
  | { type: "dismiss" };

export function heldImportReducer(state: HeldImportState, action: HeldImportAction): HeldImportState;
```

Behaviour:

| Action | Result |
|---|---|
| `uploadStarted` | `null` |
| `uploadSucceeded` | held > 0: `{file, summary, selected: empty, busy: false}`; else `null` |
| `toggle` | state null: `null`; else new `Set` with `hash` added or removed |
| `retryStarted` | state null: `null`; else `busy: true` |
| `retrySucceeded` | state null or `state.file !== action.file`: unchanged; held > 0: `{file, summary: action.summary, selected: empty, busy: false}`; else `null` |
| `retryFailed` | state null or different file: unchanged; else `busy: false`, selection kept |
| `dismiss` | `null` |

- [ ] **Step 1: Write the failing tests** (`heldImport.test.ts`)

Helper `summaryWith(hashes: string[])` builds an `ImportSummary` whose `suspected_duplicates` has one entry per hash and whose `rows_held_as_suspected_duplicate` equals `hashes.length`. Tests (each a separate `it`):

1. `uploadSucceeded` with held `["a","b"]` opens the panel: same `file`, summary's hashes `["a","b"]`, `selected` empty, `busy` false.
2. `uploadSucceeded` with 0 held -> `null`.
3. `toggle "a"` selects it; `toggle "a"` again deselects it; the pre-toggle state's `selected` still has size 0 (immutability).
4. `toggle` on `null` -> `null`.
5. `retryStarted` sets `busy: true` and keeps `selected`.
6. `retrySucceeded` with held `["b","c"]` (different from before) -> held list is exactly `["b","c"]`, `selected` empty, `busy` false.
7. `retrySucceeded` with 0 held -> `null`.
8. `retryFailed` -> panel kept, `selected` still `{"a"}`, `busy` false.
9. `dismiss` -> `null`.
10. `uploadStarted` while a panel is open with a selection -> `null`.
11. Stale retry: open panel for file A, `uploadStarted`, `uploadSucceeded` for file B (held `["x"]`), then `retrySucceeded` for file A with held `["a"]` -> still B's panel, held `["x"]`. Same for `retryFailed` for file A -> B's state unchanged (`busy` as before).
12. Stale retry after dismiss: `dismiss`, then `retrySucceeded` for A -> `null`.

Files are distinct `new File([...], "a.csv")` / `"b.csv"` objects; test 11 also uses two `File`s with the **same name** to prove the check is object identity, not name.

- [ ] **Step 2: Run, expect FAIL** (module missing).
- [ ] **Step 3: Implement** `heldImportReducer` as a `switch` on `action.type` with a helper `openOrClose(file, summary)` shared by `uploadSucceeded` and `retrySucceeded`.
- [ ] **Step 4: Run, expect PASS**; full `npx vitest run`, `npx tsc -b`.
- [ ] **Step 5: Mutation check** (by hand, revert each): toggle without delete (test 3); `retrySucceeded` keeps old selection (6); skip the file-identity check (11); compare by `file.name` (11, same-name case); `retryFailed` clears selection (8); `uploadSucceeded` opens at 0 held (2). Each must fail at least one test.
- [ ] **Step 6: Commit** both files - "Add held-import panel reducer".

---

### Task 3: Render the panel and wire it into the upload flow

**Files:** Create `frontend/src/HeldImportPanel.tsx`; modify `frontend/src/App.tsx`

- [ ] **Step 1: `HeldImportPanel.tsx`**

Props: `state: NonNullable<HeldImportState>`, `onToggle(hash)`, `onImportSelected()`, `onDismiss()`.

Layout, reusing the "Transfers to review" card pattern (`Card className="mb-4 border-accent/40"`):

- Heading: `Held as possible duplicates ({n})`.
- One line of explanation: "These rows match a transaction already imported to the same account, for the same amount, within 3 days. They were not imported."
- One row per suspect (key `row_hash`), bordered like the transfer rows:
  - left: checkbox `Import anyway` (checked = `selected.has(row_hash)`, disabled when `busy`)
  - **New:** `date · account_name`, `description`, amount (`formatAmount`, red/green as `TransactionSummary`)
  - `&harr;`
  - **Already imported:** `existing_date · account_name`, `existing_description`, same amount
- Footer: `PrimaryButton` **Import selected ({k})**, disabled when `k === 0` or `busy`; `SecondaryButton` **Dismiss**, disabled when `busy`.

- [ ] **Step 2: Wire into `App.tsx`**

```ts
const [heldImport, dispatchHeldImport] = useReducer(heldImportReducer, null);

async function handleFileUpload(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  dispatchHeldImport({ type: "uploadStarted" });
  setUploadStatus(`Importing ${file.name}...`);
  try {
    const summary = await uploadCsv(file);
    setUploadStatus(formatImportStatus(summary));
    dispatchHeldImport({ type: "uploadSucceeded", file, summary });
    reload();
  } catch (err) {
    setUploadStatus(`Failed to import ${file.name}: ${String(err)}`);
  } finally {
    e.target.value = "";
  }
}

async function handleImportSelected() {
  if (!heldImport) return;
  const { file, selected } = heldImport;
  dispatchHeldImport({ type: "retryStarted" });
  setUploadStatus(`Importing ${selected.size} selected row(s) from ${file.name}...`);
  try {
    const summary = await uploadCsv(file, [...selected]);
    setUploadStatus(formatImportStatus(summary));
    dispatchHeldImport({ type: "retrySucceeded", file, summary });
    reload();
  } catch (err) {
    setUploadStatus(`Failed to import selected rows from ${file.name}: ${String(err)}`);
    dispatchHeldImport({ type: "retryFailed", file });
  }
}
```

(The `try/catch` mirrors `handleFileUpload`: a network or 4xx failure is a real, expected case here.)

Render `{heldImport && <HeldImportPanel ... />}` directly below the upload/Detect/Export row, above `{error && ...}`.

- [ ] **Step 3: Checks** - `npx tsc -b`, `npx vitest run` (all green, count reported), `npx vite build` succeeds.
- [ ] **Step 4: Commit** `HeldImportPanel.tsx`, `App.tsx` - "Show held import rows with import-anyway selection".

The panel's rendering is verified in Task 4, not by unit test.

---

### Task 4: Live browser walkthrough on a DB copy, docs

Oracle first (raw SQL against the copy, before opening the browser): the Phase 2 live result table already gives the expected held sets and partners for the three files; re-derive the counts with SQL on the fresh copy (`SELECT COUNT(*) FROM transactions`, and the partner ids 401-408, 410-415, 417, 562, 563 exist) before looking at the UI.

- [ ] **Step 1: Switch the backend to a DB copy on port 8000.** Note whether a normal backend is running on 8000 (`netstat -ano | grep :8000`). If so, stop it (reloader first, then worker - see dev-server gotchas). Copy `backend/finance.db` to `$SCRATCH/finance_phase3.db`. Start `DATABASE_PATH=$SCRATCH/finance_phase3.db venv/Scripts/python.exe -m uvicorn app.main:app --port 8000` (no `--reload`). Confirm with `curl -s localhost:8000/health` and that `curl -s localhost:8000/transactions | ` row count equals the copy's SQL count. Start Vite on 5173 if not running.
- [ ] **Step 2: Walkthrough** (claude-in-chrome, new tab, screenshots at each step):
  1. Import `data/ExportData_BOA_July2026_9837.csv`: status line `0 new, 2 already imported, 15 held as possible duplicates`; panel lists 15 rows, each new row beside its partner (spot-check 3 against the oracle ids); **Import selected (0)** disabled.
  2. Check IKEA -$127.35, click **Import selected (1)**: buttons disable during the request; status `1 new, 2 already imported, 14 held`; panel shows 14, none checked. SQL: count +1, the new row's hash is the accepted one.
  3. Click **Dismiss**: panel closes; SQL count unchanged.
  4. Import `ExportData_BOA_3938_Oct142026.csv`: 2 held (partners 562, 563). Then, with that panel open, import `ExportData_BOA_Aug2026_9837.csv` (0 held): the panel closes as soon as the upload starts and stays closed.
  5. Import `ExportData_BOA_1962_July2026.csv`: 24 held; check 2, uncheck 1, **Import selected (1)**: exactly 1 new (SQL), 23 held.
  6. Regression sweep: Transactions table, filters, Detect Transfers, Export CSV, Dashboard, Chat tab load with no console errors.
- [ ] **Step 3: Restore.** Stop the copy backend (confirm port 8000 free), restart the normal backend the way it was running before (with `--reload` if it had it), confirm `/health` and that the real `finance.db` count is unchanged from before Task 4. Delete `$SCRATCH/finance_phase3.db`. Close the browser tab.
- [ ] **Step 4: Docs.** LLD: status line ("Phase 3 built and live-verified"), decisions 1-4 under Frontend changes, a "Live result (Phase 3)" table. Commit the LLD and this plan.
- [ ] **Step 5: Close-out review** (Opus subagent + Codex, against merge-base before Task 1): both run `npx vitest run` and `npx tsc -b` and report literal output; mutation pass over tests 16-17 (helpers included). Verify findings, fix inside approved direction, record in the LLD review log. Push.
- [ ] **Step 6: Follow-ups** after push: update the import runbook artifact's manual overlap-check step (the guard now does it; the step becomes "review the held panel") and its stale data-through dates; update `overlap_guard_status` memory.
