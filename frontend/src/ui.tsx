import type { ReactNode } from "react";

export function Card({
  children,
  className = "",
  variant = "default",
}: {
  children: ReactNode;
  className?: string;
  variant?: "default" | "elevated";
}) {
  const variantClass =
    variant === "elevated"
      ? "bg-surface border border-hairline-strong shadow-[0_8px_24px_-16px_rgba(0,0,0,0.6)]"
      : "bg-surface border border-hairline";
  return <div className={`${variantClass} rounded-2xl p-4 ${className}`}>{children}</div>;
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="text-xs font-semibold tracking-widest uppercase text-ink-muted mb-2">
      {children}
    </div>
  );
}

export function StatTile({
  label,
  value,
  valueColor,
}: {
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <Card variant="elevated">
      <div className="text-sm text-ink-secondary">{label}</div>
      <div className="text-3xl font-semibold tracking-tight" style={{ color: valueColor ?? "var(--color-ink)" }}>
        {value}
      </div>
    </Card>
  );
}

export function PrimaryButton({
  children,
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={`px-3 py-1.5 rounded-lg text-sm font-medium bg-accent text-canvas hover:bg-accent-strong transition-colors disabled:opacity-40 disabled:cursor-not-allowed shadow-[0_0_0_1px_rgba(0,0,0,0.2),0_4px_16px_-4px_var(--color-accent-soft)] ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function SecondaryButton({
  children,
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={`px-3 py-1.5 rounded-lg text-sm font-medium bg-surface-2 text-ink border border-hairline hover:border-hairline-strong transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export const inputClass =
  "bg-surface-2 border border-hairline rounded-lg px-2 py-1 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-colors";
