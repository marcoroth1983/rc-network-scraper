import { useCallback, useEffect, useState } from 'react';
import type { MetricsSummary, MetricsTimeseries } from '../types/api';
import { getMetricsSummary, getMetricsTimeseries } from '../api/client';
import { MiniChart } from './MiniChart';

const cardStyle: React.CSSProperties = {
  background: 'rgba(15, 15, 35, 0.6)',
  border: '1px solid rgba(255, 255, 255, 0.08)',
  backdropFilter: 'blur(16px)',
  WebkitBackdropFilter: 'blur(16px)',
  boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)',
};

const RANGES = [7, 30, 90] as const;

function Tile({ label, value, sub }: { label: string; value: number; sub?: string }) {
  return (
    <div className="rounded-xl p-3" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}>
      <p className="text-[11px]" style={{ color: 'rgba(248,250,252,0.5)' }}>{label}</p>
      <p className="text-2xl font-bold tabular-nums" style={{ color: '#F8FAFC' }}>{value}</p>
      {sub && <p className="text-[11px] mt-0.5" style={{ color: 'rgba(248,250,252,0.4)' }}>{sub}</p>}
    </div>
  );
}

export function MetricsPanel() {
  const [summary, setSummary] = useState<MetricsSummary | null>(null);
  const [series, setSeries] = useState<MetricsTimeseries | null>(null);
  const [days, setDays] = useState<number>(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (range: number) => {
    setLoading(true);
    setError(null);
    try {
      const [s, t] = await Promise.all([getMetricsSummary(), getMetricsTimeseries(range)]);
      setSummary(s);
      setSeries(t);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(days); }, [load, days]);

  return (
    <section className="w-full rounded-2xl p-4 sm:p-6" style={cardStyle}>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm font-semibold" style={{ color: '#A78BFA' }}>Nutzungs-Metriken</p>
        <div role="group" aria-label="Zeitraum" className="flex gap-1">
          {RANGES.map((r) => (
            <button key={r} type="button" onClick={() => setDays(r)}
              aria-pressed={days === r}
              className="px-3 py-2 rounded-lg text-xs font-medium transition-colors"
              style={days === r
                ? { background: 'linear-gradient(135deg, rgba(99,102,241,0.9), rgba(139,92,246,0.9))', color: '#fff' }
                : { background: 'rgba(255,255,255,0.06)', color: 'rgba(248,250,252,0.6)' }}>
              {r} Tage
            </button>
          ))}
        </div>
      </div>

      {loading && <p className="text-sm py-6 text-center" style={{ color: 'rgba(248,250,252,0.35)' }}>Lade Metriken…</p>}
      {!loading && error && <p role="alert" className="text-sm py-6 text-center" style={{ color: '#EC4899' }}>Fehler: {error}</p>}

      {!loading && !error && summary && series && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 mb-6">
            <Tile label="Nutzer gesamt" value={summary.users_total} sub={`${summary.users_pending} wartend`} />
            <Tile label="Freigeschaltet" value={summary.users_approved} />
            <Tile label="Aktiv (7 T)" value={summary.users_active_7d} sub={`${summary.users_active_30d} in 30 T`} />
            <Tile label="Annoncen gesamt" value={summary.listings_total} />
            <Tile label="Favoriten" value={summary.favorites_total} />
            <Tile label="Gespeicherte Suchen" value={summary.saved_searches_total} />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <MiniChart title="Neue Annoncen / Tag" data={series.listings_new} type="bar" accent="#6366F1" />
            <MiniChart title="Verkauft / Tag" data={series.listings_closed} type="bar" accent="#EC4899" />
            <MiniChart title="Neue Nutzer / Tag" data={series.users_new} type="bar" accent="#A78BFA" />
            <MiniChart title="Logins / Tag" data={series.logins} type="line" accent="#34D399" />
            <MiniChart title="Benachrichtigungen / Tag" data={series.notifications} type="line" accent="#FBBF24" />
          </div>
        </>
      )}
    </section>
  );
}
