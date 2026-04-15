/**
 * Format a numeric price to German locale display string.
 * Falls back to the raw price string if price_numeric is null.
 */
export function formatPrice(price_numeric: number | null, price: string | null): string {
  if (price_numeric != null) {
    return new Intl.NumberFormat('de-DE', {
      style: 'currency',
      currency: 'EUR',
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    }).format(price_numeric);
  }
  return price ?? '–';
}

export function formatDate(iso: string | null): string {
  if (!iso) return '–';
  return new Date(iso).toLocaleDateString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });
}

/**
 * Return a German-language relative time string for an ISO timestamp.
 * Uses the wall-clock distance from now to the given time.
 * Examples: "vor 3 Sek", "vor 5 Min", "vor 2 Std", "vor 4 Tagen"
 */
export function formatRelativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(diffMs)) return '–';
  if (diffMs < 0) return 'gerade eben';
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return `vor ${diffSec} Sek`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `vor ${diffMin} Min`;
  const diffHrs = Math.floor(diffMin / 60);
  if (diffHrs < 24) return `vor ${diffHrs} Std`;
  const diffDays = Math.floor(diffHrs / 24);
  return `vor ${diffDays} Tagen`;
}
