import type { Account, Category, Transaction } from "./api";

export function formatAmount(cents: number): string {
  return (cents / 100).toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function csvField(value: string): string {
  if (/[",\r\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

export function transactionsToCsv(
  transactions: Transaction[],
  accountById: Map<number, Account>,
  categoryById: Map<number, Category>
): string {
  const header = ["Date", "Account", "Description", "Category", "Note", "Amount"];
  const rows = transactions.map((t) => [
    t.date,
    accountById.get(t.account_id)?.name ?? "",
    t.clean_description ?? t.description,
    t.category_id !== null ? categoryById.get(t.category_id)?.name ?? "" : "",
    t.note ?? "",
    formatAmount(t.amount_cents),
  ]);
  return [header, ...rows].map((row) => row.map(csvField).join(",")).join("\r\n");
}
