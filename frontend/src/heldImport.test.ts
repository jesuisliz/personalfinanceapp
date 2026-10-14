import { describe, expect, it } from "vitest";
import type { ImportSummary } from "./api";
import { heldImportReducer, retryRequest, type HeldImportState } from "./heldImport";

function summaryWith(hashes: string[]): ImportSummary {
  return {
    filename: "x.csv",
    rows_seen: hashes.length + 5,
    rows_inserted: 3,
    rows_skipped_as_duplicate: 2,
    rows_held_as_suspected_duplicate: hashes.length,
    suspected_duplicates: hashes.map((hash, i) => ({
      row_hash: hash,
      account_name: "Cash Rewards",
      date: `2026-07-0${i + 1}`,
      description: `NEW ${hash}`,
      amount_cents: -1000 - i,
      existing_id: 400 + i,
      existing_date: `2026-07-0${i + 1}`,
      existing_description: `Existing ${hash}`,
    })),
  };
}

function heldHashes(state: HeldImportState): string[] | null {
  return state && state.summary.suspected_duplicates.map((s) => s.row_hash);
}

const fileA = new File(["a"], "a.csv");
const fileB = new File(["b"], "b.csv");

function openPanel(file: File, hashes: string[]): HeldImportState {
  return heldImportReducer(null, { type: "uploadSucceeded", file, summary: summaryWith(hashes) });
}

describe("heldImportReducer", () => {
  it("opens the panel when an upload holds rows, nothing selected", () => {
    const state = openPanel(fileA, ["a", "b"]);

    expect(state?.file).toBe(fileA);
    expect(heldHashes(state)).toEqual(["a", "b"]);
    expect(state?.selected.size).toBe(0);
    expect(state?.busy).toBe(false);
  });

  it("stays closed when an upload holds nothing", () => {
    expect(openPanel(fileA, [])).toBeNull();
  });

  it("toggles a row on and off without mutating the previous state", () => {
    const opened = openPanel(fileA, ["a", "b"]);

    const selected = heldImportReducer(opened, { type: "toggle", hash: "a" });
    expect([...selected!.selected]).toEqual(["a"]);
    expect(selected!.busy).toBe(false);
    expect(opened!.selected.size).toBe(0);

    const deselected = heldImportReducer(selected, { type: "toggle", hash: "a" });
    expect(deselected!.selected.size).toBe(0);
    expect([...selected!.selected]).toEqual(["a"]);
  });

  it("ignores toggle when no panel is open", () => {
    expect(heldImportReducer(null, { type: "toggle", hash: "a" })).toBeNull();
  });

  it("marks the panel busy on retry and keeps the selection", () => {
    const selected = heldImportReducer(openPanel(fileA, ["a", "b"]), { type: "toggle", hash: "a" });

    const busy = heldImportReducer(selected, { type: "retryStarted" });

    expect(busy?.busy).toBe(true);
    expect([...busy!.selected]).toEqual(["a"]);
  });

  it("replaces the held list wholesale after a successful retry and clears the selection", () => {
    let state = openPanel(fileA, ["a", "b"]);
    state = heldImportReducer(state, { type: "toggle", hash: "a" });
    state = heldImportReducer(state, { type: "retryStarted" });

    state = heldImportReducer(state, { type: "retrySucceeded", file: fileA, summary: summaryWith(["b", "c"]) });

    expect(heldHashes(state)).toEqual(["b", "c"]);
    expect(state?.file).toBe(fileA);
    expect(state?.selected.size).toBe(0);
    expect(state?.busy).toBe(false);
  });

  it("closes the panel when a retry leaves nothing held", () => {
    let state = openPanel(fileA, ["a"]);
    state = heldImportReducer(state, { type: "retryStarted" });

    state = heldImportReducer(state, { type: "retrySucceeded", file: fileA, summary: summaryWith([]) });

    expect(state).toBeNull();
  });

  it("keeps the panel and selection when a retry fails", () => {
    let state = openPanel(fileA, ["a", "b"]);
    state = heldImportReducer(state, { type: "toggle", hash: "a" });
    state = heldImportReducer(state, { type: "retryStarted" });

    state = heldImportReducer(state, { type: "retryFailed", file: fileA });

    expect(heldHashes(state)).toEqual(["a", "b"]);
    expect([...state!.selected]).toEqual(["a"]);
    expect(state?.busy).toBe(false);
  });

  it("closes the panel on dismiss, with or without a selection", () => {
    const opened = openPanel(fileA, ["a"]);
    const selected = heldImportReducer(opened, { type: "toggle", hash: "a" });

    expect(heldImportReducer(opened, { type: "dismiss" })).toBeNull();
    expect(heldImportReducer(selected, { type: "dismiss" })).toBeNull();
  });

  it("clears the panel as soon as a new upload starts, with or without a selection", () => {
    const opened = openPanel(fileA, ["a"]);
    const selected = heldImportReducer(opened, { type: "toggle", hash: "a" });

    expect(heldImportReducer(opened, { type: "uploadStarted" })).toBeNull();
    expect(heldImportReducer(selected, { type: "uploadStarted" })).toBeNull();
  });

  it("replaces an open panel with the latest upload's response", () => {
    const state = heldImportReducer(openPanel(fileA, ["a"]), {
      type: "uploadSucceeded",
      file: fileB,
      summary: summaryWith(["x", "y"]),
    });

    expect(state?.file).toBe(fileB);
    expect(heldHashes(state)).toEqual(["x", "y"]);
  });

  it("ignores a late retry response for a file the panel no longer shows", () => {
    for (const otherFile of [fileB, new File(["a2"], "a.csv")]) {
      let state = openPanel(fileA, ["a"]);
      state = heldImportReducer(state, { type: "retryStarted" });
      state = heldImportReducer(state, { type: "uploadStarted" });
      state = heldImportReducer(state, { type: "uploadSucceeded", file: otherFile, summary: summaryWith(["x"]) });
      state = heldImportReducer(state, { type: "toggle", hash: "x" });
      const otherPanel = heldImportReducer(state, { type: "retryStarted" });

      const afterSuccess = heldImportReducer(otherPanel, {
        type: "retrySucceeded",
        file: fileA,
        summary: summaryWith(["a"]),
      });
      const afterEmptySuccess = heldImportReducer(otherPanel, {
        type: "retrySucceeded",
        file: fileA,
        summary: summaryWith([]),
      });
      const afterFailure = heldImportReducer(otherPanel, { type: "retryFailed", file: fileA });

      expect(afterSuccess).toBe(otherPanel);
      expect(afterEmptySuccess).toBe(otherPanel);
      expect(afterFailure).toBe(otherPanel);
      expect(heldHashes(afterSuccess)).toEqual(["x"]);
    }
  });

  it("ignores a late retry response after dismiss", () => {
    let state = openPanel(fileA, ["a"]);
    state = heldImportReducer(state, { type: "retryStarted" });
    state = heldImportReducer(state, { type: "dismiss" });

    expect(heldImportReducer(state, { type: "retrySucceeded", file: fileA, summary: summaryWith(["a"]) })).toBeNull();
    expect(heldImportReducer(state, { type: "retryFailed", file: fileA })).toBeNull();
  });
});

describe("retryRequest", () => {
  it("re-sends the same File with only the checked hashes", () => {
    let state = openPanel(fileA, ["a", "b", "c"]);
    state = heldImportReducer(state, { type: "toggle", hash: "c" });
    state = heldImportReducer(state, { type: "toggle", hash: "a" });

    const request = retryRequest(state!);

    expect(request.file).toBe(fileA);
    expect([...request.acceptHashes].sort()).toEqual(["a", "c"]);
  });
});
