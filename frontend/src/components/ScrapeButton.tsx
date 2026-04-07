import { useState } from 'react';
import { triggerScrape } from '../api/client';
import type { ScrapeSummary } from '../types/api';

export default function ScrapeButton({ onDone }: { onDone?: () => void }) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScrapeSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleScrape() {
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const summary = await triggerScrape();
      setResult(summary);
      onDone?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex items-center gap-3">
      <button
        onClick={handleScrape}
        disabled={loading}
        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-brand text-white text-sm font-semibold hover:bg-brand-dark active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {loading && (
          <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
        )}
        {loading ? 'Scraping…' : 'Scrape starten'}
      </button>

      {result && !loading && (
        <span className="text-xs text-gray-600">
          ✓ {result.new} neu, {result.updated} aktualisiert, {result.skipped} übersprungen
        </span>
      )}

      {error && !loading && (
        <span className="text-xs text-red-500">Fehler: {error}</span>
      )}
    </div>
  );
}
