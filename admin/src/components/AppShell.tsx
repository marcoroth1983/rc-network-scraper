import { useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';

import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

const titleMap: Record<string, string> = {
  '/': 'Übersicht',
  '/metrics': 'Metriken',
  '/llm': 'LLM-Kaskade',
  '/users': 'Nutzer',
};

export function AppShell() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const { pathname } = useLocation();

  const title = titleMap[pathname] ?? 'RC-Scout Ops';

  return (
    <div className="flex min-h-dvh bg-bg-app">
      <Sidebar isOpen={drawerOpen} onClose={() => setDrawerOpen(false)} />

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar title={title} onMenuClick={() => setDrawerOpen(true)} />
        <main className="p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
