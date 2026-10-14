import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchTransactions, uploadCsv } from "./api";

function stubFetch(body: unknown = []) {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => body });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
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
    expect(form.getAll("accept_hashes")).toEqual(["h1", "h2"]);
  });

  it("sends no accept_hashes entry when no hashes are given", async () => {
    const fetchMock = stubFetch({});
    const file = new File(["a,b\n"], "x.csv", { type: "text/csv" });

    await uploadCsv(file);

    expect(sentForm(fetchMock).has("accept_hashes")).toBe(false);
  });
});
