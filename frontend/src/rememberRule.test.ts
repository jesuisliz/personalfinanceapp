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
