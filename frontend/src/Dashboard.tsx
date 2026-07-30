import { useEffect, useRef, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  fetchCategoryBreakdown,
  fetchCategoryTransactions,
  fetchMonthlySummary,
  fetchTopMerchants,
  type Account,
  type CategoryBreakdown,
  type MerchantBreakdown,
  type MonthlySummary,
  type Transaction,
} from "./api";
import { formatAmount } from "./format";
import { Card, StatTile, inputClass } from "./ui";
import { IconBank, IconCalendar } from "./icons";

const MONTHS_HISTORY = 6;
const TOP_MERCHANTS_LIMIT = 10;
const ALL_MONTHS_VALUE = "__all__";

// Dark-mode steps from the dataviz reference palette (references/palette.md) —
// categorical (identity: income vs expenses are distinct series)
const COLOR_INCOME = "#3987e5";
const COLOR_EXPENSE = "#d95926";
// Sequential (magnitude: one hue, ranking categories/merchants) — reuses the
// categorical blue slot as its own one-hue ramp, per the reference convention.
const COLOR_SEQUENTIAL = "#3987e5";
// Status (net savings is a state, not a series identity)
const COLOR_GOOD = "#0ca30c";
const COLOR_CRITICAL = "#d03b3b";

const GRID_COLOR = "#2c2c2a";
const AXIS_COLOR = "#383835";
const TEXT_MUTED = "#898781";

const TOOLTIP_STYLE = {
  backgroundColor: "#232320",
  border: "1px solid rgba(255,255,255,0.18)",
  borderRadius: 10,
  color: "#ffffff",
  fontSize: 13,
};

function monthLabel(month: string): string {
  const [year, m] = month.split("-").map(Number);
  return new Date(year, m - 1, 1).toLocaleDateString("en-US", { month: "short", year: "2-digit" });
}

function categoryKey(c: CategoryBreakdown): string {
  return String(c.category_id ?? "uncategorized");
}

function RankedBarList({
  rows,
  emptyMessage,
  selectedKey,
  onRowClick,
}: {
  rows: { key: string; label: string; total_cents: number }[];
  emptyMessage: string;
  selectedKey?: string | null;
  onRowClick?: (key: string) => void;
}) {
  if (rows.length === 0) {
    return <p className="text-ink-muted text-sm">{emptyMessage}</p>;
  }
  const max = Math.max(...rows.map((r) => r.total_cents));
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div
          key={r.key}
          className={`flex items-center gap-2 text-sm -mx-1 px-1 py-0.5 rounded-lg transition-colors ${
            onRowClick ? "cursor-pointer hover:bg-surface-2" : ""
          } ${selectedKey === r.key ? "bg-accent-soft" : ""}`}
          onClick={onRowClick ? () => onRowClick(r.key) : undefined}
        >
          <div className="w-32 shrink-0 truncate text-ink-secondary" title={r.label}>
            {r.label}
          </div>
          <div className="flex-1 bg-surface-2 rounded h-4 overflow-hidden">
            <div
              className="h-4 rounded"
              style={{ width: `${(r.total_cents / max) * 100}%`, backgroundColor: COLOR_SEQUENTIAL }}
            />
          </div>
          <div className="w-20 shrink-0 text-right text-ink tabular-nums">{formatAmount(r.total_cents)}</div>
        </div>
      ))}
    </div>
  );
}

export default function Dashboard({ accounts }: { accounts: Account[] }) {
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [monthly, setMonthly] = useState<MonthlySummary[]>([]);
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null);
  const monthInitialized = useRef(false);
  const [categories, setCategories] = useState<CategoryBreakdown[]>([]);
  const [merchants, setMerchants] = useState<MerchantBreakdown[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<CategoryBreakdown | null>(null);
  const [categoryTransactions, setCategoryTransactions] = useState<Transaction[]>([]);
  const [categoryTransactionsLoading, setCategoryTransactionsLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchMonthlySummary(MONTHS_HISTORY, selectedAccountId)
      .then((result) => {
        setMonthly(result);
        setSelectedMonth((prev) => {
          // "All months" (null) is an explicit user choice once initialized, not a
          // sentinel for "not yet loaded" - don't override it on account switch.
          if (monthInitialized.current && prev === null) return null;
          if (prev && result.some((r) => r.month === prev)) return prev;
          return result.length > 0 ? result[result.length - 1].month : null;
        });
        monthInitialized.current = true;
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [selectedAccountId]);

  useEffect(() => {
    // selectedMonth === null is a valid "All months" selection once initialized -
    // only skip fetching before the monthly summary has loaded at all.
    if (monthly.length === 0) {
      setCategories([]);
      setMerchants([]);
      return;
    }
    Promise.all([
      fetchCategoryBreakdown(selectedMonth, selectedAccountId),
      fetchTopMerchants(selectedMonth, selectedAccountId, TOP_MERCHANTS_LIMIT),
    ])
      .then(([categoryResult, merchantResult]) => {
        setCategories(categoryResult);
        setMerchants(merchantResult);
      })
      .catch((e) => setError(String(e)));
  }, [selectedMonth, selectedAccountId, monthly.length]);

  useEffect(() => {
    if (selectedCategory === null || monthly.length === 0) {
      setCategoryTransactions([]);
      return;
    }
    setCategoryTransactionsLoading(true);
    fetchCategoryTransactions(selectedMonth, selectedAccountId, selectedCategory.category_id)
      .then(setCategoryTransactions)
      .catch((e) => setError(String(e)))
      .finally(() => setCategoryTransactionsLoading(false));
  }, [selectedCategory, selectedMonth, selectedAccountId, monthly.length]);

  function handleCategoryClick(key: string) {
    const clicked = categories.find((c) => categoryKey(c) === key) ?? null;
    setSelectedCategory((prev) => (prev && clicked && categoryKey(prev) === key ? null : clicked));
  }

  const accountById = new Map(accounts.map((a) => [a.id, a]));
  const totals = monthly.reduce(
    (acc, m) => ({ income: acc.income + m.income_cents, expense: acc.expense + m.expense_cents }),
    { income: 0, expense: 0 }
  );
  const net = totals.income - totals.expense;
  const savingsRate = totals.income > 0 ? (net / totals.income) * 100 : 0;
  const trendData = monthly.map((m) => ({ ...m, label: monthLabel(m.month) }));

  return (
    <div>
      <div className="flex flex-wrap items-center gap-4 mb-4">
        <label className="flex items-center gap-1.5" title="Account">
          <IconBank className="text-ink-muted shrink-0" />
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
      </div>

      {error && <p className="text-critical mb-4">{error}</p>}

      {loading ? (
        <p className="text-ink-muted">Loading...</p>
      ) : monthly.length === 0 ? (
        <p className="text-ink-muted">No transactions yet. Import a CSV to see your dashboard.</p>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatTile label={`Income (${monthly.length} mo)`} value={formatAmount(totals.income)} />
            <StatTile label={`Expenses (${monthly.length} mo)`} value={formatAmount(totals.expense)} />
            <StatTile
              label="Net savings"
              value={formatAmount(net)}
              valueColor={net >= 0 ? COLOR_GOOD : COLOR_CRITICAL}
            />
            <StatTile label="Savings rate" value={`${savingsRate.toFixed(1)}%`} />
          </div>

          <Card>
            <h2 className="font-semibold text-ink mb-3">Monthly income vs. expenses</h2>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={trendData}>
                <CartesianGrid stroke={GRID_COLOR} vertical={false} />
                <XAxis dataKey="label" stroke={AXIS_COLOR} tick={{ fill: TEXT_MUTED, fontSize: 12 }} />
                <YAxis
                  stroke={AXIS_COLOR}
                  tick={{ fill: TEXT_MUTED, fontSize: 12 }}
                  tickFormatter={(v: number) => formatAmount(v)}
                  width={80}
                />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  cursor={{ fill: "rgba(255,255,255,0.06)" }}
                  formatter={(value) => formatAmount(Number(value))}
                />
                <Legend wrapperStyle={{ fontSize: 12, color: TEXT_MUTED }} />
                <Bar dataKey="income_cents" name="Income" fill={COLOR_INCOME} radius={[4, 4, 0, 0]} maxBarSize={24} />
                <Bar
                  dataKey="expense_cents"
                  name="Expenses"
                  fill={COLOR_EXPENSE}
                  radius={[4, 4, 0, 0]}
                  maxBarSize={24}
                />
              </BarChart>
            </ResponsiveContainer>
          </Card>

          <Card>
            <h2 className="font-semibold text-ink mb-3">Net savings trend</h2>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={trendData}>
                <CartesianGrid stroke={GRID_COLOR} vertical={false} />
                <XAxis dataKey="label" stroke={AXIS_COLOR} tick={{ fill: TEXT_MUTED, fontSize: 12 }} />
                <YAxis
                  stroke={AXIS_COLOR}
                  tick={{ fill: TEXT_MUTED, fontSize: 12 }}
                  tickFormatter={(v: number) => formatAmount(v)}
                  width={80}
                />
                <ReferenceLine y={0} stroke={AXIS_COLOR} />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  cursor={{ fill: "rgba(255,255,255,0.06)" }}
                  formatter={(value) => formatAmount(Number(value))}
                />
                <Bar dataKey="net_cents" name="Net" radius={[4, 4, 4, 4]} maxBarSize={24}>
                  {trendData.map((entry) => (
                    <Cell key={entry.month} fill={entry.net_cents >= 0 ? COLOR_GOOD : COLOR_CRITICAL} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </Card>

          <label className="flex items-center gap-1.5" title="Month">
            <IconCalendar className="text-ink-muted shrink-0" />
            <select
              className={inputClass}
              value={selectedMonth ?? ALL_MONTHS_VALUE}
              onChange={(e) => setSelectedMonth(e.target.value === ALL_MONTHS_VALUE ? null : e.target.value)}
            >
              <option value={ALL_MONTHS_VALUE}>All months</option>
              {monthly.map((m) => (
                <option key={m.month} value={m.month}>
                  {monthLabel(m.month)}
                </option>
              ))}
            </select>
          </label>

          <div className="grid md:grid-cols-2 gap-6">
            <Card>
              <h2 className="font-semibold text-ink mb-1">Spending by category</h2>
              <p className="text-xs text-ink-muted mb-3">Click a category to see its transactions.</p>
              <RankedBarList
                rows={categories.map((c) => ({
                  key: categoryKey(c),
                  label: c.category_name,
                  total_cents: c.total_cents,
                }))}
                emptyMessage="No spending in this period."
                selectedKey={selectedCategory ? categoryKey(selectedCategory) : null}
                onRowClick={handleCategoryClick}
              />
            </Card>

            <Card>
              <h2 className="font-semibold text-ink mb-3">Top merchants</h2>
              <RankedBarList
                rows={merchants.map((m) => ({ key: m.merchant, label: m.merchant, total_cents: m.total_cents }))}
                emptyMessage="No spending in this period."
              />
            </Card>
          </div>

          {selectedCategory && (
            <Card>
              <h2 className="font-semibold text-ink mb-3">
                {selectedCategory.category_name} transactions &mdash;{" "}
                {selectedMonth ? monthLabel(selectedMonth) : "All time"}
              </h2>
              {categoryTransactionsLoading ? (
                <p className="text-ink-muted text-sm">Loading...</p>
              ) : categoryTransactions.length === 0 ? (
                <p className="text-ink-muted text-sm">No transactions found.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left border-b border-hairline text-ink-secondary">
                        <th className="p-2 font-medium">Date</th>
                        <th className="p-2 font-medium">Account</th>
                        <th className="p-2 font-medium">Description</th>
                        <th className="p-2 font-medium text-right">Amount</th>
                      </tr>
                    </thead>
                    <tbody>
                      {categoryTransactions.map((t) => (
                        <tr key={t.id} className="border-b border-hairline last:border-0">
                          <td className="p-2 whitespace-nowrap text-ink-secondary">{t.date}</td>
                          <td className="p-2 whitespace-nowrap text-ink-secondary">
                            {accountById.get(t.account_id)?.name ?? t.account_id}
                          </td>
                          <td className="p-2 text-ink">{t.clean_description ?? t.description}</td>
                          <td className="p-2 text-right whitespace-nowrap text-critical">
                            {formatAmount(t.amount_cents)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
