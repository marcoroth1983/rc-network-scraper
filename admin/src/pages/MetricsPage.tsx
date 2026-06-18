import { useEffect, useState } from 'react';
import type { MetricsSummary, MetricsTimeseries } from '../types/api';
import { getMetricsSummary, getMetricsTimeseries } from '../api/client';
import { KpiCard } from '../components/KpiCard';
import { TrendChart } from '../components/TrendChart';

const RANGES = [7, 30, 90] as const;

export default function MetricsPage() {
  const [summary, setSummary] = useState<MetricsSummary | null>(null);
  const [series, setSeries] = useState<MetricsTimeseries | null>(null);
  const [days, setDays] = useState<number>(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const [s, t] = await Promise.all([getMetricsSummary(), getMetricsTimeseries(days)]);
        if (active) {
          setSummary(s);
          setSeries(t);
        }
      } catch (err: unknown) {
        if (active) setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [days]);

  return (
    <div>
      {/* Range toggle */}
      <div role="group" aria-label="Zeitraum" className="flex gap-2">
        {RANGES.map((r) => (
          <button
            key={r}
            type="button"
            onClick={() => setDays(r)}
            aria-pressed={days === r}
            className={[
              'rounded-control text-[13px] font-medium px-3 py-1.5 transition-colors',
              days === r
                ? 'bg-surface-active text-text-primary'
                : 'bg-surface text-text-secondary hover:bg-surface-2',
            ].join(' ')}
          >
            {r} Tage
          </button>
        ))}
      </div>

      {/* Error state */}
      {error && (
        <p role="alert" className="text-danger text-sm py-6">
          Fehler: {error}
        </p>
      )}

      {/* KPI grid */}
      {!error && (
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4 my-6">
          {loading && !summary ? (
            <>
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="animate-pulse bg-surface rounded-card h-[80px]" />
              ))}
            </>
          ) : summary ? (
            <>
              <KpiCard
                label="Nutzer gesamt"
                value={summary.users_total}
                sub={`${summary.users_pending} wartend`}
              />
              <KpiCard label="Freigeschaltet" value={summary.users_approved} />
              <KpiCard
                label="Aktiv 7T"
                value={summary.users_active_7d}
                sub={`${summary.users_active_30d} in 30 T`}
              />
              <KpiCard label="Annoncen gesamt" value={summary.listings_total} />
              <KpiCard label="Favoriten" value={summary.favorites_total} />
              <KpiCard label="Gespeicherte Suchen" value={summary.saved_searches_total} />
            </>
          ) : null}
        </div>
      )}

      {/* Chart grid */}
      {!error && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <TrendChart
            title="Neue Annoncen / Tag"
            data={series?.listings_new ?? []}
            type="bar"
            accent="#3FD984"
            loading={loading}
          />
          <TrendChart
            title="Verkauft / Tag"
            data={series?.listings_closed ?? []}
            type="bar"
            accent="#F75555"
            loading={loading}
          />
          <TrendChart
            title="Neue Nutzer / Tag"
            data={series?.users_new ?? []}
            type="bar"
            accent="#2E6BFF"
            loading={loading}
          />
          <TrendChart
            title="Logins / Tag"
            data={series?.logins ?? []}
            type="line"
            accent="#3FD984"
            loading={loading}
          />
          <TrendChart
            title="Benachrichtigungen / Tag"
            data={series?.notifications ?? []}
            type="line"
            accent="#F5B544"
            loading={loading}
          />
        </div>
      )}
    </div>
  );
}
