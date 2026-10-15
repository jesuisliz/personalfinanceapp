import { describe, expect, it } from "vitest";
import type { Account, Category, MerchantRuleListItem } from "./api";
import { filterRules, ruleCategoryLabel, ruleScopeLabel, sortRulesNewestFirst } from "./merchantRules";

const categories: Category[] = [{ id: 4, name: "Dining Out", parent_id: null }];
const accounts: Account[] = [{ id: 8, name: "American Express", institution: "American Express", account_type: "credit_card" }];

function rule(overrides: Partial<MerchantRuleListItem>): MerchantRuleListItem {
  return { id: 1, match_pattern: "PATTERN", clean_name: "Name", category_id: null, account_id: null, match_count: 0, ...overrides };
}

const kura = rule({ id: 2, match_pattern: "SQ *KURA", clean_name: "Kura Sushi", category_id: 4 });
const amex = rule({ id: 10, match_pattern: "AUTOPAY PMT", clean_name: "Card Payment", account_id: 8 });
const orphan = rule({ id: 3, match_pattern: "OLD", clean_name: "Old", category_id: 99, account_id: 42 });
const all = [kura, amex, orphan];

describe("rule labels", () => {
  it("names a known category, '-' for none, and the id for an unknown one", () => {
    expect(ruleCategoryLabel(kura, categories)).toBe("Dining Out");
    expect(ruleCategoryLabel(amex, categories)).toBe("-");
    expect(ruleCategoryLabel(orphan, categories)).toBe("Unknown category #99");
  });

  it("names the account, 'All accounts' for a global rule, and the id for an unknown one", () => {
    expect(ruleScopeLabel(amex, accounts)).toBe("American Express");
    expect(ruleScopeLabel(kura, accounts)).toBe("All accounts");
    expect(ruleScopeLabel(orphan, accounts)).toBe("Unknown account #42");
  });
});

describe("filterRules", () => {
  const ids = (query: string) => filterRules(all, query, categories, accounts).map((r) => r.id);

  it.each([
    ["pattern, mid-string, mixed-case query", "oPAY p", [10]],
    ["clean name, mid-string", "rd paym", [10]],
    ["clean name, mid-string", "SUSH", [2]],
    ["category label, mid-string", "ning ou", [2]],
    ["scope label, mid-string", "xpress", [10]],
    ["'All accounts' label", "all acc", [2]],
    ["unknown category label", "unknown category", [3]],
    ["unknown account label", "account #42", [3]],
    ["regex characters taken literally", "sq *k", [2]],
  ])("matches on %s", (_label, query, expected) => {
    expect(ids(query as string)).toEqual(expected);
  });

  it("returns every rule for an empty or whitespace-only query", () => {
    expect(ids("")).toEqual([2, 10, 3]);
    expect(ids("   ")).toEqual([2, 10, 3]);
  });

  it("returns nothing when no field matches", () => {
    expect(ids("zzz")).toEqual([]);
  });
});

describe("sortRulesNewestFirst", () => {
  it("sorts by numeric id, highest first, without mutating the input", () => {
    const input = [kura, amex, orphan];
    expect(sortRulesNewestFirst(input).map((r) => r.id)).toEqual([10, 3, 2]);
    expect(input.map((r) => r.id)).toEqual([2, 10, 3]);
  });
});
