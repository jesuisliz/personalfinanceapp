import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchTransactions } from "./api";

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
