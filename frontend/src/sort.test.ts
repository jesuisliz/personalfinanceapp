import { describe, expect, it } from "vitest";
import { sortTransactionsByDate } from "./sort";
import type { Transaction } from "./api";

function makeTransaction(id: number, date: string): Transaction {
  return {
    id,
    account_id: 1,
    date,
    posted_date: null,
    description: "desc",
    amount_cents: -100,
    raw_category: null,
    memo: null,
    category_id: null,
    clean_description: null,
    is_transfer: false,
    note: null,
  };
}

// Ids deliberately don't follow date order (as in real data), so sorting by id alone fails.
const unordered = [
  makeTransaction(5, "2026-07-02"),
  makeTransaction(8, "2025-12-30"),
  makeTransaction(9, "2026-07-02"),
  makeTransaction(2, "2026-01-15"),
  makeTransaction(7, "2026-07-02"),
];

const ids = (transactions: Transaction[]) => transactions.map((t) => t.id);

describe("sortTransactionsByDate", () => {
  it("sorts newest first, same-day rows by id descending", () => {
    expect(ids(sortTransactionsByDate(unordered, "desc"))).toEqual([9, 7, 5, 2, 8]);
  });

  it("sorts oldest first, same-day rows by id ascending", () => {
    expect(ids(sortTransactionsByDate(unordered, "asc"))).toEqual([8, 2, 5, 7, 9]);
  });

  it("does not mutate its input", () => {
    const before = ids(unordered);
    sortTransactionsByDate(unordered, "asc");
    expect(ids(unordered)).toEqual(before);
  });
});
