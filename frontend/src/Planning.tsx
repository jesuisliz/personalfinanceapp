import { useEffect, useState } from "react";
import {
  createGoal,
  deleteGoal,
  fetchBalance,
  fetchCategories,
  fetchGoalProjection,
  fetchGoals,
  fetchRunway,
  runScenario,
  setBalance,
  updateGoal,
  type Category,
  type CurrentBalance,
  type GoalProjection,
  type RunwayResult,
  type SavingsGoal,
  type ScenarioResult,
} from "./api";
import { formatAmount } from "./format";

const COLOR_GOOD = "#0ca30c";
const COLOR_CRITICAL = "#d03b3b";
const COLOR_MUTED = "#898781";

function dollarsToCents(input: string): number | null {
  const n = Number(input);
  if (Number.isNaN(n)) return null;
  return Math.round(n * 100);
}

function StatTile({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <div className="bg-white border border-gray-200 rounded shadow-sm p-4">
      <div className="text-sm text-gray-500">{label}</div>
      <div className="text-2xl font-semibold" style={{ color: valueColor ?? "#0b0b0b" }}>
        {value}
      </div>
    </div>
  );
}

function GoalCard({
  goal,
  projection,
  onSaveProgress,
  onDelete,
}: {
  goal: SavingsGoal;
  projection: GoalProjection | undefined;
  onSaveProgress: (goalId: number, savedSoFarCents: number) => void;
  onDelete: (goalId: number) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [savedInput, setSavedInput] = useState(String(goal.saved_so_far_cents / 100));

  const progressPct = Math.min(100, (goal.saved_so_far_cents / goal.target_amount_cents) * 100);

  function save() {
    const cents = dollarsToCents(savedInput);
    if (cents === null) return;
    onSaveProgress(goal.id, cents);
    setEditing(false);
  }

  return (
    <div className="bg-white border border-gray-200 rounded shadow-sm p-4">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-semibold text-gray-900">{goal.name}</h3>
          <div className="text-sm text-gray-500">
            {formatAmount(goal.saved_so_far_cents)} of {formatAmount(goal.target_amount_cents)}
            {goal.target_date && <> &middot; target {goal.target_date}</>}
          </div>
        </div>
        <button className="text-xs text-red-600 hover:underline" onClick={() => onDelete(goal.id)}>
          Delete
        </button>
      </div>

      <div className="mt-2 bg-gray-100 rounded h-3 overflow-hidden">
        <div className="h-3 rounded bg-blue-600" style={{ width: `${progressPct}%` }} />
      </div>

      <div className="mt-2 text-sm">
        {!projection ? (
          <span className="text-gray-400">Loading projection...</span>
        ) : projection.status === "already_met" ? (
          <span className="font-medium" style={{ color: COLOR_GOOD }}>
            Goal already met
          </span>
        ) : projection.status === "not_on_track" ? (
          <span className="font-medium" style={{ color: COLOR_CRITICAL }}>
            Not on track (average monthly savings is $0 or negative recently)
          </span>
        ) : (
          <span style={{ color: COLOR_GOOD }}>
            On track &mdash; about {projection.months_to_goal?.toFixed(1)} months to go
            {projection.projected_date && <> (around {projection.projected_date})</>}
          </span>
        )}
      </div>

      <div className="mt-2">
        {editing ? (
          <div className="flex items-center gap-2">
            <input
              className="border border-gray-300 rounded px-2 py-1 text-sm w-28"
              value={savedInput}
              onChange={(e) => setSavedInput(e.target.value)}
              autoFocus
            />
            <button className="text-xs text-blue-600 hover:underline" onClick={save}>
              Save
            </button>
            <button className="text-xs text-gray-500 hover:underline" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        ) : (
          <button className="text-xs text-blue-600 hover:underline" onClick={() => setEditing(true)}>
            Update saved-so-far
          </button>
        )}
      </div>
    </div>
  );
}

export default function Planning() {
  const [balance, setBalanceState] = useState<CurrentBalance | null>(null);
  const [balanceInput, setBalanceInput] = useState("");
  const [runway, setRunway] = useState<RunwayResult | null>(null);
  const [goals, setGoals] = useState<SavingsGoal[]>([]);
  const [projections, setProjections] = useState<Record<number, GoalProjection>>({});
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newGoalName, setNewGoalName] = useState("");
  const [newGoalAmount, setNewGoalAmount] = useState("");
  const [newGoalDate, setNewGoalDate] = useState("");

  const [scenarioCategory, setScenarioCategory] = useState("");
  const [scenarioReduction, setScenarioReduction] = useState("25");
  const [scenarioMonths, setScenarioMonths] = useState("6");
  const [scenarioGoalId, setScenarioGoalId] = useState<string>("runway");
  const [scenarioResult, setScenarioResult] = useState<ScenarioResult | null>(null);
  const [scenarioError, setScenarioError] = useState<string | null>(null);

  function reload() {
    setLoading(true);
    setError(null);
    Promise.all([fetchBalance(), fetchRunway(6), fetchGoals(), fetchCategories()])
      .then(([balanceResult, runwayResult, goalsResult, categoriesResult]) => {
        setBalanceState(balanceResult);
        setBalanceInput(balanceResult.amount_cents !== null ? String(balanceResult.amount_cents / 100) : "");
        setRunway(runwayResult);
        setGoals(goalsResult);
        setCategories(categoriesResult);
        if (categoriesResult.length > 0) setScenarioCategory(categoriesResult[0].name);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(reload, []);

  useEffect(() => {
    Promise.all(goals.map((g) => fetchGoalProjection(g.id, 6).then((p) => [g.id, p] as const)))
      .then((pairs) => setProjections(Object.fromEntries(pairs)))
      .catch((e) => setError(String(e)));
  }, [goals]);

  async function handleSetBalance() {
    const cents = dollarsToCents(balanceInput);
    if (cents === null) return;
    await setBalance(cents);
    reload();
  }

  async function handleCreateGoal() {
    const cents = dollarsToCents(newGoalAmount);
    if (!newGoalName.trim() || cents === null) return;
    await createGoal({
      name: newGoalName.trim(),
      target_amount_cents: cents,
      target_date: newGoalDate || null,
    });
    setNewGoalName("");
    setNewGoalAmount("");
    setNewGoalDate("");
    const fresh = await fetchGoals();
    setGoals(fresh);
  }

  async function handleSaveProgress(goalId: number, savedSoFarCents: number) {
    await updateGoal(goalId, { saved_so_far_cents: savedSoFarCents });
    const fresh = await fetchGoals();
    setGoals(fresh);
  }

  async function handleDeleteGoal(goalId: number) {
    await deleteGoal(goalId);
    const fresh = await fetchGoals();
    setGoals(fresh);
  }

  async function handleRunScenario() {
    setScenarioError(null);
    setScenarioResult(null);
    const reduction = Number(scenarioReduction);
    const months = Number(scenarioMonths);
    if (!scenarioCategory || Number.isNaN(reduction) || Number.isNaN(months)) return;

    try {
      const result = await runScenario({
        category_name: scenarioCategory,
        reduction_percent: reduction,
        months,
        goal_id: scenarioGoalId === "runway" ? null : Number(scenarioGoalId),
      });
      setScenarioResult(result);
    } catch (e) {
      setScenarioError(String(e));
    }
  }

  if (loading) return <p className="text-gray-500">Loading...</p>;

  return (
    <div className="max-w-3xl space-y-6">
      {error && <p className="text-red-600">{error}</p>}

      <div className="grid grid-cols-2 gap-4">
        <StatTile
          label="Current balance"
          value={balance?.amount_cents != null ? formatAmount(balance.amount_cents) : "Not set"}
        />
        <StatTile
          label="Financial runway"
          value={
            !runway?.balance_configured
              ? "Set balance to see"
              : runway.runway_months !== null
                ? `${runway.runway_months.toFixed(1)} months`
                : "Not enough expense history"
          }
        />
      </div>

      <div className="bg-white border border-gray-200 rounded shadow-sm p-4">
        <h2 className="font-semibold text-gray-900 mb-2">Current balance (savings/cash on hand)</h2>
        <p className="text-xs mb-2" style={{ color: COLOR_MUTED }}>
          Entered manually &mdash; the app can only see bounded-date-range CSV imports, never a true
          starting balance, so it never guesses this number.
        </p>
        <div className="flex items-center gap-2">
          <span className="text-gray-500">$</span>
          <input
            className="border border-gray-300 rounded px-2 py-1 text-sm w-32"
            value={balanceInput}
            onChange={(e) => setBalanceInput(e.target.value)}
          />
          <button
            className="px-3 py-1.5 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700"
            onClick={handleSetBalance}
          >
            Update
          </button>
        </div>
        {runway?.balance_configured && (
          <p className="text-sm text-gray-600 mt-2">
            Average monthly expenses (last 6 months): {formatAmount(runway.avg_monthly_expense_cents)}
            {runway.projected_end_date && (
              <>
                {" "}
                &mdash; at this rate, savings would last until around {runway.projected_end_date}.
              </>
            )}
          </p>
        )}
      </div>

      <div className="bg-white border border-gray-200 rounded shadow-sm p-4">
        <h2 className="font-semibold text-gray-900 mb-3">Savings goals (vacations are just goals)</h2>
        <div className="space-y-3 mb-4">
          {goals.length === 0 ? (
            <p className="text-gray-500 text-sm">No goals yet &mdash; add one below.</p>
          ) : (
            goals.map((g) => (
              <GoalCard
                key={g.id}
                goal={g}
                projection={projections[g.id]}
                onSaveProgress={handleSaveProgress}
                onDelete={handleDeleteGoal}
              />
            ))
          )}
        </div>

        <div className="border-t border-gray-200 pt-3">
          <h3 className="text-sm font-medium text-gray-700 mb-2">New goal</h3>
          <div className="flex flex-wrap gap-2">
            <input
              className="border border-gray-300 rounded px-2 py-1 text-sm flex-1 min-w-[150px]"
              placeholder="Name (e.g. Hawaii Vacation)"
              value={newGoalName}
              onChange={(e) => setNewGoalName(e.target.value)}
            />
            <input
              className="border border-gray-300 rounded px-2 py-1 text-sm w-28"
              placeholder="Target $"
              value={newGoalAmount}
              onChange={(e) => setNewGoalAmount(e.target.value)}
            />
            <input
              type="date"
              className="border border-gray-300 rounded px-2 py-1 text-sm"
              value={newGoalDate}
              onChange={(e) => setNewGoalDate(e.target.value)}
            />
            <button
              className="px-3 py-1.5 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700"
              onClick={handleCreateGoal}
            >
              Add goal
            </button>
          </div>
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded shadow-sm p-4">
        <h2 className="font-semibold text-gray-900 mb-1">Scenario analysis</h2>
        <p className="text-xs mb-3" style={{ color: COLOR_MUTED }}>
          Reuses the same backend-computed savings estimate as the Chat tab &mdash; never an LLM guess.
        </p>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <span className="text-sm text-gray-700">Reduce</span>
          <select
            className="border border-gray-300 rounded px-2 py-1 text-sm bg-white"
            value={scenarioCategory}
            onChange={(e) => setScenarioCategory(e.target.value)}
          >
            {categories.map((c) => (
              <option key={c.id} value={c.name}>
                {c.name}
              </option>
            ))}
            <option value="Uncategorized">Uncategorized</option>
          </select>
          <span className="text-sm text-gray-700">by</span>
          <input
            className="border border-gray-300 rounded px-2 py-1 text-sm w-16"
            value={scenarioReduction}
            onChange={(e) => setScenarioReduction(e.target.value)}
          />
          <span className="text-sm text-gray-700">% over</span>
          <input
            className="border border-gray-300 rounded px-2 py-1 text-sm w-16"
            value={scenarioMonths}
            onChange={(e) => setScenarioMonths(e.target.value)}
          />
          <span className="text-sm text-gray-700">months, applied to</span>
          <select
            className="border border-gray-300 rounded px-2 py-1 text-sm bg-white"
            value={scenarioGoalId}
            onChange={(e) => setScenarioGoalId(e.target.value)}
          >
            <option value="runway">Runway</option>
            {goals.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
          <button
            className="px-3 py-1.5 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700"
            onClick={handleRunScenario}
          >
            Run
          </button>
        </div>

        {scenarioError && <p className="text-red-600 text-sm">{scenarioError}</p>}

        {scenarioResult && (
          <div className="text-sm space-y-1">
            <p>
              Estimated savings: {formatAmount(scenarioResult.savings_estimate.monthly_savings_cents)}/month (
              {formatAmount(scenarioResult.savings_estimate.annual_savings_cents)}/year), based on an average
              of {formatAmount(scenarioResult.savings_estimate.avg_monthly_cents)}/month actually spent.
            </p>
            {scenarioResult.runway && (
              <p>
                {scenarioResult.runway.runway_months !== null ? (
                  <>Runway would extend to {scenarioResult.runway.runway_months.toFixed(1)} months.</>
                ) : (
                  <>Not enough expense history to project runway.</>
                )}
              </p>
            )}
            {scenarioResult.goal_projection && (
              <p>
                {scenarioResult.goal_projection.status === "already_met" ? (
                  <>That goal is already met.</>
                ) : scenarioResult.goal_projection.status === "not_on_track" ? (
                  <>Still not on track even with this reduction.</>
                ) : (
                  <>
                    That goal would be reached in about{" "}
                    {scenarioResult.goal_projection.months_to_goal?.toFixed(1)} months.
                  </>
                )}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
