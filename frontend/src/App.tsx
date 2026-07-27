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
import { formatAmount } from "./format";
import Dashboard from "./Dashboard";
import Chat from "./Chat";
import Planning from "./Planning";

function TransactionSummary({ txn, account }: { txn: Transaction; account: Account | undefined }) {
  return (
    <div className="text-sm">
      <div className="text-gray-500">{txn.date} &middot; {account?.name ?? txn.account_id}</div>
      <div>{txn.clean_description ?? txn.description}</div>
      <div className={txn.amount_cents < 0 ? "text-red-600" : "text-green-700"}>
        {formatAmount(txn.amount_cents)}
      </div>
    </div>
  );
}

export default function App() {
  const [view, setView] = useState<"transactions" | "dashboard" | "chat" | "planning">("transactions");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [allTransactions, setAllTransactions] = useState<Transaction[]>([]);
  const [transferMatches, setTransferMatches] = useState<TransferMatch[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [uncategorizedOnly, setUncategorizedOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const [editingDescriptionId, setEditingDescriptionId] = useState<number | null>(null);
  const [editingValue, setEditingValue] = useState("");

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

  const accountById = new Map(accounts.map((a) => [a.id, a]));
  const categoryById = new Map(categories.map((c) => [c.id, c]));
  const transactionById = new Map(allTransactions.map((t) => [t.id, t]));
  const visibleTransactions = allTransactions
    .filter((t) => selectedAccountId === null || t.account_id === selectedAccountId)
    .filter((t) => !uncategorizedOnly || t.category_id === null);

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center gap-2 mb-6">
          <h1 className="text-2xl font-semibold text-gray-900 mr-4">
            {view === "transactions"
              ? "Transactions"
              : view === "dashboard"
                ? "Dashboard"
                : view === "chat"
                  ? "Chat"
                  : "Planning"}
          </h1>
          <div className="flex border border-gray-300 rounded overflow-hidden text-sm font-medium">
            <button
              className={`px-3 py-1.5 ${
                view === "transactions" ? "bg-blue-600 text-white" : "bg-white text-gray-700 hover:bg-gray-50"
              }`}
              onClick={() => setView("transactions")}
            >
              Transactions
            </button>
            <button
              className={`px-3 py-1.5 border-l border-gray-300 ${
                view === "dashboard" ? "bg-blue-600 text-white" : "bg-white text-gray-700 hover:bg-gray-50"
              }`}
              onClick={() => setView("dashboard")}
            >
              Dashboard
            </button>
            <button
              className={`px-3 py-1.5 border-l border-gray-300 ${
                view === "chat" ? "bg-blue-600 text-white" : "bg-white text-gray-700 hover:bg-gray-50"
              }`}
              onClick={() => setView("chat")}
            >
              Chat
            </button>
            <button
              className={`px-3 py-1.5 border-l border-gray-300 ${
                view === "planning" ? "bg-blue-600 text-white" : "bg-white text-gray-700 hover:bg-gray-50"
              }`}
              onClick={() => setView("planning")}
            >
              Planning
            </button>
          </div>
        </div>

        {view === "dashboard" && <Dashboard accounts={accounts} />}

        {view === "chat" && <Chat />}

        {view === "planning" && <Planning />}

        {view === "transactions" && (
          <>
        {transferMatches.length > 0 && (
          <div className="mb-6 bg-white border border-amber-300 rounded shadow-sm p-4">
            <h2 className="font-semibold text-gray-900 mb-3">
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
                    className="flex flex-wrap items-center justify-between gap-3 border border-gray-200 rounded p-3"
                  >
                    <div className="flex flex-wrap gap-6">
                      <TransactionSummary txn={txnA} account={accountById.get(txnA.account_id)} />
                      <span className="text-gray-400 self-center">&harr;</span>
                      <TransactionSummary txn={txnB} account={accountById.get(txnB.account_id)} />
                    </div>
                    <div className="flex gap-2">
                      <button
                        className="px-3 py-1 bg-green-600 text-white rounded text-sm hover:bg-green-700"
                        onClick={() => handleTransferDecision(m.id, "confirmed")}
                      >
                        Confirm
                      </button>
                      <button
                        className="px-3 py-1 bg-gray-200 text-gray-700 rounded text-sm hover:bg-gray-300"
                        onClick={() => handleTransferDecision(m.id, "rejected")}
                      >
                        Reject
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-4 mb-4">
          <label className="flex items-center gap-2">
            <span className="font-medium text-gray-700">Account:</span>
            <select
              className="border border-gray-300 rounded px-2 py-1 bg-white"
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

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={uncategorizedOnly}
              onChange={(e) => setUncategorizedOnly(e.target.checked)}
            />
            <span className="text-gray-700">Uncategorized only</span>
          </label>

          <label className="flex items-center gap-2 cursor-pointer">
            <span className="px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm font-medium">
              Import CSV
            </span>
            <input type="file" accept=".csv" className="hidden" onChange={handleFileUpload} />
          </label>

          <button
            className="px-3 py-1.5 bg-white border border-gray-300 rounded hover:bg-gray-50 text-sm font-medium text-gray-700"
            onClick={handleDetectTransfers}
          >
            Detect Transfers
          </button>

          {uploadStatus && <span className="text-sm text-gray-600">{uploadStatus}</span>}
        </div>

        {error && <p className="text-red-600 mb-4">{error}</p>}

        {loading ? (
          <p className="text-gray-500">Loading...</p>
        ) : visibleTransactions.length === 0 ? (
          <p className="text-gray-500">
            {allTransactions.length === 0
              ? "No transactions yet. Import a CSV to get started."
              : "No transactions match the current filters."}
          </p>
        ) : (
          <div className="bg-white border border-gray-200 rounded shadow-sm overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left border-b border-gray-200 bg-gray-100 text-gray-700">
                  <th className="p-2">Date</th>
                  <th className="p-2">Account</th>
                  <th className="p-2">Description</th>
                  <th className="p-2">Category</th>
                  <th className="p-2 text-right">Amount</th>
                </tr>
              </thead>
              <tbody>
                {visibleTransactions.map((t) => (
                  <tr key={t.id} className="border-b border-gray-100 last:border-0">
                    <td className="p-2 whitespace-nowrap">{t.date}</td>
                    <td className="p-2 whitespace-nowrap">{accountById.get(t.account_id)?.name ?? t.account_id}</td>
                    <td className="p-2">
                      {editingDescriptionId === t.id ? (
                        <input
                          autoFocus
                          className="border border-gray-300 rounded px-1 py-0.5 w-full"
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
                          className="cursor-pointer hover:underline decoration-dotted"
                          title="Click to rename"
                          onClick={() => startEditingDescription(t)}
                        >
                          {t.clean_description ?? t.description}
                        </span>
                      )}
                    </td>
                    <td className="p-2">
                      <select
                        className="border border-gray-200 rounded px-1 py-0.5 bg-white text-gray-700"
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
                      {t.category_id && !categoryById.has(t.category_id) && (
                        <span className="text-red-500 text-xs ml-1">unknown category</span>
                      )}
                    </td>
                    <td className={`p-2 text-right whitespace-nowrap ${t.amount_cents < 0 ? "text-red-600" : "text-green-700"}`}>
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
