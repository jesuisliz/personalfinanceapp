import type { RulePreview } from "./api";
import { IconCheck, IconX } from "./icons";
import { canSave, displayName, isMismatch, type RememberRuleState } from "./rememberRule";
import { Card, PrimaryButton, SecondaryButton, inputClass } from "./ui";

type PanelState = NonNullable<RememberRuleState>;

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

/** The first message that applies: error, still checking, then each reason the server would refuse. */
function Status({ state, accountName }: { state: PanelState; accountName: string }) {
  const preview = state.preview;
  if (state.error) return <p className="text-sm text-critical">{state.error}</p>;
  if (!preview) {
    const blank = state.patternTouched && state.pattern.trim() === "";
    return <p className="text-sm text-ink-muted">{blank ? "Enter a pattern" : "Checking..."}</p>;
  }
  if (!preview.matches_source) {
    return (
      <p className="text-sm text-critical">
        The pattern doesn't appear in this transaction's description: {state.source.description}
      </p>
    );
  }
  const conflict = preview.conflicting_rule;
  if (conflict) {
    return (
      <p className="text-sm text-critical">
        Rule #{conflict.id} ("{conflict.match_pattern}" &rarr; {conflict.clean_name}) already names this transaction
        {conflict.account_id !== null && ", for this account only"}.
        {conflict.account_id === null && !state.thisAccountOnly && (
          <> Checking "Only for {accountName}" would put this rule ahead of it.</>
        )}
      </p>
    );
  }
  if (preview.category_mismatch_count > 0) {
    return (
      <p className="text-sm text-critical">
        {plural(preview.category_mismatch_count, "transaction")} this pattern matches{" "}
        {preview.category_mismatch_count === 1 ? "is" : "are"} already in another category. Narrow the pattern to save.
      </p>
    );
  }
  return (
    <p className="text-sm text-ink-secondary">
      Would name {plural(preview.would_name_count, "transaction")} and categorize {preview.would_categorize_count} of
      them.
    </p>
  );
}

/** Example rows the pattern matches; rows in another category are highlighted. */
function Sample({ preview, categoryName }: { preview: RulePreview; categoryName: string }) {
  if (preview.sample.length === 0) return null;
  return (
    <div className="text-sm">
      <div className="text-ink-muted">Examples:</div>
      <ul>
        {preview.sample.map((row) => (
          <li key={row.id} className={isMismatch(row.category_name, categoryName) ? "text-critical" : "text-ink-secondary"}>
            {row.date} &middot; {row.description} &middot; {row.category_name ?? "Uncategorized"}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Opt-in offer, after a category edit, to remember it as a merchant rule. */
export default function RememberRulePanel({
  state,
  categoryName,
  accountName,
  onPatternChange,
  onNameChange,
  onScopeToggle,
  onSave,
  onDismiss,
}: {
  state: PanelState;
  categoryName: string;
  accountName: string;
  onPatternChange: (pattern: string) => void;
  onNameChange: (name: string) => void;
  onScopeToggle: () => void;
  onSave: () => void;
  onDismiss: () => void;
}) {
  const dismissButton = (label: string) => (
    <SecondaryButton onClick={onDismiss}>
      <span className="inline-flex items-center gap-1.5">
        <IconX />
        {label}
      </span>
    </SecondaryButton>
  );

  return (
    <Card className="mb-4 border-accent/40">
      <h2 className="font-semibold text-ink mb-1">Remember this as a rule?</h2>
      <p className="text-sm text-ink-muted mb-3">
        Future transactions matching the pattern get this name and category.
      </p>
      {state.savedRuleId !== null ? (
        <div className="space-y-3">
          <p className="text-sm text-good">
            Rule saved (#{state.savedRuleId}). Matching transactions without a name were updated. To undo, delete rule{" "}
            {state.savedRuleId} with <code>DELETE /merchant-rules/{state.savedRuleId}</code>.
          </p>
          {dismissButton("Close")}
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-4">
            <label className="text-sm text-ink-secondary flex flex-col gap-1">
              Pattern
              <input
                className={inputClass}
                value={state.pattern}
                placeholder={!state.patternTouched && state.pattern === "" ? "Finding a pattern..." : undefined}
                onChange={(e) => onPatternChange(e.target.value)}
              />
            </label>
            <label className="text-sm text-ink-secondary flex flex-col gap-1">
              Name
              <input className={inputClass} value={displayName(state)} onChange={(e) => onNameChange(e.target.value)} />
            </label>
            <div className="text-sm text-ink-secondary flex flex-col gap-1">
              Category
              <span className="text-ink py-1">{categoryName}</span>
            </div>
          </div>
          <label className="flex items-center gap-1.5 text-sm text-ink-secondary cursor-pointer">
            <input
              type="checkbox"
              className="accent-[color:var(--color-accent)]"
              checked={state.thisAccountOnly}
              onChange={onScopeToggle}
            />
            Only for {accountName}
          </label>
          <Status state={state} accountName={accountName} />
          {state.preview && <Sample preview={state.preview} categoryName={categoryName} />}
          <p className="text-xs text-ink-muted">On import, this rule is applied before the bank's own category.</p>
          <div className="flex gap-2">
            <PrimaryButton onClick={onSave} disabled={!canSave(state)}>
              <span className="inline-flex items-center gap-1.5">
                <IconCheck />
                {state.saving ? "Saving..." : "Save rule"}
              </span>
            </PrimaryButton>
            {dismissButton("Dismiss")}
          </div>
        </div>
      )}
    </Card>
  );
}
