import type { ImportSummary } from "./api";

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

/** Opens the panel for a response that held rows, with nothing selected; closes it otherwise. */
function openOrClose(file: File, summary: ImportSummary): HeldImportState {
  if (summary.rows_held_as_suspected_duplicate === 0) return null;
  return { file, summary, selected: new Set(), busy: false };
}

function toggled(selected: ReadonlySet<string>, hash: string): Set<string> {
  const next = new Set(selected);
  if (next.has(hash)) next.delete(hash);
  else next.add(hash);
  return next;
}

/**
 * Panel transitions for held import rows. Retry results apply only while the panel still shows
 * the same File object the retry was sent with, so a late response can't reopen a stale panel.
 */
export function heldImportReducer(state: HeldImportState, action: HeldImportAction): HeldImportState {
  switch (action.type) {
    case "uploadStarted":
    case "dismiss":
      return null;
    case "uploadSucceeded":
      return openOrClose(action.file, action.summary);
    case "toggle":
      return state && { ...state, selected: toggled(state.selected, action.hash) };
    case "retryStarted":
      return state && { ...state, busy: true };
    case "retrySucceeded":
      if (state?.file !== action.file) return state;
      return openOrClose(action.file, action.summary);
    case "retryFailed":
      if (state?.file !== action.file) return state;
      return { ...state, busy: false };
  }
}
