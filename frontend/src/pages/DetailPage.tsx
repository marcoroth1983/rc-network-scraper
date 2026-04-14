import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { getListing, toggleSold, toggleFavorite, getListingsByAuthor } from '../api/client';
import { useAuth } from '../hooks/useAuth';
import ListingCard from '../components/ListingCard';
import type { ListingDetail, ListingSummary } from '../types/api';
import { formatPrice } from '../utils/format';

function formatDate(iso: string | null): string {
  if (!iso) return '–';
  return new Date(iso).toLocaleDateString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

type PriceIndicator = 'deal' | 'fair' | 'expensive' | null;

function buildTooltip(label: string, median: number | null | undefined, count: number | null | undefined): string {
  if (median == null || count == null) return label;
  const medianStr = median.toLocaleString('de-DE', { maximumFractionDigits: 0 });
  return `${label} · Ø ${medianStr} € bei ${count} Inseraten`;
}

function PriceIndicatorBadge({ indicator, median, count }: { indicator: PriceIndicator; median?: number | null; count?: number | null }) {
  if (indicator === 'deal') {
    return (
      <span
        className="text-xs font-semibold px-2 py-0.5 rounded-full cursor-default"
        style={{ background: 'rgba(52,211,153,0.15)', color: '#34D399', border: '1px solid rgba(52,211,153,0.3)' }}
        title={buildTooltip('Günstig', median, count)}
      >
        Günstig
      </span>
    );
  }
  if (indicator === 'fair') {
    return (
      <span
        className="text-xs font-semibold px-2 py-0.5 rounded-full cursor-default"
        style={{ background: 'rgba(167,139,250,0.15)', color: '#A78BFA', border: '1px solid rgba(167,139,250,0.3)' }}
        title={buildTooltip('Gut', median, count)}
      >
        Gut
      </span>
    );
  }
  if (indicator === 'expensive') {
    return (
      <span
        className="text-xs font-semibold px-2 py-0.5 rounded-full cursor-default"
        style={{ background: 'rgba(251,146,60,0.15)', color: '#FB923C', border: '1px solid rgba(251,146,60,0.3)' }}
        title={buildTooltip('Teuer', median, count)}
      >
        Teuer
      </span>
    );
  }
  return null;
}

/** Convert snake_case English attribute keys to readable German-friendly labels. */
function humanizeAttributeKey(key: string): string {
  const knownLabels: Record<string, string> = {
    wingspan_mm: 'Spannweite (mm)',
    weight_g: 'Gewicht (g)',
    scale: 'Maßstab',
    battery: 'Akku',
    motor: 'Motor',
    channels: 'Kanäle',
    servos_included: 'Servos inkl.',
    esc: 'Regler',
    length_mm: 'Länge (mm)',
    height_mm: 'Höhe (mm)',
    blade_size: 'Rotorblattgröße',
    frame_size: 'Rahmengröße',
  };
  return knownLabels[key] ?? key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

interface FieldProps {
  label: string;
  value: string | null | undefined;
  highlight?: boolean;
}

function Field({ label, value, highlight }: FieldProps) {
  return (
    <div
      className="p-3 rounded-xl"
      style={{ background: 'rgba(255,255,255,0.03)' }}
    >
      <dt
        className="text-xs font-medium uppercase tracking-wide mb-0.5"
        style={{ color: 'rgba(248,250,252,0.35)' }}
      >
        {label}
      </dt>
      <dd
        className="text-sm font-medium"
        style={{ color: highlight ? '#FDE68A' : '#F8FAFC' }}
      >
        {value ?? '–'}
      </dd>
    </div>
  );
}

function Spinner() {
  return (
    <div className="flex justify-center py-16">
      <div
        className="animate-spin h-8 w-8 border-4 rounded-full"
        style={{ borderColor: '#A78BFA', borderTopColor: 'transparent' }}
      />
    </div>
  );
}

interface AuthorListingsSectionProps {
  heading: string;
  items: ListingSummary[];
}

function AuthorListingsSection({ heading, items }: AuthorListingsSectionProps) {
  return (
    <div className="mt-6">
      <h2
        className="text-xs font-semibold uppercase tracking-wider mb-3 px-1"
        style={{ color: 'rgba(248,250,252,0.35)' }}
      >
        {heading}
      </h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {items.map((item) => (
          <div
            key={item.id}
            className="rounded-2xl overflow-hidden"
            style={{
              background: 'rgba(15, 15, 35, 0.6)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
            }}
          >
            <ListingCard listing={item} />
          </div>
        ))}
      </div>
    </div>
  );
}

const PLZ_LAT_KEY = 'rcn_ref_lat';
const PLZ_LON_KEY = 'rcn_ref_lon';
const PLZ_CITY_STORAGE_KEY = 'rcn_ref_plz_city';

/** Haversine distance in km between two lat/lon points. */
function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

export default function DetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [listing, setListing] = useState<ListingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [soldPending, setSoldPending] = useState(false);
  const [favoritePending, setFavoritePending] = useState(false);
  const [authorListings, setAuthorListings] = useState<ListingSummary[]>([]);
  const [shareCopied, setShareCopied] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(null);
    setAuthorListings([]);
    getListing(Number(id))
      .then((data) => {
        setListing(data);
        setLoading(false);
        return getListingsByAuthor(data.author, data.id);
      })
      .then(setAuthorListings)
      .catch((err: Error) => {
        setError(err.message);
        setLoading(false);
      });
  }, [id]);

  if (loading) return <Spinner />;

  if (error) {
    return (
      <div
        className="rounded-xl p-4"
        style={{
          background: 'rgba(236,72,153,0.08)',
          border: '1px solid rgba(236,72,153,0.3)',
          color: '#EC4899',
        }}
      >
        Fehler: {error}
      </div>
    );
  }

  if (!listing) return null;

  const location = [listing.plz, listing.city].filter(Boolean).join(' ') || '–';

  // Compute distance from user's saved reference location (stored by FilterPanel)
  const refCity = localStorage.getItem(PLZ_CITY_STORAGE_KEY);
  const refLat = parseFloat(localStorage.getItem(PLZ_LAT_KEY) ?? '');
  const refLon = parseFloat(localStorage.getItem(PLZ_LON_KEY) ?? '');
  const distanceKm: number | null =
    listing.latitude && listing.longitude && !isNaN(refLat) && !isNaN(refLon)
      ? haversineKm(refLat, refLon, listing.latitude, listing.longitude)
      : null;
  const mapsHref = listing.latitude && listing.longitude
    ? `https://www.google.com/maps/dir/?api=1&destination=${listing.latitude},${listing.longitude}`
    : `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(location + ', Deutschland')}`;

  async function handleToggleSold() {
    const next = !listing!.is_sold;
    if (next && !window.confirm(`"${listing!.title}" als verkauft markieren?`)) return;
    setSoldPending(true);
    try {
      await toggleSold(listing!.id, next);
      setListing((l) => l ? { ...l, is_sold: next } : l);
    } finally {
      setSoldPending(false);
    }
  }

  async function handleToggleFavorite() {
    setFavoritePending(true);
    try {
      const next = !listing!.is_favorite;
      await toggleFavorite(listing!.id, next);
      setListing((l) => l ? { ...l, is_favorite: next } : l);
    } finally {
      setFavoritePending(false);
    }
  }

  async function handleShare() {
    if (!listing) return;
    const url = `${window.location.origin}/listings/${listing.id}`;
    const title = listing.title ?? 'RC-Network Inserat';

    if (typeof navigator.share === 'function') {
      try {
        await navigator.share({ url, title });
        return;
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        // Other errors fall through to clipboard fallback.
      }
    }
    try {
      await navigator.clipboard.writeText(url);
      setShareCopied(true);
      setTimeout(() => setShareCopied(false), 2000);
    } catch {
      // Clipboard unavailable — no UI fallback for this hobby scope.
    }
  }

  return (
    <div className="w-full pt-3 pb-6 sm:pt-0 sm:pb-10">
      {/* Main content card */}
      <div
        className="rounded-2xl overflow-hidden"
        style={{
          background: 'rgba(15, 15, 35, 0.6)',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          backdropFilter: 'blur(20px) saturate(1.2)',
          boxShadow: '0 0 60px rgba(99,102,241,0.06), 0 4px 16px rgba(0,0,0,0.2)',
        }}
      >
        <div className="p-4 sm:p-6">
          {/* Title row + actions */}
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-4">
            <h1 className="text-2xl font-bold leading-tight" style={{ color: '#F8FAFC' }}>
              {listing.title}
            </h1>
            <div className="flex items-center gap-2 shrink-0">
              {/* Favorite star */}
              <button
                onClick={handleToggleFavorite}
                disabled={favoritePending}
                aria-label={listing.is_favorite ? 'Von Merkliste entfernen' : 'Merken'}
                className="p-1.5 rounded-full transition-all duration-200 disabled:opacity-50"
                style={{
                  background: listing.is_favorite ? 'rgba(253,230,138,0.12)' : 'rgba(255,255,255,0.06)',
                  border: `1px solid ${listing.is_favorite ? 'rgba(253,230,138,0.3)' : 'rgba(255,255,255,0.1)'}`,
                }}
              >
                <svg
                  className="w-5 h-5 transition-colors"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                  fill={listing.is_favorite ? 'currentColor' : 'none'}
                  style={{ color: listing.is_favorite ? '#FDE68A' : 'rgba(248,250,252,0.4)' }}
                  aria-hidden="true"
                >
                  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                </svg>
              </button>

              {/* Share button */}
              <button
                onClick={handleShare}
                aria-label="Link zu diesem Inserat teilen"
                className="p-1.5 rounded-full transition-all duration-200"
                style={{
                  background: shareCopied ? 'rgba(45,212,191,0.15)' : 'rgba(255,255,255,0.06)',
                  border: `1px solid ${shareCopied ? 'rgba(45,212,191,0.35)' : 'rgba(255,255,255,0.1)'}`,
                }}
              >
                {shareCopied ? (
                  <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="#2DD4BF" strokeWidth={2} aria-hidden="true">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                ) : (
                  <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="rgba(248,250,252,0.6)" strokeWidth={2} aria-hidden="true">
                    <circle cx="18" cy="5" r="3" />
                    <circle cx="6" cy="12" r="3" />
                    <circle cx="18" cy="19" r="3" />
                    <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
                    <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
                  </svg>
                )}
              </button>

              {/* Sold toggle — admin only */}
              {isAdmin && <button
                onClick={handleToggleSold}
                disabled={soldPending}
                className="text-xs font-semibold px-3 py-1.5 rounded-full transition-all duration-200 disabled:opacity-50"
                style={
                  listing.is_sold
                    ? {
                        background: 'rgba(236,72,153,0.12)',
                        border: '1px solid rgba(236,72,153,0.35)',
                        color: '#EC4899',
                      }
                    : {
                        background: 'rgba(255,255,255,0.06)',
                        border: '1px solid rgba(255,255,255,0.12)',
                        color: 'rgba(248,250,252,0.6)',
                      }
                }
              >
                {listing.is_sold ? 'Verkauft ✓' : 'Als verkauft markieren'}
              </button>}
            </div>
          </div>

          {/* 3-column hero row: primary metadata | hero image | secondary metadata */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 lg:gap-6 mb-6 pb-6"
               style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>

            {/* Column 1: primary metadata */}
            <dl className="lg:col-span-3 flex flex-col gap-3">
              {/* Price — highlighted yellow */}
              <div
                className="p-3 rounded-xl"
                style={{ background: 'rgba(253,230,138,0.06)', border: '1px solid rgba(253,230,138,0.12)' }}
              >
                <dt className="text-xs font-medium uppercase tracking-wide mb-0.5" style={{ color: 'rgba(248,250,252,0.35)' }}>
                  Preis
                </dt>
                <dd className="flex flex-wrap items-center gap-2">
                  <span className="text-lg font-bold" style={{ color: '#FDE68A' }}>
                    {formatPrice(listing.price_numeric, listing.price)}
                  </span>
                  <PriceIndicatorBadge indicator={listing.price_indicator} median={listing.price_indicator_median} count={listing.price_indicator_count} />
                </dd>
              </div>

              <Field label="Zustand" value={listing.condition} />
              <Field label="Versand" value={listing.shipping} />

              {/* Location with Maps link */}
              <div
                className="p-3 rounded-xl"
                style={{ background: 'rgba(255,255,255,0.03)' }}
              >
                <dt className="text-xs font-medium uppercase tracking-wide mb-0.5" style={{ color: 'rgba(248,250,252,0.35)' }}>
                  Ort
                </dt>
                <dd className="mt-0.5 flex items-center gap-2">
                  <span className="text-sm font-medium" style={{ color: '#F8FAFC' }}>{location}</span>
                  {location !== '–' && (
                    <a
                      href={mapsHref}
                      target="_blank"
                      rel="noopener noreferrer"
                      title="Route in Google Maps"
                      className="transition-colors"
                      style={{ color: '#6366F1' }}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = '#818CF8'; }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = '#6366F1'; }}
                    >
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                        <circle cx="12" cy="11" r="3" />
                      </svg>
                    </a>
                  )}
                </dd>
              </div>

              {/* Distance — only when reference location is set */}
              {distanceKm != null && (
                <div
                  className="p-3 rounded-xl"
                  style={{ background: 'rgba(255,255,255,0.03)' }}
                >
                  <dt className="text-xs font-medium uppercase tracking-wide mb-0.5" style={{ color: 'rgba(248,250,252,0.35)' }}>
                    Entfernung
                  </dt>
                  <dd className="mt-0.5 text-sm font-semibold" style={{ color: '#A78BFA' }}>
                    {distanceKm.toFixed(1)} km{refCity ? ` von ${refCity}` : ''}
                  </dd>
                </div>
              )}
            </dl>

            {/* Column 2: hero image — order-first keeps it at the top on mobile */}
            <div className="lg:col-span-6 order-first lg:order-none">
              {listing.images.length > 0 ? (() => {
                const src = listing.images[0];
                const abs = src.startsWith('/') ? `https://www.rc-network.de${src}` : src;
                return (
                  <a href={abs} target="_blank" rel="noopener noreferrer" className="block">
                    <img
                      src={abs}
                      alt={listing.title}
                      className="w-full h-full rounded-2xl object-cover"
                      style={{ maxHeight: '360px', minHeight: '220px', border: '1px solid rgba(255,255,255,0.08)' }}
                    />
                  </a>
                );
              })() : listing.is_sold ? (
                <div
                  className="w-full rounded-2xl flex items-center justify-center"
                  style={{
                    height: '200px',
                    background: 'rgba(15, 15, 35, 0.6)',
                    border: '1px solid rgba(255, 255, 255, 0.08)',
                  }}
                >
                  <div className="flex flex-col items-center gap-2">
                    <svg className="w-10 h-10" style={{ color: 'rgba(248,250,252,0.12)' }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
                      <rect x="3" y="3" width="18" height="18" rx="2" />
                      <circle cx="8.5" cy="8.5" r="1.5" />
                      <path d="M21 15l-5-5L5 21" />
                    </svg>
                    <span className="text-xs font-medium" style={{ color: 'rgba(248,250,252,0.25)' }}>Bild nicht mehr verfügbar</span>
                  </div>
                </div>
              ) : null}
            </div>

            {/* Column 3: secondary metadata */}
            <dl className="lg:col-span-3 flex flex-col gap-3">
              {/* Original link */}
              <div
                className="p-3 rounded-xl"
                style={{ background: 'rgba(255,255,255,0.03)' }}
              >
                <dt className="text-xs font-medium uppercase tracking-wide mb-0.5" style={{ color: 'rgba(248,250,252,0.35)' }}>
                  Original
                </dt>
                <dd className="mt-0.5">
                  <a
                    href={listing.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm transition-colors"
                    style={{ color: '#6366F1' }}
                    onMouseEnter={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = '#818CF8'; }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = '#6366F1'; }}
                  >
                    rc-network.de →
                  </a>
                </dd>
              </div>

              <Field label="Inserent" value={listing.author} />
              <Field label="Datum" value={formatDate(listing.posted_at)} />

              {/* LLM-extracted product fields — only rendered when present */}
              {listing.manufacturer && <Field label="Hersteller" value={listing.manufacturer} />}
              {listing.model_name && <Field label="Modell" value={listing.model_name} />}
              {listing.model_type && <Field label="Typ" value={listing.model_type} />}
              {listing.drive_type && <Field label="Antrieb" value={listing.drive_type} />}
              {listing.completeness && <Field label="Vollständigkeit" value={listing.completeness} />}

              {/* Dynamic attributes from LLM extraction */}
              {Object.entries(listing.attributes).map(([key, val]) => (
                <Field key={key} label={humanizeAttributeKey(key)} value={val} />
              ))}
            </dl>
          </div>

          {/* Image gallery — remaining images after hero */}
          {listing.images.length > 1 && (
            <div className="mb-6">
              <h2
                className="text-xs font-semibold uppercase tracking-wider mb-3"
                style={{ color: 'rgba(248,250,252,0.35)' }}
              >
                Bilder
              </h2>
              <div className="flex overflow-x-auto flex-nowrap sm:flex-wrap gap-2 pb-1">
                {listing.images.slice(1).map((src, i) => {
                  const abs = src.startsWith('/') ? `https://www.rc-network.de${src}` : src;
                  return (
                    <a key={i} href={abs} target="_blank" rel="noopener noreferrer" className="flex-shrink-0">
                      <img
                        src={abs}
                        alt={`Bild ${i + 2}`}
                        className="h-28 w-auto rounded-xl object-cover hover:opacity-90 transition-opacity"
                        style={{ border: '1px solid rgba(255,255,255,0.1)' }}
                        loading="lazy"
                      />
                    </a>
                  );
                })}
              </div>
            </div>
          )}

          {/* Description */}
          {listing.description && (
            <div className="mb-6">
              <h2
                className="text-xs font-semibold uppercase tracking-wider mb-3"
                style={{ color: 'rgba(248,250,252,0.35)' }}
              >
                Beschreibung
              </h2>
              <div
                className="text-sm whitespace-pre-line leading-relaxed"
                style={{ color: 'rgba(248,250,252,0.65)' }}
              >
                {listing.description}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Author listings — split into aktuell and vergangen */}
      {authorListings.length > 0 && (() => {
        const aktuell = authorListings.filter((l) => !l.is_sold);
        const vergangen = authorListings.filter((l) => l.is_sold);
        return (
          <>
            {aktuell.length > 0 && (
              <AuthorListingsSection
                heading={`Weitere aktuelle Inserate von ${listing.author}`}
                items={aktuell}
              />
            )}
            {vergangen.length > 0 && (
              <AuthorListingsSection
                heading={`Vergangene Inserate von ${listing.author}`}
                items={vergangen}
              />
            )}
          </>
        );
      })()}
    </div>
  );
}
