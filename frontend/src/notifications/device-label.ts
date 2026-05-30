/** Best-effort UA → human label. Never throws — falls back to "Unbekanntes Gerät". */
export function getDeviceLabel(ua: string = navigator.userAgent): string {
  const lower = ua.toLowerCase();
  let device: string | null = null;
  if (lower.includes('iphone')) device = 'iPhone';
  else if (lower.includes('ipad')) device = 'iPad';
  else if (lower.includes('android')) device = 'Android';
  else if (lower.includes('windows')) device = 'Windows';
  else if (lower.includes('macintosh') || lower.includes('mac os')) device = 'Mac';
  else if (lower.includes('linux')) device = 'Linux';

  let browser: string | null = null;
  if (lower.includes('edg/')) browser = 'Edge';
  else if (lower.includes('chrome/') && !lower.includes('chromium')) browser = 'Chrome';
  else if (lower.includes('firefox/')) browser = 'Firefox';
  else if (lower.includes('safari/') && !lower.includes('chrome')) browser = 'Safari';

  if (device && browser) return `${device} · ${browser}`;
  if (device) return device;
  if (browser) return browser;
  return 'Unbekanntes Gerät';
}
