import type { ReactNode } from 'react';

interface KpiCardProps {
  icon?: ReactNode;
  label: string;
  value: number;
  sub?: string;
}

export function KpiCard({ icon, label, value, sub }: KpiCardProps) {
  return (
    <div className="bg-surface rounded-card p-5 border border-border">
      {icon && (
        <span className="rounded-icon bg-surface-2 p-2 mb-3 inline-flex">
          {icon}
        </span>
      )}
      <p className="text-[12px] font-medium text-text-secondary">{label}</p>
      <p className="text-[28px] font-bold tabular-nums text-text-primary">{value}</p>
      {sub && <p className="text-[12px] text-text-tertiary mt-0.5">{sub}</p>}
    </div>
  );
}
