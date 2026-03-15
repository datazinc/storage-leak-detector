import { clsx } from "clsx";
import type { ReactNode } from "react";

export function Card({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={clsx(
        "bg-slate-900 border border-slate-800 rounded-lg p-5",
        className
      )}
    >
      {children}
    </div>
  );
}

export function StatCard({
  label,
  value,
  sub,
  color = "text-white",
}: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
}) {
  return (
    <Card>
      <p className="text-xs text-slate-500 uppercase tracking-wide mb-1">
        {label}
      </p>
      <p className={clsx("text-2xl font-semibold font-mono", color)}>
        {value}
      </p>
      {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
    </Card>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  const cls = {
    critical: "bg-red-500/20 text-red-400 border-red-500/30",
    warning: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    info: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  }[severity] ?? "bg-slate-700 text-slate-400";

  return (
    <span
      className={clsx(
        "inline-block px-2 py-0.5 text-[11px] font-medium rounded border uppercase",
        cls
      )}
    >
      {severity}
    </span>
  );
}
