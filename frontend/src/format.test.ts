import { describe, expect, it } from "vitest";
import { transactionsToCsv } from "./format";
import type { Account, Category, Transaction } from "./api";

function makeTransaction(overrides: Partial<Transaction> = {}): Transaction {
  return {
    id: 1,
    account_id: 1,
    date: "2026-07-01",
    posted_date: null,
    description: "raw desc",
    amount_cents: -1234,
    raw_category: null,
    memo: null,
    category_id: null,
    clean_description: null,
    is_transfer: false,
    note: null,
    ...overrides,
  };
}

const accountById = new Map<number, Account>([
  [1, { id: 1, name: "Checking", institution: "BOA", account_type: "checking" }],
]);
const categoryById = new Map<number, Category>([
  [5, { id: 5, name: "Dining & Drinks", parent_id: null }],
]);

describe("transactionsToCsv", () => {
  it("escapes commas and quotes in free-text fields", () => {
    const txn = makeTransaction({
      clean_description: 'Some Store, "Downtown"',
      category_id: 5,
      note: "lunch w/ friend",
    });

    const csv = transactionsToCsv([txn], accountById, categoryById);
    const [header, row] = csv.split("\r\n");

    expect(header).toBe("Date,Account,Description,Category,Note,Amount");
    expect(row).toBe(
      '2026-07-01,Checking,"Some Store, ""Downtown""",Dining & Drinks,lunch w/ friend,-$12.34'
    );
  });

  it("renders blank fields for an uncategorized transaction with no note", () => {
    const txn = makeTransaction({ description: "Plain Merchant" });

    const csv = transactionsToCsv([txn], accountById, categoryById);
    const [, row] = csv.split("\r\n");

    expect(row).toBe("2026-07-01,Checking,Plain Merchant,,,-$12.34");
  });
});
