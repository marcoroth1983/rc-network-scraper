import { Link, useLocation } from 'react-router-dom';
import { LayoutDashboard, BarChart3, Cpu, Users, LogOut, X } from 'lucide-react';

import { cn } from '@/lib/utils';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { useAuth } from '../hooks/useAuth';

interface NavItem {
  label: string;
  path: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
}

const navAllgemein: NavItem[] = [
  { label: 'Übersicht', path: '/', icon: LayoutDashboard },
  { label: 'Metriken', path: '/metrics', icon: BarChart3 },
  { label: 'LLM-Kaskade', path: '/llm', icon: Cpu },
  { label: 'Nutzer', path: '/users', icon: Users },
];

function getInitials(name: string | null, email: string): string {
  if (name) {
    const parts = name.trim().split(/\s+/);
    if (parts.length >= 2) {
      return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }
    return parts[0].slice(0, 2).toUpperCase();
  }
  return email.slice(0, 2).toUpperCase();
}

export interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

export function Sidebar({ isOpen, onClose }: SidebarProps) {
  const { pathname } = useLocation();
  const { user, logout } = useAuth();

  const sidebarContent = (
    <div className="flex h-full w-[240px] flex-col bg-bg-sidebar">
      {/* Brand row */}
      <div className="flex items-center gap-3 px-4 py-5">
        {/* Gradient diamond logo */}
        <div
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-icon bg-gradient-to-br from-[#4F7BFF] to-[#8B5CF6]"
          aria-hidden="true"
        >
          <span className="text-xs font-bold text-white">R</span>
        </div>
        <span className="text-sm font-semibold text-text-primary">RC-Scout Ops</span>
        {/* Close button — only shown when drawer is open on mobile */}
        <button
          className="ml-auto lg:hidden text-text-secondary hover:text-text-primary"
          onClick={onClose}
          aria-label="Sidebar schliessen"
        >
          <X size={18} />
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2 pb-4">
        {/* Section: ALLGEMEIN */}
        <p className="mb-1 px-2 pt-4 text-[11px] font-semibold uppercase tracking-wide text-text-tertiary">
          Allgemein
        </p>
        <ul className="space-y-0.5">
          {navAllgemein.map((item) => {
            const isActive = pathname === item.path;
            return (
              <li key={item.path}>
                <Link
                  to={item.path}
                  onClick={onClose}
                  className={cn(
                    'flex h-10 items-center gap-3 rounded-control px-3 text-sm transition-colors',
                    isActive
                      ? 'bg-surface-active text-text-primary font-medium'
                      : 'text-text-secondary hover:bg-surface-2 hover:text-text-primary'
                  )}
                  aria-current={isActive ? 'page' : undefined}
                >
                  <item.icon size={18} />
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>

        {/* Section: SYSTEM */}
        <p className="mb-1 px-2 pt-6 text-[11px] font-semibold uppercase tracking-wide text-text-tertiary">
          System
        </p>
        <ul className="space-y-0.5">
          <li>
            <button
              onClick={logout}
              className="flex h-10 w-full items-center gap-3 rounded-control px-3 text-sm text-text-secondary transition-colors hover:bg-surface-2 hover:text-text-primary"
            >
              <LogOut size={18} />
              Abmelden
            </button>
          </li>
        </ul>
      </nav>

      {/* Profile card */}
      {user && (
        <div className="border-t border-border p-3">
          <div className="flex items-center gap-3 rounded-control bg-surface p-3">
            <Avatar className="h-8 w-8">
              <AvatarFallback className="text-xs">
                {getInitials(user.name, user.email)}
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-text-primary">
                {user.name ?? user.email}
              </p>
              <p className="truncate text-[11px] text-text-tertiary">{user.email}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  return (
    <>
      {/* Desktop sidebar — always visible on lg+ */}
      <aside className="hidden min-h-dvh lg:block shrink-0">
        {sidebarContent}
      </aside>

      {/* Mobile drawer */}
      {isOpen && (
        <div className="lg:hidden">
          {/* Scrim */}
          <div
            className="fixed inset-0 z-10 bg-black/50"
            onClick={onClose}
            aria-hidden="true"
          />
          {/* Drawer panel */}
          <aside className="fixed left-0 top-0 z-20 h-full">
            {sidebarContent}
          </aside>
        </div>
      )}
    </>
  );
}
