import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createRuleFromEdit,
  deleteMerchantRule,
  fetchMerchantRules,
  fetchTransactions,
  previewRule,
  refusalMessage,
  uploadCsv,
} from "./api";

function stubFetch(body: unknown = []) {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => body });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function stubFetchError(status: number, body: unknown) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status, json: async () => body }));
}

function requestedUrl(fetchMock: ReturnType<typeof vi.fn>): URL {
  return new URL(String(fetchMock.mock.calls[0][0]));
}

describe("fetchTransactions", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requests every transaction, with no limit and no account filter", async () => {
    const fetchMock = stubFetch();

    await fetchTransactions(null);

    const url = requestedUrl(fetchMock);
    expect(url.pathname).toBe("/transactions");
    expect(url.search).toBe("");
  });

  it("passes account_id when given, still with no limit", async () => {
    const fetchMock = stubFetch();

    await fetchTransactions(7);

    const url = requestedUrl(fetchMock);
    expect(url.search).toBe("?account_id=7");
  });

  it("returns every row the server sends, untruncated", async () => {
    const rows = Array.from({ length: 1001 }, (_, i) => ({ id: i + 1 }));
    stubFetch(rows);

    const result = await fetchTransactions(null);

    expect(result).toHaveLength(1001);
    expect(result).toEqual(rows);
  });
});

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
    expect(await (form.get("file") as File).text()).toBe("a,b\n");
    expect(form.getAll("accept_hashes")).toEqual(["h1", "h2"]);
  });

  it("sends the file but no accept_hashes entry when no hashes are given", async () => {
    const fetchMock = stubFetch({});
    const file = new File(["a,b\n"], "x.csv", { type: "text/csv" });

    await uploadCsv(file);

    const form = sentForm(fetchMock);
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    expect(requestedUrl(fetchMock).pathname).toBe("/imports");
    expect(await (form.get("file") as File).text()).toBe("a,b\n");
    expect(form.has("accept_hashes")).toBe(false);
  });

  it("returns the server's summary", async () => {
    const summary = { filename: "x.csv", rows_seen: 3 };
    stubFetch(summary);

    expect(await uploadCsv(new File(["a"], "x.csv"))).toEqual(summary);
  });

  it("rejects with the server's detail when the server responds with an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 400, json: async () => ({ detail: "bad file" }) })
    );

    await expect(uploadCsv(new File(["a"], "x.csv"))).rejects.toThrow("bad file");
  });
});

describe("refusalMessage", () => {
  it("reads message from a {code, message} detail", () => {
    expect(
      refusalMessage({ detail: { code: "conflict", message: "An existing rule already names this transaction" } }, "x")
    ).toBe("An existing rule already names this transaction");
  });

  it("uses a string detail as is", () => {
    expect(refusalMessage({ detail: "Merchant rule 9 not found" }, "x")).toBe("Merchant rule 9 not found");
  });

  it("falls back for FastAPI validation errors (array detail)", () => {
    expect(refusalMessage({ detail: [{ loc: ["body", "match_pattern"], msg: "blank" }] }, "Preview failed")).toBe(
      "Preview failed"
    );
  });

  it("falls back when there is no detail", () => {
    expect(refusalMessage({}, "Preview failed")).toBe("Preview failed");
  });
});

describe("previewRule", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

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
    stubFetchError(409, {
      detail: { code: "source_category_changed", message: "This transaction's category changed since the rule was suggested" },
    });

    await expect(previewRule(request)).rejects.toThrow("This transaction's category changed since the rule was suggested");
  });

  it("rejects a FastAPI validation error (422, array detail) with the fallback message", async () => {
    stubFetchError(422, { detail: [{ loc: ["body", "match_pattern"], msg: "blank" }] });

    await expect(previewRule(request)).rejects.toThrow("Rule preview failed");
  });
});

describe("createRuleFromEdit", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const request = {
    source_transaction_id: 971,
    match_pattern: "DD *DOORDASH",
    clean_name: "DoorDash",
    category_id: 7,
    this_account_only: true,
  };

  it("posts the request as JSON to /merchant-rules", async () => {
    const fetchMock = stubFetch({ id: 77 });

    await createRuleFromEdit(request);

    expect(requestedUrl(fetchMock).pathname).toBe("/merchant-rules");
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    expect(fetchMock.mock.calls[0][1].headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual(request);
  });

  it("returns the saved rule", async () => {
    stubFetch({ id: 77, match_pattern: "DD *DOORDASH" });

    expect(await createRuleFromEdit(request)).toEqual({ id: 77, match_pattern: "DD *DOORDASH" });
  });

  it("rejects a 400 refusal with its message", async () => {
    stubFetchError(400, { detail: { code: "pattern_not_matching_source", message: "The pattern doesn't match this transaction" } });

    await expect(createRuleFromEdit(request)).rejects.toThrow("The pattern doesn't match this transaction");
  });

  it("rejects with the refusal message, not [object Object]", async () => {
    stubFetchError(409, {
      detail: {
        code: "category_mismatch",
        message: "Some transactions this rule would match are in a different category",
        count: 30,
        sample: [],
      },
    });

    await expect(createRuleFromEdit(request)).rejects.toThrow(
      "Some transactions this rule would match are in a different category"
    );
  });
});

describe("merchant rules", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetchMerchantRules GETs /merchant-rules and returns the list", async () => {
    const rows = [{ id: 1, match_pattern: "X", clean_name: "X", category_id: null, account_id: null, match_count: 2 }];
    const fetchMock = stubFetch(rows);

    const result = await fetchMerchantRules();

    expect(requestedUrl(fetchMock).pathname).toBe("/merchant-rules");
    expect(fetchMock.mock.calls[0][1]).toBeUndefined();
    expect(result).toEqual(rows);
  });

  it("deleteMerchantRule sends DELETE and reports a 204 as deleted", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 });
    vi.stubGlobal("fetch", fetchMock);

    expect(await deleteMerchantRule(53)).toBe("deleted");
    expect(requestedUrl(fetchMock).pathname).toBe("/merchant-rules/53");
    expect(fetchMock.mock.calls[0][1]).toEqual({ method: "DELETE" });
  });

  it("deleteMerchantRule reports a 404 as already deleted", async () => {
    stubFetchError(404, { detail: "Merchant rule 53 not found" });

    expect(await deleteMerchantRule(53)).toBe("already_deleted");
  });

  it("deleteMerchantRule throws on any other error status", async () => {
    stubFetchError(500, {});

    await expect(deleteMerchantRule(53)).rejects.toThrow("Deleting rule #53 failed (500)");
  });
});
