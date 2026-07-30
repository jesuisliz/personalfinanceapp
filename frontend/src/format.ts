import type { Account, Category, Transaction } from "./api";

export function formatAmount(cents: number): string {
  return (cents / 100).toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export function formatRelativeTime(isoString: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(isoString).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = seconds / 60;
  if (minutes < 60) return `${Math.floor(minutes)}m ago`;
  const hours = minutes / 60;
  if (hours < 24) return `${Math.floor(hours)}h ago`;
  const days = hours / 24;
  if (days < 7) return `${Math.floor(days)}d ago`;
  return new Date(isoString).toLocaleDateString("en-US", { month: "short", day: "numeric" });
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
