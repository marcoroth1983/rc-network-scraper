import { Bell, Info, Menu } from 'lucide-react';

import { cn } from '@/lib/utils';

export interface TopBarProps {
  title: string;
  onMenuClick: () => void;
}

export function TopBar({ title, onMenuClick }: TopBarProps) {
  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-border bg-bg-app px-6">
      {/* Left: breadcrumb + page title */}
      <div>
        <p className="text-[11px] font-medium uppercase tracking-wide text-text-tertiary">
          RC-Scout Ops
        </p>
        <h1 className="text-2xl font-semibold text-text-primary">{title}</h1>
      </div>

      {/* Right cluster */}
      <div className="flex items-center gap-2">
        <IconButton label="Benachrichtigungen">
          <Bell size={18} />
        </IconButton>
        <IconButton label="Info">
          <Info size={18} />
        </IconButton>
        {/* Hamburger — only on mobile */}
        <button
          onClick={onMenuClick}
          className={cn(
            'flex h-9 w-9 items-center justify-center rounded-full bg-surface text-text-secondary transition-colors hover:bg-surface-2 hover:text-text-primary lg:hidden'
          )}
          aria-label="Navigation oeffnen"
        >
          <Menu size={18} />
        </button>
      </div>
    </header>
  );
}

function IconButton({
  children,
  label,
}: {
  children: React.ReactNode;
  label: string;
}) {
  return (
    <button
      className="flex h-9 w-9 items-center justify-center rounded-full bg-surface text-text-secondary transition-colors hover:bg-surface-2 hover:text-text-primary"
      aria-label={label}
    >
      {children}
    </button>
  );
}
