import type { Account, Category, MerchantRule, MerchantRuleListItem } from "./api";

/** The rule's category name, "-" when it sets none, or the id when the category no longer exists. */
export function ruleCategoryLabel(rule: MerchantRule, categories: Category[]): string {
  if (rule.category_id === null) return "-";
  return categories.find((c) => c.id === rule.category_id)?.name ?? `Unknown category #${rule.category_id}`;
}

/** "All accounts" for a global rule, else the account name, or the id when the account no longer exists. */
export function ruleScopeLabel(rule: MerchantRule, accounts: Account[]): string {
  if (rule.account_id === null) return "All accounts";
  return accounts.find((a) => a.id === rule.account_id)?.name ?? `Unknown account #${rule.account_id}`;
}

/** Rules where any of pattern, clean name, category label or scope label contains the query (plain text, any case). */
export function filterRules(
  rules: MerchantRuleListItem[],
  query: string,
  categories: Category[],
  accounts: Account[]
): MerchantRuleListItem[] {
  const needle = query.trim().toLowerCase();
  if (needle === "") return rules;
  return rules.filter((rule) =>
    [rule.match_pattern, rule.clean_name, ruleCategoryLabel(rule, categories), ruleScopeLabel(rule, accounts)].some(
      (field) => field.toLowerCase().includes(needle)
    )
  );
}

/** A new array, highest id first: the rule just created is the one most likely to need checking. */
export function sortRulesNewestFirst(rules: MerchantRuleListItem[]): MerchantRuleListItem[] {
  return [...rules].sort((a, b) => b.id - a.id);
}
