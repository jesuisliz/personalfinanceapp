const API_BASE = "http://localhost:8000";

export interface Account {
  id: number;
  name: string;
  institution: string;
  account_type: string;
}

export interface Transaction {
  id: number;
  account_id: number;
  date: string;
  posted_date: string | null;
  description: string;
  amount_cents: number;
  raw_category: string | null;
  memo: string | null;
  category_id: number | null;
  clean_description: string | null;
  is_transfer: boolean;
  note: string | null;
}

export interface Category {
  id: number;
  name: string;
  parent_id: number | null;
}

export interface TransferMatch {
  id: number;
  transaction_id_a: number;
  transaction_id_b: number;
  status: string;
}

export interface SuspectedDuplicate {
  row_hash: string;
  account_name: string;
  date: string;
  description: string;
  amount_cents: number;
  existing_id: number;
  existing_date: string;
  existing_description: string;
}

export interface ImportSummary {
  filename: string;
  rows_seen: number;
  rows_inserted: number;
  rows_skipped_as_duplicate: number;
  rows_held_as_suspected_duplicate: number;
  suspected_duplicates: SuspectedDuplicate[];
}

export interface RuleConflict {
  id: number;
  match_pattern: string;
  clean_name: string;
  category_id: number | null;
  account_id: number | null;
}

export type MerchantRule = RuleConflict;

export interface RuleSampleRow {
  id: number;
  date: string;
  description: string;
  category_name: string | null;
}

export interface RulePreview {
  match_pattern: string;
  matches_source: boolean;
  conflicting_rule: RuleConflict | null;
  would_name_count: number;
  would_categorize_count: number;
  category_mismatch_count: number;
  sample: RuleSampleRow[];
}

export interface RulePreviewRequest {
  source_transaction_id: number;
  match_pattern: string | null;
  category_id: number;
  this_account_only: boolean;
}

export interface RuleFromEditRequest {
  source_transaction_id: number;
  match_pattern: string;
  clean_name: string;
  category_id: number;
  this_account_only: boolean;
}

export interface MonthlySummary {
  month: string;
  income_cents: number;
  expense_cents: number;
  net_cents: number;
}

export interface CategoryBreakdown {
  category_id: number | null;
  category_name: string;
  total_cents: number;
}

export interface MerchantBreakdown {
  merchant: string;
  total_cents: number;
  transaction_count: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ToolCall {
  name: string;
  arguments: Record<string, unknown>;
  result: unknown;
}

export interface ChatReply {
  reply: string;
  tool_calls: ToolCall[];
  conversation_id: number;
}

export interface ChatHistoryMessage {
  role: "user" | "assistant";
  content: string;
  tool_calls: ToolCall[];
}

export interface ChatConversationSummary {
  id: number;
  title: string;
  updated_at: string;
}

export interface SavingsGoal {
  id: number;
  name: string;
  target_amount_cents: number;
  target_date: string | null;
  saved_so_far_cents: number;
}

export interface CurrentBalance {
  configured: boolean;
  amount_cents: number | null;
  updated_at: string | null;
}

export interface RunwayResult {
  balance_configured: boolean;
  current_balance_cents: number | null;
  avg_monthly_expense_cents: number;
  runway_months: number | null;
  projected_end_date: string | null;
}

export interface GoalProjection {
  goal_id: number;
  status: "on_track" | "not_on_track" | "already_met";
  avg_monthly_net_savings_cents: number;
  remaining_cents: number;
  months_to_goal: number | null;
  projected_date: string | null;
}

export interface ScenarioResult {
  savings_estimate: {
    avg_monthly_cents: number;
    monthly_savings_cents: number;
    annual_savings_cents: number;
    months_considered: number;
  };
  runway: RunwayResult | null;
  goal_projection: GoalProjection | null;
}

async function asJson(res: Response, errorMessage: string) {
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? errorMessage);
  return body;
}

/** The text to show for an error response: a string detail, a {code, message} detail's message, else the fallback. */
export function refusalMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") {
    return detail.message;
  }
  return fallback;
}

async function asJsonOrRefusal(res: Response, errorMessage: string) {
  const body = await res.json();
  if (!res.ok) throw new Error(refusalMessage(body, errorMessage));
  return body;
}

export async function fetchAccounts(): Promise<Account[]> {
  const res = await fetch(`${API_BASE}/accounts`);
  if (!res.ok) throw new Error("Failed to load accounts");
  return res.json();
}

export async function fetchTransactions(accountId: number | null): Promise<Transaction[]> {
  const url = new URL(`${API_BASE}/transactions`);
  if (accountId !== null) url.searchParams.set("account_id", String(accountId));
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to load transactions");
  return res.json();
}

export async function updateTransaction(
  id: number,
  updates: { category_id?: number | null; clean_description?: string | null; is_transfer?: boolean; note?: string | null }
): Promise<Transaction> {
  const res = await fetch(`${API_BASE}/transactions/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  return asJson(res, "Failed to update transaction");
}

export async function uploadCsv(file: File, acceptHashes: string[] = []): Promise<ImportSummary> {
  const formData = new FormData();
  formData.append("file", file);
  for (const hash of acceptHashes) formData.append("accept_hashes", hash);
  const res = await fetch(`${API_BASE}/imports`, { method: "POST", body: formData });
  return asJson(res, "Import failed");
}

export async function fetchCategories(): Promise<Category[]> {
  const res = await fetch(`${API_BASE}/categories`);
  if (!res.ok) throw new Error("Failed to load categories");
  return res.json();
}

export async function fetchSuggestedTransferMatches(): Promise<TransferMatch[]> {
  const res = await fetch(`${API_BASE}/transfer-matches?status=suggested`);
  if (!res.ok) throw new Error("Failed to load transfer matches");
  return res.json();
}

export async function detectTransfers(): Promise<TransferMatch[]> {
  const res = await fetch(`${API_BASE}/transfer-matches/detect`, { method: "POST" });
  return asJson(res, "Transfer detection failed");
}

export async function updateTransferMatch(id: number, status: "confirmed" | "rejected"): Promise<TransferMatch> {
  const res = await fetch(`${API_BASE}/transfer-matches/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  return asJson(res, "Failed to update transfer match");
}

/** What a rule remembered from a category edit would do. Read-only on the server. */
export async function previewRule(request: RulePreviewRequest): Promise<RulePreview> {
  const res = await fetch(`${API_BASE}/merchant-rules/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return asJsonOrRefusal(res, "Rule preview failed");
}

/** Save a rule remembered from a category edit; the server refuses unsafe rules. */
export async function createRuleFromEdit(request: RuleFromEditRequest): Promise<MerchantRule> {
  const res = await fetch(`${API_BASE}/merchant-rules`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return asJsonOrRefusal(res, "Saving the rule failed");
}

export type MerchantRuleListItem = MerchantRule & { match_count: number };

export async function fetchMerchantRules(): Promise<MerchantRuleListItem[]> {
  const res = await fetch(`${API_BASE}/merchant-rules`);
  if (!res.ok) throw new Error("Failed to load rules");
  return res.json();
}

/** Delete a rule. A 404 means it was already gone, which isn't an error for the Rules tab. */
export async function deleteMerchantRule(id: number): Promise<"deleted" | "already_deleted"> {
  const res = await fetch(`${API_BASE}/merchant-rules/${id}`, { method: "DELETE" });
  if (res.status === 404) return "already_deleted";
  if (!res.ok) throw new Error(`Deleting rule #${id} failed (${res.status})`);
  return "deleted";
}

export async function fetchMonthlySummary(months: number, accountId: number | null): Promise<MonthlySummary[]> {
  const url = new URL(`${API_BASE}/dashboard/monthly`);
  url.searchParams.set("months", String(months));
  if (accountId !== null) url.searchParams.set("account_id", String(accountId));
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to load monthly summary");
  return res.json();
}

export async function fetchCategoryBreakdown(
  month: string | null,
  accountId: number | null
): Promise<CategoryBreakdown[]> {
  const url = new URL(`${API_BASE}/dashboard/categories`);
  if (month !== null) url.searchParams.set("month", month);
  if (accountId !== null) url.searchParams.set("account_id", String(accountId));
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to load category breakdown");
  return res.json();
}

export async function fetchTopMerchants(
  month: string | null,
  accountId: number | null,
  limit = 10
): Promise<MerchantBreakdown[]> {
  const url = new URL(`${API_BASE}/dashboard/merchants`);
  if (month !== null) url.searchParams.set("month", month);
  url.searchParams.set("limit", String(limit));
  if (accountId !== null) url.searchParams.set("account_id", String(accountId));
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to load top merchants");
  return res.json();
}

export async function fetchCategoryTransactions(
  month: string | null,
  accountId: number | null,
  categoryId: number | null
): Promise<Transaction[]> {
  const url = new URL(`${API_BASE}/dashboard/categories/transactions`);
  if (month !== null) url.searchParams.set("month", month);
  if (accountId !== null) url.searchParams.set("account_id", String(accountId));
  if (categoryId === null) {
    url.searchParams.set("uncategorized", "true");
  } else {
    url.searchParams.set("category_id", String(categoryId));
  }
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to load category transactions");
  return res.json();
}

export async function fetchIncomeBreakdown(
  month: string | null,
  accountId: number | null
): Promise<CategoryBreakdown[]> {
  const url = new URL(`${API_BASE}/dashboard/income-categories`);
  if (month !== null) url.searchParams.set("month", month);
  if (accountId !== null) url.searchParams.set("account_id", String(accountId));
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to load income breakdown");
  return res.json();
}

export async function fetchIncomeTransactions(
  month: string | null,
  accountId: number | null,
  categoryId: number | null
): Promise<Transaction[]> {
  const url = new URL(`${API_BASE}/dashboard/income-categories/transactions`);
  if (month !== null) url.searchParams.set("month", month);
  if (accountId !== null) url.searchParams.set("account_id", String(accountId));
  if (categoryId === null) {
    url.searchParams.set("uncategorized", "true");
  } else {
    url.searchParams.set("category_id", String(categoryId));
  }
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to load income transactions");
  return res.json();
}

export async function sendChatMessage(
  message: string,
  history: ChatMessage[],
  conversationId: number | null
): Promise<ChatReply> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history, conversation_id: conversationId }),
  });
  return asJson(res, "Chat request failed");
}

export async function fetchConversationMessages(conversationId: number): Promise<ChatHistoryMessage[]> {
  const res = await fetch(`${API_BASE}/chat/conversations/${conversationId}/messages`);
  return asJson(res, "Failed to load conversation history");
}

export async function fetchConversations(): Promise<ChatConversationSummary[]> {
  const res = await fetch(`${API_BASE}/chat/conversations`);
  if (!res.ok) throw new Error("Failed to load conversations");
  return res.json();
}

export async function renameConversation(id: number, title: string): Promise<ChatConversationSummary> {
  const res = await fetch(`${API_BASE}/chat/conversations/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  return asJson(res, "Failed to rename conversation");
}

export async function deleteConversation(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/chat/conversations/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete conversation");
}

export async function fetchGoals(): Promise<SavingsGoal[]> {
  const res = await fetch(`${API_BASE}/goals`);
  if (!res.ok) throw new Error("Failed to load goals");
  return res.json();
}

export async function createGoal(goal: {
  name: string;
  target_amount_cents: number;
  target_date?: string | null;
  saved_so_far_cents?: number;
}): Promise<SavingsGoal> {
  const res = await fetch(`${API_BASE}/goals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(goal),
  });
  return asJson(res, "Failed to create goal");
}

export async function updateGoal(
  id: number,
  updates: Partial<{
    name: string;
    target_amount_cents: number;
    target_date: string | null;
    saved_so_far_cents: number;
  }>
): Promise<SavingsGoal> {
  const res = await fetch(`${API_BASE}/goals/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  return asJson(res, "Failed to update goal");
}

export async function deleteGoal(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/goals/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete goal");
}

export async function fetchGoalProjection(id: number, months = 6): Promise<GoalProjection> {
  const url = new URL(`${API_BASE}/goals/${id}/projection`);
  url.searchParams.set("months", String(months));
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to load goal projection");
  return res.json();
}

export async function fetchBalance(): Promise<CurrentBalance> {
  const res = await fetch(`${API_BASE}/balance`);
  if (!res.ok) throw new Error("Failed to load balance");
  return res.json();
}

export async function setBalance(amountCents: number): Promise<CurrentBalance> {
  const res = await fetch(`${API_BASE}/balance`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ amount_cents: amountCents }),
  });
  return asJson(res, "Failed to set balance");
}

export async function fetchRunway(months = 6): Promise<RunwayResult> {
  const url = new URL(`${API_BASE}/runway`);
  url.searchParams.set("months", String(months));
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to load runway");
  return res.json();
}

export async function runScenario(params: {
  category_name: string;
  reduction_percent: number;
  months: number;
  goal_id?: number | null;
}): Promise<ScenarioResult> {
  const res = await fetch(`${API_BASE}/scenario`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  return asJson(res, "Scenario request failed");
}
