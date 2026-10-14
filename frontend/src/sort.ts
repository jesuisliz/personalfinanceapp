import type { Transaction } from "./api";

export type SortDirection = "asc" | "desc";

/**
 * Return a new array sorted by date, tie-broken by id in the same direction so
 * same-day rows have a stable order that reverses cleanly. Does not mutate the input.
 */
export function sortTransactionsByDate(transactions: Transaction[], direction: SortDirection): Transaction[] {
  const sign = direction === "asc" ? 1 : -1;
  return [...transactions].sort((a, b) => {
    const byDate = a.date.localeCompare(b.date);
    return sign * (byDate !== 0 ? byDate : a.id - b.id);
  });
}
