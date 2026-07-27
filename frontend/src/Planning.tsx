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
import { Card, PrimaryButton, StatTile, inputClass } from "./ui";

const COLOR_GOOD = "#0ca30c";
const COLOR_CRITICAL = "#d03b3b";

function dollarsToCents(input: string): number | null {
  const n = Number(input);
  if (Number.isNaN(n)) return null;
  return Math.round(n * 100);
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
    <Card>
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-semibold text-ink">{goal.name}</h3>
          <div className="text-sm text-ink-muted">
            {formatAmount(goal.saved_so_far_cents)} of {formatAmount(goal.target_amount_cents)}
            {goal.target_date && <> &middot; target {goal.target_date}</>}
          </div>
        </div>
        <button className="text-xs text-critical hover:underline" onClick={() => onDelete(goal.id)}>
          Delete
        </button>
      </div>

      <div className="mt-2 bg-surface-2 rounded-full h-3 overflow-hidden">
        <div
          className="h-3 rounded-full bg-accent shadow-[0_0_8px_var(--color-accent-soft)]"
          style={{ width: `${progressPct}%` }}
        />
      </div>

      <div className="mt-2 text-sm">
        {!projection ? (
          <span className="text-ink-muted">Loading projection...</span>
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
              className={`${inputClass} w-28`}
              value={savedInput}
              onChange={(e) => setSavedInput(e.target.value)}
              autoFocus
            />
            <button className="text-xs text-accent hover:underline" onClick={save}>
              Save
            </button>
            <button className="text-xs text-ink-muted hover:underline" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        ) : (
          <button className="text-xs text-accent hover:underline" onClick={() => setEditing(true)}>
            Update saved-so-far
          </button>
        )}
      </div>
    </Card>
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

  if (loading) return <p className="text-ink-muted">Loading...</p>;

  return (
    <div className="max-w-3xl space-y-6">
      {error && <p className="text-critical">{error}</p>}

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

      <Card>
        <h2 className="font-semibold text-ink mb-2">Current balance (savings/cash on hand)</h2>
        <p className="text-xs text-ink-muted mb-2">
          Entered manually &mdash; the app can only see bounded-date-range CSV imports, never a true
          starting balance, so it never guesses this number.
        </p>
        <div className="flex items-center gap-2">
          <span className="text-ink-muted">$</span>
          <input
            className={`${inputClass} w-32`}
            value={balanceInput}
            onChange={(e) => setBalanceInput(e.target.value)}
          />
          <PrimaryButton onClick={handleSetBalance}>Update</PrimaryButton>
        </div>
        {runway?.balance_configured && (
          <p className="text-sm text-ink-secondary mt-2">
            Average monthly expenses (last 6 months): {formatAmount(runway.avg_monthly_expense_cents)}
            {runway.projected_end_date && (
              <>
                {" "}
                &mdash; at this rate, savings would last until around {runway.projected_end_date}.
              </>
            )}
          </p>
        )}
      </Card>

      <Card>
        <h2 className="font-semibold text-ink mb-3">Savings goals (vacations are just goals)</h2>
        <div className="space-y-3 mb-4">
          {goals.length === 0 ? (
            <p className="text-ink-muted text-sm">No goals yet &mdash; add one below.</p>
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

        <div className="border-t border-hairline pt-3">
          <h3 className="text-sm font-medium text-ink-secondary mb-2">New goal</h3>
          <div className="flex flex-wrap gap-2">
            <input
              className={`${inputClass} flex-1 min-w-[150px]`}
              placeholder="Name (e.g. Hawaii Vacation)"
              value={newGoalName}
              onChange={(e) => setNewGoalName(e.target.value)}
            />
            <input
              className={`${inputClass} w-28`}
              placeholder="Target $"
              value={newGoalAmount}
              onChange={(e) => setNewGoalAmount(e.target.value)}
            />
            <input
              type="date"
              className={inputClass}
              value={newGoalDate}
              onChange={(e) => setNewGoalDate(e.target.value)}
            />
            <PrimaryButton onClick={handleCreateGoal}>Add goal</PrimaryButton>
          </div>
        </div>
      </Card>

      <Card>
        <h2 className="font-semibold text-ink mb-1">Scenario analysis</h2>
        <p className="text-xs text-ink-muted mb-3">
          Reuses the same backend-computed savings estimate as the Chat tab &mdash; never an LLM guess.
        </p>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <span className="text-sm text-ink-secondary">Reduce</span>
          <select
            className={inputClass}
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
          <span className="text-sm text-ink-secondary">by</span>
          <input
            className={`${inputClass} w-16`}
            value={scenarioReduction}
            onChange={(e) => setScenarioReduction(e.target.value)}
          />
          <span className="text-sm text-ink-secondary">% over</span>
          <input
            className={`${inputClass} w-16`}
            value={scenarioMonths}
            onChange={(e) => setScenarioMonths(e.target.value)}
          />
          <span className="text-sm text-ink-secondary">months, applied to</span>
          <select
            className={inputClass}
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
          <PrimaryButton onClick={handleRunScenario}>Run</PrimaryButton>
        </div>

        {scenarioError && <p className="text-critical text-sm">{scenarioError}</p>}

        {scenarioResult && (
          <div className="text-sm space-y-1 text-ink-secondary">
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
      </Card>
    </div>
  );
}
