import type { RuleFromEditRequest, RulePreview, RulePreviewRequest, Transaction } from "./api";

/** The edited row a rule is being remembered from. */
export type RuleSource = Pick<Transaction, "id" | "account_id" | "description" | "clean_description">;

export type RememberRuleState = {
  source: RuleSource;
  categoryId: number;
  pattern: string;
  patternTouched: boolean;
  name: string | null; // null: not edited, displayName() gives the default
  thisAccountOnly: boolean;
  preview: RulePreview | null;
  previewThisAccountOnly: boolean; // scope the stored preview was computed for
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

/** A sample row already in another category; an uncategorized row is one the rule would fill, not a mismatch. */
export function isMismatch(rowCategory: string | null, categoryName: string): boolean {
  return rowCategory !== null && rowCategory !== categoryName;
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

/** The create-rule request for the panel's current pattern, name, category and scope. */
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
 * Pattern and scope edits drop the preview and any error, and reset latestSeq to 0 (no request
 * uses it), so a response still in flight for the old inputs can't land.
 */
const invalidated = { preview: null, error: null, latestSeq: 0 };

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
      return { ...state, pattern: action.pattern, patternTouched: true, ...invalidated };
    case "nameEdited":
      return { ...state, name: action.name };
    case "scopeToggled":
      return { ...state, thisAccountOnly: !state.thisAccountOnly, ...invalidated };
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
