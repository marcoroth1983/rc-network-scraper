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
