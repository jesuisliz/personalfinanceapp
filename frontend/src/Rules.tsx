import { useEffect, useState } from "react";
import {
  deleteMerchantRule,
  fetchAccounts,
  fetchCategories,
  fetchMerchantRules,
  type Account,
  type Category,
  type MerchantRuleListItem,
} from "./api";
import { categoryDotColor } from "./categoryColor";
import { filterRules, ruleCategoryLabel, ruleScopeLabel, sortRulesNewestFirst } from "./merchantRules";
import { Card, SecondaryButton, inputClass } from "./ui";

/** Every merchant rule, with how many transactions it wins today; delete one with an inline confirm. */
export default function Rules() {
  const [rules, setRules] = useState<MerchantRuleListItem[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [confirmingId, setConfirmingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  function load() {
    setLoading(true);
    setLoadError(null);
    return Promise.all([fetchMerchantRules(), fetchAccounts(), fetchCategories()])
      .then(([rulesResult, accountsResult, categoriesResult]) => {
        setRules(rulesResult);
        setAccounts(accountsResult);
        setCategories(categoriesResult);
      })
      .catch((e: Error) => setLoadError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  async function handleDelete(id: number) {
    setDeletingId(id);
    setStatus(null);
    try {
      const outcome = await deleteMerchantRule(id);
      setStatus(outcome === "deleted" ? `Deleted rule #${id}.` : `Rule #${id} was already deleted.`);
    } catch (e) {
      setStatus((e as Error).message);
    } finally {
      // Keep the row disabled until the reload drops it, so it can't be deleted twice.
      await load();
      setDeletingId(null);
      setConfirmingId(null);
    }
  }

  const visible = sortRulesNewestFirst(filterRules(rules, query, categories, accounts));

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
        <h2 className="font-semibold text-ink">Merchant rules ({rules.length})</h2>
        <input
          className={`${inputClass} w-64`}
          placeholder="Search rules"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <p className="text-sm text-ink-muted mb-3">
        Deleting a rule stops it applying from now on. Transactions it already named or categorized keep those values.
      </p>
      {status && <p className="text-sm text-ink-secondary mb-3">{status}</p>}

      {loadError ? (
        <p className="text-sm text-critical">{loadError}</p>
      ) : loading && rules.length === 0 ? (
        <p className="text-sm text-ink-muted">Loading...</p>
      ) : rules.length === 0 ? (
        <p className="text-sm text-ink-muted">No rules yet</p>
      ) : visible.length === 0 ? (
        <p className="text-sm text-ink-muted">No rules match {query.trim()}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-ink-muted border-b border-hairline">
              <tr>
                <th className="py-2 pr-3 font-medium">#</th>
                <th className="py-2 pr-3 font-medium">Pattern</th>
                <th className="py-2 pr-3 font-medium">Clean name</th>
                <th className="py-2 pr-3 font-medium">Category</th>
                <th className="py-2 pr-3 font-medium">Scope</th>
                <th className="py-2 pr-3 font-medium text-right">Matches</th>
                <th className="py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {visible.map((rule) => {
                const knownCategory = categories.some((c) => c.id === rule.category_id);
                const busy = deletingId === rule.id;
                return (
                  <tr key={rule.id} className="border-b border-hairline last:border-0">
                    <td className="py-2 pr-3 text-ink-muted">{rule.id}</td>
                    <td className="py-2 pr-3 font-mono text-xs text-ink">{rule.match_pattern}</td>
                    <td className="py-2 pr-3 text-ink">{rule.clean_name}</td>
                    <td className="py-2 pr-3 text-ink-secondary">
                      <span className="inline-flex items-center gap-1.5">
                        {knownCategory && rule.category_id !== null && (
                          <span
                            className="inline-block h-2 w-2 rounded-full"
                            style={{ backgroundColor: categoryDotColor(rule.category_id) }}
                          />
                        )}
                        {ruleCategoryLabel(rule, categories)}
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-ink-secondary">{ruleScopeLabel(rule, accounts)}</td>
                    <td className={`py-2 pr-3 text-right ${rule.match_count === 0 ? "text-ink-muted" : "text-ink"}`}>
                      {rule.match_count}
                    </td>
                    <td className="py-2 text-right whitespace-nowrap">
                      {confirmingId === rule.id ? (
                        <span className="inline-flex items-center gap-2">
                          <span className="text-ink-secondary">Delete rule #{rule.id}?</span>
                          <SecondaryButton disabled={busy} onClick={() => handleDelete(rule.id)}>
                            Confirm
                          </SecondaryButton>
                          <SecondaryButton disabled={busy} onClick={() => setConfirmingId(null)}>
                            Cancel
                          </SecondaryButton>
                        </span>
                      ) : (
                        <button
                          className="text-xs text-critical hover:underline disabled:opacity-40"
                          disabled={deletingId !== null}
                          onClick={() => setConfirmingId(rule.id)}
                        >
                          Delete
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
