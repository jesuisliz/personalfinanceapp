import { useEffect, useState } from "react";
import {
  fetchAccounts,
  fetchCategories,
  fetchSuggestedTransferMatches,
  fetchTransactions,
  detectTransfers,
  updateTransaction,
  updateTransferMatch,
  uploadCsv,
  type Account,
  type Category,
  type Transaction,
  type TransferMatch,
} from "./api";
import { formatAmount, transactionsToCsv } from "./format";
import Dashboard from "./Dashboard";
import Chat from "./Chat";
import Planning from "./Planning";
import { Card, SecondaryButton, inputClass } from "./ui";
import { categoryDotColor } from "./categoryColor";
import {
  IconBarChart,
  IconCheck,
  IconCompass,
  IconDownload,
  IconList,
  IconMessageCircle,
  IconTransfer,
  IconUpload,
  IconX,
} from "./icons";

const TABS = [
  { key: "transactions", label: "Transactions", icon: IconList },
  { key: "dashboard", label: "Dashboard", icon: IconBarChart },
  { key: "chat", label: "Chat", icon: IconMessageCircle },
  { key: "planning", label: "Planning", icon: IconCompass },
] as const;

type View = (typeof TABS)[number]["key"];

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function monthLabel(monthKey: string): string {
  const [year, month] = monthKey.split("-");
  return `${MONTH_NAMES[Number(month) - 1]} ${year}`;
}

function TransactionSummary({ txn, account }: { txn: Transaction; account: Account | undefined }) {
  return (
    <div className="text-sm">
      <div className="text-ink-muted">{txn.date} &middot; {account?.name ?? txn.account_id}</div>
      <div className="text-ink">{txn.clean_description ?? txn.description}</div>
      <div className={txn.amount_cents < 0 ? "text-critical" : "text-good"}>
        {formatAmount(txn.amount_cents)}
      </div>
    </div>
  );
}

export default function App() {
  const [view, setView] = useState<View>("transactions");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [allTransactions, setAllTransactions] = useState<Transaction[]>([]);
  const [transferMatches, setTransferMatches] = useState<TransferMatch[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [selectedCategoryId, setSelectedCategoryId] = useState<number | null>(null);
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null);
  const [merchantSearch, setMerchantSearch] = useState("");
  const [minAmount, setMinAmount] = useState("");
  const [maxAmount, setMaxAmount] = useState("");
  const [uncategorizedOnly, setUncategorizedOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const [editingDescriptionId, setEditingDescriptionId] = useState<number | null>(null);
  const [editingValue, setEditingValue] = useState("");
  const [editingNoteId, setEditingNoteId] = useState<number | null>(null);
  const [editingNoteValue, setEditingNoteValue] = useState("");

  function reload() {
    setLoading(true);
    setError(null);
    Promise.all([fetchAccounts(), fetchCategories(), fetchTransactions(null), fetchSuggestedTransferMatches()])
      .then(([accountsResult, categoriesResult, transactionsResult, matchesResult]) => {
        setAccounts(accountsResult);
        setCategories(categoriesResult);
        setAllTransactions(transactionsResult);
        setTransferMatches(matchesResult);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(reload, []);

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadStatus(`Importing ${file.name}...`);
    try {
      const summary = await uploadCsv(file);
      setUploadStatus(
        `${summary.filename}: ${summary.rows_inserted} new, ${summary.rows_skipped_as_duplicate} already imported`
      );
      reload();
    } catch (err) {
      setUploadStatus(`Failed to import ${file.name}: ${String(err)}`);
    } finally {
      e.target.value = "";
    }
  }

  async function handleCategoryChange(txnId: number, value: string) {
    await updateTransaction(txnId, { category_id: value === "" ? null : Number(value) });
    reload();
  }

  function startEditingDescription(txn: Transaction) {
    setEditingDescriptionId(txn.id);
    setEditingValue(txn.clean_description ?? txn.description);
  }

  async function saveDescription(txnId: number) {
    await updateTransaction(txnId, { clean_description: editingValue.trim() || null });
    setEditingDescriptionId(null);
    reload();
  }

  function startEditingNote(txn: Transaction) {
    setEditingNoteId(txn.id);
    setEditingNoteValue(txn.note ?? "");
  }

  async function saveNote(txnId: number) {
    await updateTransaction(txnId, { note: editingNoteValue.trim() || null });
    setEditingNoteId(null);
    reload();
  }

  async function handleDetectTransfers() {
    setUploadStatus("Detecting transfers...");
    const found = await detectTransfers();
    setUploadStatus(`Found ${found.length} new possible transfer${found.length === 1 ? "" : "s"} to review`);
    reload();
  }

  async function handleTransferDecision(matchId: number, status: "confirmed" | "rejected") {
    await updateTransferMatch(matchId, status);
    reload();
  }

  function handleExportCsv() {
    const csv = transactionsToCsv(visibleTransactions, accountById, categoryById);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `transactions_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const accountById = new Map(accounts.map((a) => [a.id, a]));
  const categoryById = new Map(categories.map((c) => [c.id, c]));
  const transactionById = new Map(allTransactions.map((t) => [t.id, t]));
  const availableMonths = Array.from(new Set(allTransactions.map((t) => t.date.slice(0, 7)))).sort(
    (a, b) => (a < b ? 1 : -1)
  );
  const merchantSearchLower = merchantSearch.trim().toLowerCase();
  const minAmountCents = minAmount.trim() === "" ? null : Math.round(Number(minAmount) * 100);
  const maxAmountCents = maxAmount.trim() === "" ? null : Math.round(Number(maxAmount) * 100);
  const visibleTransactions = allTransactions
    .filter((t) => selectedAccountId === null || t.account_id === selectedAccountId)
    .filter((t) => !uncategorizedOnly || t.category_id === null)
    .filter((t) => selectedCategoryId === null || t.category_id === selectedCategoryId)
    .filter((t) => selectedMonth === null || t.date.slice(0, 7) === selectedMonth)
    .filter(
      (t) => merchantSearchLower === "" || (t.clean_description ?? t.description).toLowerCase().includes(merchantSearchLower)
    )
    .filter((t) => minAmountCents === null || Number.isNaN(minAmountCents) || t.amount_cents >= minAmountCents)
    .filter((t) => maxAmountCents === null || Number.isNaN(maxAmountCents) || t.amount_cents <= maxAmountCents);

  return (
    <div className="min-h-screen bg-canvas text-ink">
      <div className="max-w-5xl mx-auto p-6">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-8">
          <div className="flex items-center gap-2">
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-accent shadow-[0_0_12px_var(--color-accent)]" />
            <h1 className="text-xl font-semibold tracking-tight">Ledger</h1>
          </div>

          <div className="flex bg-surface border border-hairline rounded-xl p-1 text-sm font-medium gap-1">
            {TABS.map((t) => {
              const TabIcon = t.icon;
              return (
                <button
                  key={t.key}
                  className={`px-3 py-1.5 rounded-lg transition-colors ${
                    view === t.key
                      ? "bg-accent text-canvas"
                      : "text-ink-secondary hover:text-ink hover:bg-surface-2"
                  }`}
                  onClick={() => setView(t.key)}
                >
                  <span className="inline-flex items-center gap-1.5">
                    <TabIcon />
                    {t.label}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {view === "dashboard" && <Dashboard accounts={accounts} />}

        {view === "chat" && <Chat />}

        {view === "planning" && <Planning />}

        {view === "transactions" && (
          <>
            {transferMatches.length > 0 && (
              <Card className="mb-6 border-accent/40">
                <h2 className="font-semibold text-ink mb-3">
                  Transfers to review ({transferMatches.length})
                </h2>
                <div className="space-y-3">
                  {transferMatches.map((m) => {
                    const txnA = transactionById.get(m.transaction_id_a);
                    const txnB = transactionById.get(m.transaction_id_b);
                    if (!txnA || !txnB) return null;
                    return (
                      <div
                        key={m.id}
                        className="flex flex-wrap items-center justify-between gap-3 border border-hairline rounded-xl p-3"
                      >
                        <div className="flex flex-wrap gap-6">
                          <TransactionSummary txn={txnA} account={accountById.get(txnA.account_id)} />
                          <span className="text-ink-muted self-center">&harr;</span>
                          <TransactionSummary txn={txnB} account={accountById.get(txnB.account_id)} />
                        </div>
                        <div className="flex gap-2">
                          <button
                            className="px-3 py-1 bg-good text-canvas rounded-lg text-sm font-medium hover:opacity-90 transition-opacity"
                            onClick={() => handleTransferDecision(m.id, "confirmed")}
                          >
                            <span className="inline-flex items-center gap-1.5">
                              <IconCheck />
                              Confirm
                            </span>
                          </button>
                          <SecondaryButton onClick={() => handleTransferDecision(m.id, "rejected")}>
                            <span className="inline-flex items-center gap-1.5">
                              <IconX />
                              Reject
                            </span>
                          </SecondaryButton>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </Card>
            )}

            <div className="flex flex-wrap items-center gap-4 mb-4">
              <label className="flex items-center gap-2">
                <span className="font-medium text-ink-secondary text-sm">Account</span>
                <select
                  className={inputClass}
                  value={selectedAccountId ?? "all"}
                  onChange={(e) => setSelectedAccountId(e.target.value === "all" ? null : Number(e.target.value))}
                >
                  <option value="all">All accounts</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex items-center gap-2">
                <span className="font-medium text-ink-secondary text-sm">Category</span>
                <select
                  className={inputClass}
                  value={selectedCategoryId ?? "all"}
                  onChange={(e) => setSelectedCategoryId(e.target.value === "all" ? null : Number(e.target.value))}
                >
                  <option value="all">All categories</option>
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex items-center gap-2">
                <span className="font-medium text-ink-secondary text-sm">Month</span>
                <select
                  className={inputClass}
                  value={selectedMonth ?? "all"}
                  onChange={(e) => setSelectedMonth(e.target.value === "all" ? null : e.target.value)}
                >
                  <option value="all">All months</option>
                  {availableMonths.map((m) => (
                    <option key={m} value={m}>
                      {monthLabel(m)}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex items-center gap-2">
                <span className="font-medium text-ink-secondary text-sm">Merchant</span>
                <input
                  type="text"
                  className={inputClass}
                  placeholder="Search merchant..."
                  value={merchantSearch}
                  onChange={(e) => setMerchantSearch(e.target.value)}
                />
              </label>

              <label className="flex items-center gap-2">
                <span className="font-medium text-ink-secondary text-sm">Amount</span>
                <input
                  type="number"
                  step="0.01"
                  className={`${inputClass} w-24`}
                  placeholder="Min"
                  value={minAmount}
                  onChange={(e) => setMinAmount(e.target.value)}
                />
                <span className="text-ink-muted">&ndash;</span>
                <input
                  type="number"
                  step="0.01"
                  className={`${inputClass} w-24`}
                  placeholder="Max"
                  value={maxAmount}
                  onChange={(e) => setMaxAmount(e.target.value)}
                />
                <span className="text-ink-muted text-xs italic" title="Amounts are negative for expenses, positive for income/refunds — e.g. -100 to -50 for expenses between $50 and $100">
                  expenses are negative
                </span>
              </label>

              <label className="flex items-center gap-2 cursor-pointer text-sm">
                <input
                  type="checkbox"
                  className="accent-[color:var(--color-accent)]"
                  checked={uncategorizedOnly}
                  onChange={(e) => setUncategorizedOnly(e.target.checked)}
                />
                <span className="text-ink-secondary">Uncategorized only</span>
              </label>

              <label className="cursor-pointer">
                <span className="px-3 py-1.5 bg-accent text-canvas rounded-lg hover:bg-accent-strong transition-colors text-sm font-medium inline-flex items-center gap-1.5">
                  <IconUpload />
                  Import CSV
                </span>
                <input type="file" accept=".csv" className="hidden" onChange={handleFileUpload} />
              </label>

              <SecondaryButton onClick={handleDetectTransfers}>
                <span className="inline-flex items-center gap-1.5">
                  <IconTransfer />
                  Detect Transfers
                </span>
              </SecondaryButton>

              <SecondaryButton onClick={handleExportCsv}>
                <span className="inline-flex items-center gap-1.5">
                  <IconDownload />
                  Export CSV
                </span>
              </SecondaryButton>

              {uploadStatus && <span className="text-sm text-ink-muted">{uploadStatus}</span>}
            </div>

            {error && <p className="text-critical mb-4">{error}</p>}

            {loading ? (
              <p className="text-ink-muted">Loading...</p>
            ) : visibleTransactions.length === 0 ? (
              <p className="text-ink-muted">
                {allTransactions.length === 0
                  ? "No transactions yet. Import a CSV to get started."
                  : "No transactions match the current filters."}
              </p>
            ) : (
              <div className="bg-surface border border-hairline rounded-2xl overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left border-b border-hairline bg-surface-2 text-ink-secondary">
                      <th className="p-2 font-medium">Date</th>
                      <th className="p-2 font-medium">Account</th>
                      <th className="p-2 font-medium">Description</th>
                      <th className="p-2 font-medium">Category</th>
                      <th className="p-2 font-medium">Note</th>
                      <th className="p-2 font-medium text-right">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleTransactions.map((t) => (
                      <tr key={t.id} className="border-b border-hairline last:border-0 hover:bg-surface-2/60 transition-colors">
                        <td className="p-2 whitespace-nowrap text-ink-secondary">{t.date}</td>
                        <td className="p-2 whitespace-nowrap text-ink-secondary">
                          {accountById.get(t.account_id)?.name ?? t.account_id}
                        </td>
                        <td className="p-2">
                          {editingDescriptionId === t.id ? (
                            <input
                              autoFocus
                              className={`${inputClass} w-full`}
                              value={editingValue}
                              onChange={(e) => setEditingValue(e.target.value)}
                              onBlur={() => saveDescription(t.id)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") saveDescription(t.id);
                                if (e.key === "Escape") setEditingDescriptionId(null);
                              }}
                            />
                          ) : (
                            <span
                              className="cursor-pointer hover:text-accent transition-colors"
                              title="Click to rename"
                              onClick={() => startEditingDescription(t)}
                            >
                              {t.clean_description ?? t.description}
                            </span>
                          )}
                        </td>
                        <td className="p-2">
                          <div className="flex items-center gap-2">
                            {t.category_id !== null && (
                              <span
                                className="h-2 w-2 rounded-full shrink-0"
                                style={{ backgroundColor: categoryDotColor(t.category_id) }}
                              />
                            )}
                            <select
                              className={`${inputClass} bg-canvas`}
                              value={t.category_id ?? ""}
                              onChange={(e) => handleCategoryChange(t.id, e.target.value)}
                            >
                              <option value="">Uncategorized</option>
                              {categories.map((c) => (
                                <option key={c.id} value={c.id}>
                                  {c.name}
                                </option>
                              ))}
                            </select>
                          </div>
                          {t.category_id && !categoryById.has(t.category_id) && (
                            <span className="text-critical text-xs ml-1">unknown category</span>
                          )}
                        </td>
                        <td className="p-2">
                          {editingNoteId === t.id ? (
                            <input
                              autoFocus
                              className={`${inputClass} w-full`}
                              value={editingNoteValue}
                              onChange={(e) => setEditingNoteValue(e.target.value)}
                              onBlur={() => saveNote(t.id)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") saveNote(t.id);
                                if (e.key === "Escape") setEditingNoteId(null);
                              }}
                            />
                          ) : (
                            <span
                              className={`cursor-pointer hover:text-accent transition-colors ${t.note ? "text-ink-secondary" : "text-ink-muted italic"}`}
                              title="Click to add a note"
                              onClick={() => startEditingNote(t)}
                            >
                              {t.note || "Add note..."}
                            </span>
                          )}
                        </td>
                        <td className={`p-2 text-right whitespace-nowrap ${t.amount_cents < 0 ? "text-critical" : "text-good"}`}>
                          {formatAmount(t.amount_cents)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
