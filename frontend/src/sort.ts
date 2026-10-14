import type { Transaction } from "./api";

export type SortKey = "date" | "amount";
export type SortDirection = "asc" | "desc";

type Comparator = (a: Transaction, b: Transaction) => number;

const byDate: Comparator = (a, b) => a.date.localeCompare(b.date);
const byAmount: Comparator = (a, b) => a.amount_cents - b.amount_cents;
const byId: Comparator = (a, b) => a.id - b.id;

// Tie-break order per key: amount ties fall back to date, then id; date ties to id.
const COMPARATORS: Record<SortKey, Comparator[]> = {
  date: [byDate, byId],
  amount: [byAmount, byDate, byId],
};

/**
 * Return a new array sorted by `key`, with every tie-break applied in the same direction so the
 * order is deterministic and reverses cleanly. Amount sorts on the signed value (expenses are
 * negative), so ascending puts the biggest expenses first. Does not mutate the input.
 */
export function sortTransactions(transactions: Transaction[], key: SortKey, direction: SortDirection): Transaction[] {
  const sign = direction === "asc" ? 1 : -1;
  const comparators = COMPARATORS[key];
  return [...transactions].sort((a, b) => {
    for (const compare of comparators) {
      const result = compare(a, b);
      if (result !== 0) return sign * result;
    }
    return 0;
  });
}
