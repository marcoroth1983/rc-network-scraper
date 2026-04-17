import { useEffect, useState } from 'react';
import type { AuthUser } from '../hooks/useAuth';
import type { NotificationPrefs } from '../types/api';
import {
  linkTelegram,
  unlinkTelegram,
  getNotificationPrefs,
  updateNotificationPrefs,
} from '../api/client';
import { useConfirm } from './ConfirmDialog';
import { formatRelativeTime } from '../utils/format';

interface Props {
  user: AuthUser;
  onUserReload: () => void;
}

interface ToggleRow {
  key: keyof NotificationPrefs;
  label: string;
}

const TOGGLE_ROWS: ToggleRow[] = [
  { key: 'new_search_results', label: 'Neue Suchtreffer' },
  { key: 'fav_sold',           label: 'Verkauft' },
  { key: 'fav_price',          label: 'Preis' },
  { key: 'fav_deleted',        label: 'Gelöscht' },
  { key: 'fav_indicator',      label: 'Preisbewertung' },
];

// Spinner used for in-flight PUT requests
function Spinner() {
  return (
    <span
      className="inline-block w-3.5 h-3.5 rounded-full border-2 shrink-0"
      style={{
        borderColor: 'rgba(167,139,250,0.3)',
        borderTopColor: '#A78BFA',
        animation: 'spin 0.7s linear infinite',
      }}
      aria-hidden="true"
    />
  );
}

export function TelegramPanel({ user, onUserReload }: Props) {
  const confirm = useConfirm();

  const isLinked = user.telegram_chat_id != null;

  // Notification prefs state — only loaded when linked
  const [prefs, setPrefs] = useState<NotificationPrefs | null>(null);
  const [prefsLoading, setPrefsLoading] = useState(false);
  const [prefsError, setPrefsError] = useState<string | null>(null);

  // Which pref key has a PUT in-flight
  const [inflightKey, setInflightKey] = useState<keyof NotificationPrefs | null>(null);

  // Action states
  const [linking, setLinking] = useState(false);
  const [unlinking, setUnlinking] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLinked) {
      setPrefs(null);
      setPrefsError(null);
      return;
    }
    let cancelled = false;
    setPrefsLoading(true);
    setPrefsError(null);
    getNotificationPrefs()
      .then((data) => {
        if (!cancelled) {
          setPrefs(data);
          setPrefsLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setPrefsError(err instanceof Error ? err.message : 'Fehler beim Laden');
          setPrefsLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [isLinked]);

  async function handleLink() {
    setLinking(true);
    setActionError(null);
    try {
      const result = await linkTelegram();
      // Defensive allowlist: the deeplink comes from our backend but we refuse to
      // open anything that isn't an https://t.me/… URL. Prevents accidental
      // navigation if the backend response is ever misconfigured.
      let parsed: URL;
      try {
        parsed = new URL(result.deeplink);
      } catch {
        setActionError('Ungültiger Deeplink vom Server');
        return;
      }
      if (parsed.protocol !== 'https:' || parsed.hostname !== 't.me') {
        setActionError('Ungültiger Deeplink vom Server');
        return;
      }
      // Mobile browsers are unreliable at handing the t.me URL off to the
      // native Telegram app — many just render the t.me landing page.
      // Strategy: try the native tg:// scheme first (opens the installed
      // app directly). If the page is still visible after 800ms, assume
      // the app is not installed and fall back to the https://t.me/ URL,
      // which at least shows Telegram's "Open in Telegram" landing page.
      const botName = parsed.pathname.replace(/^\//, '');
      const startToken = parsed.searchParams.get('start') ?? '';
      const tgUrl = `tg://resolve?domain=${encodeURIComponent(botName)}&start=${encodeURIComponent(startToken)}`;

      let switchedAway = false;
      const onVisibility = () => {
        if (document.hidden) switchedAway = true;
      };
      document.addEventListener('visibilitychange', onVisibility);

      // First: try the native scheme.
      window.location.href = tgUrl;

      // Fallback: if still visible after 800ms, the app didn't catch the URL.
      window.setTimeout(() => {
        document.removeEventListener('visibilitychange', onVisibility);
        if (!switchedAway && !document.hidden) {
          window.location.href = result.deeplink;
        }
      }, 800);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Verknüpfung fehlgeschlagen');
    } finally {
      setLinking(false);
    }
  }

  async function handleUnlink() {
    const ok = await confirm({
      title: 'Telegram trennen?',
      message: 'Die Verbindung zu deinem Telegram-Account wird entfernt. Du erhältst keine Benachrichtigungen mehr.',
      confirmLabel: 'Trennen',
      cancelLabel: 'Abbrechen',
      destructive: true,
    });
    if (!ok) return;

    setUnlinking(true);
    setActionError(null);
    try {
      await unlinkTelegram();
      onUserReload();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Trennung fehlgeschlagen');
    } finally {
      setUnlinking(false);
    }
  }

  async function handleToggle(key: keyof NotificationPrefs, currentValue: boolean) {
    if (!prefs || inflightKey !== null) return;
    const newValue = !currentValue;

    // Optimistic update
    setPrefs((prev) => prev ? { ...prev, [key]: newValue } : prev);
    setInflightKey(key);

    try {
      const updated = await updateNotificationPrefs({ [key]: newValue });
      setPrefs(updated);
    } catch {
      // Revert optimistic update on failure
      setPrefs((prev) => prev ? { ...prev, [key]: currentValue } : prev);
    } finally {
      setInflightKey(null);
    }
  }

  return (
    <div
      className="w-full rounded-2xl p-4 sm:p-6"
      style={{
        background: 'rgba(15,15,35,0.6)',
        border: '1px solid rgba(255,255,255,0.08)',
        backdropFilter: 'blur(20px)',
        boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
      }}
    >
      {/* Panel header */}
      <div className="flex items-start justify-between gap-3 mb-4">
        <p className="text-sm font-semibold" style={{ color: '#A78BFA' }}>
          Benachrichtigungen (Telegram)
        </p>
      </div>

      {/* Connection status */}
      <div className="flex items-center justify-between gap-3 mb-4">
        {isLinked ? (
          <p className="text-sm" style={{ color: 'rgba(248,250,252,0.75)' }}>
            {'\u2705'} Verbunden seit{' '}
            {user.telegram_linked_at ? formatRelativeTime(user.telegram_linked_at) : '–'}
          </p>
        ) : (
          <p className="text-sm" style={{ color: 'rgba(248,250,252,0.45)' }}>
            Nicht verbunden
          </p>
        )}

        {isLinked ? (
          <button
            type="button"
            onClick={handleUnlink}
            disabled={unlinking}
            className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-150 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              background: 'rgba(236,72,153,0.08)',
              border: '1px solid rgba(236,72,153,0.35)',
              color: '#EC4899',
            }}
            onPointerEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = 'rgba(236,72,153,0.16)';
            }}
            onPointerLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = 'rgba(236,72,153,0.08)';
            }}
            aria-label="Telegram-Verbindung trennen"
          >
            {unlinking ? 'Trennen…' : 'Trennen'}
          </button>
        ) : (
          <button
            type="button"
            onClick={handleLink}
            disabled={linking}
            className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-150 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              background: 'rgba(167,139,250,0.08)',
              border: '1px solid rgba(167,139,250,0.35)',
              color: '#A78BFA',
            }}
            onPointerEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = 'rgba(167,139,250,0.16)';
            }}
            onPointerLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = 'rgba(167,139,250,0.08)';
            }}
            aria-label="Mit Telegram verbinden"
          >
            {linking ? 'Verbinden…' : 'Mit Telegram verbinden'}
          </button>
        )}
      </div>

      {/* Action error */}
      {actionError && (
        <p
          className="text-xs mb-3 px-3 py-2 rounded-lg"
          style={{
            background: 'rgba(236,72,153,0.1)',
            color: '#EC4899',
            border: '1px solid rgba(236,72,153,0.25)',
          }}
        >
          {actionError}
        </p>
      )}

      {/* Notification toggles — only when linked */}
      {isLinked && (
        <>
          <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)' }} className="mb-4" />

          {prefsLoading && (
            <p className="text-sm text-center py-4" style={{ color: 'rgba(248,250,252,0.35)' }}>
              Lade Einstellungen…
            </p>
          )}

          {!prefsLoading && prefsError && (
            <p className="text-sm text-center py-4" style={{ color: '#EC4899' }}>
              Fehler: {prefsError}
            </p>
          )}

          {!prefsLoading && !prefsError && prefs && (
            <ul className="space-y-3">
              {TOGGLE_ROWS.map(({ key, label }) => {
                const isInFlight = inflightKey === key;
                const value = prefs[key];
                return (
                  <li key={key} className="flex items-center justify-between gap-3">
                    <span className="text-sm" style={{ color: 'rgba(248,250,252,0.75)' }}>
                      {label}
                    </span>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={value}
                      aria-label={label}
                      disabled={inflightKey !== null}
                      onClick={() => handleToggle(key, value)}
                      className="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-aurora-indigo/50 disabled:cursor-not-allowed disabled:opacity-60"
                      style={{
                        background: value
                          ? 'linear-gradient(135deg, rgba(99,102,241,0.9), rgba(139,92,246,0.9))'
                          : 'rgba(255,255,255,0.1)',
                        border: value
                          ? '1px solid rgba(139,92,246,0.5)'
                          : '1px solid rgba(255,255,255,0.15)',
                      }}
                    >
                      {isInFlight ? (
                        <span className="absolute inset-0 flex items-center justify-center">
                          <Spinner />
                        </span>
                      ) : (
                        <span
                          className="inline-block h-3.5 w-3.5 rounded-full transition-transform duration-200"
                          style={{
                            background: '#fff',
                            transform: value ? 'translateX(18px)' : 'translateX(2px)',
                            boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
                          }}
                          aria-hidden="true"
                        />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
