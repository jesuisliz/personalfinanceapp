import { describe, expect, it } from "vitest";
import { sortTransactions } from "./sort";
import type { Transaction } from "./api";

function makeTransaction(id: number, date: string, amountCents = -100): Transaction {
  return {
    id,
    account_id: 1,
    date,
    posted_date: null,
    description: "desc",
    amount_cents: amountCents,
    raw_category: null,
    memo: null,
    category_id: null,
    clean_description: null,
    is_transfer: false,
    note: null,
  };
}

const ids = (transactions: Transaction[]) => transactions.map((t) => t.id);

describe("sortTransactions by date", () => {
  // Ids deliberately don't follow date order (as in real data), even within one year or month,
  // so sorting by id, year or month alone fails.
  const unordered = () => [
    makeTransaction(5, "2026-07-02"),
    makeTransaction(8, "2025-12-30"),
    makeTransaction(3, "2026-07-02"),
    makeTransaction(9, "2026-01-15"),
    makeTransaction(7, "2026-07-02"),
    makeTransaction(1, "2026-07-19"),
  ];

  it("sorts newest first, same-day rows by id descending", () => {
    expect(ids(sortTransactions(unordered(), "date", "desc"))).toEqual([1, 7, 5, 3, 9, 8]);
  });

  it("sorts oldest first, same-day rows by id ascending", () => {
    expect(ids(sortTransactions(unordered(), "date", "asc"))).toEqual([8, 9, 3, 5, 7, 1]);
  });
});

describe("sortTransactions input handling", () => {
  it.each(["date", "amount"] as const)("does not mutate its input when sorting by %s", (key) => {
    const input = [
      makeTransaction(1, "2026-01-01", -500),
      makeTransaction(2, "2026-03-01", 900),
      makeTransaction(3, "2026-02-01", -100),
    ];
    sortTransactions(input, key, "asc");
    sortTransactions(input, key, "desc");
    expect(ids(input)).toEqual([1, 2, 3]);
  });
});

describe("sortTransactions by amount", () => {
  // Ids and dates don't follow amount order; the -$400 expense and +$400 income share a magnitude,
  // so sorting by absolute value fails; -$15.99 and -$15.50 differ only in cents, with dates in the
  // opposite order, so comparing whole dollars fails.
  const mixed = [
    makeTransaction(1, "2026-03-01", 40000),
    makeTransaction(2, "2026-01-01", -300),
    makeTransaction(3, "2026-05-01", -40000),
    makeTransaction(4, "2026-02-01", 5000),
    makeTransaction(5, "2026-04-01", -1599),
    makeTransaction(6, "2026-03-15", -1550),
  ];

  it("ascending puts the biggest expenses first and the biggest income last", () => {
    expect(ids(sortTransactions(mixed, "amount", "asc"))).toEqual([3, 5, 6, 2, 4, 1]);
  });

  it("descending puts the biggest income first and the biggest expenses last", () => {
    expect(ids(sortTransactions(mixed, "amount", "desc"))).toEqual([1, 4, 2, 6, 5, 3]);
  });

  it("breaks amount ties by full date, then id, in the same direction", () => {
    // Id 50 is in February like 20 and 30 but on an earlier day, so a month-only tie-break fails.
    const subscriptions = [
      makeTransaction(30, "2026-02-15", -1599),
      makeTransaction(10, "2026-03-15", -1599),
      makeTransaction(20, "2026-02-15", -1599),
      makeTransaction(40, "2026-01-15", -1599),
      makeTransaction(50, "2026-02-03", -1599),
    ];
    expect(ids(sortTransactions(subscriptions, "amount", "asc"))).toEqual([40, 50, 20, 30, 10]);
    expect(ids(sortTransactions(subscriptions, "amount", "desc"))).toEqual([10, 30, 20, 50, 40]);
  });
});
