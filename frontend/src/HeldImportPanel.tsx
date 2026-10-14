import type { SuspectedDuplicate } from "./api";
import { formatAmount } from "./format";
import type { HeldImportState } from "./heldImport";
import { IconCheck, IconX } from "./icons";
import { Card, PrimaryButton, SecondaryButton } from "./ui";

/** One side of a held pair: date, account, description and amount. */
function HeldSide({
  label,
  date,
  accountName,
  description,
  amountCents,
}: {
  label: string;
  date: string;
  accountName: string;
  description: string;
  amountCents: number;
}) {
  return (
    <div className="text-sm min-w-0">
      <div className="text-xs font-semibold tracking-widest uppercase text-ink-muted">{label}</div>
      <div className="text-ink-muted">
        {date} &middot; {accountName}
      </div>
      <div className="text-ink break-words">{description}</div>
      <div className={amountCents < 0 ? "text-critical" : "text-good"}>{formatAmount(amountCents)}</div>
    </div>
  );
}

function HeldRow({
  suspect,
  checked,
  disabled,
  onToggle,
}: {
  suspect: SuspectedDuplicate;
  checked: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-4 border border-hairline rounded-xl p-3">
      <label className="flex items-center gap-1.5 text-sm text-ink-secondary cursor-pointer">
        <input
          type="checkbox"
          className="accent-[color:var(--color-accent)]"
          checked={checked}
          disabled={disabled}
          onChange={onToggle}
        />
        Import anyway
      </label>
      <div className="flex flex-wrap gap-6">
        <HeldSide
          label="New"
          date={suspect.date}
          accountName={suspect.account_name}
          description={suspect.description}
          amountCents={suspect.amount_cents}
        />
        <span className="text-ink-muted self-center">&harr;</span>
        <HeldSide
          label="Already imported"
          date={suspect.existing_date}
          accountName={suspect.account_name}
          description={suspect.existing_description}
          amountCents={suspect.amount_cents}
        />
      </div>
    </div>
  );
}

/** Rows an import held as possible duplicates, each with an unchecked "import anyway" box. */
export default function HeldImportPanel({
  state,
  onToggle,
  onImportSelected,
  onDismiss,
}: {
  state: NonNullable<HeldImportState>;
  onToggle: (hash: string) => void;
  onImportSelected: () => void;
  onDismiss: () => void;
}) {
  const suspects = state.summary.suspected_duplicates;
  return (
    <Card className="mb-4 border-accent/40">
      <h2 className="font-semibold text-ink mb-1">Held as possible duplicates ({suspects.length})</h2>
      <p className="text-sm text-ink-muted mb-3">
        These rows from {state.file.name} match a transaction already imported to the same account, for the same
        amount, within 3 days. They were not imported.
      </p>
      <div className="space-y-3 mb-3">
        {suspects.map((suspect) => (
          <HeldRow
            key={suspect.row_hash}
            suspect={suspect}
            checked={state.selected.has(suspect.row_hash)}
            disabled={state.busy}
            onToggle={() => onToggle(suspect.row_hash)}
          />
        ))}
      </div>
      <div className="flex gap-2">
        <PrimaryButton onClick={onImportSelected} disabled={state.selected.size === 0 || state.busy}>
          <span className="inline-flex items-center gap-1.5">
            <IconCheck />
            Import selected ({state.selected.size})
          </span>
        </PrimaryButton>
        <SecondaryButton onClick={onDismiss} disabled={state.busy}>
          <span className="inline-flex items-center gap-1.5">
            <IconX />
            Dismiss
          </span>
        </SecondaryButton>
      </div>
    </Card>
  );
}
