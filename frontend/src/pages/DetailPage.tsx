import { useEffect, useState, useRef } from 'react';
import { useParams, useLocation, Link } from 'react-router-dom';
import { getListing, toggleSold, toggleFavorite } from '../api/client';
import type { ListingDetail } from '../types/api';
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
  const routerLocation = useLocation();
  // Freeze backTo at mount time — PlzBar later calls setSearchParams on the detail page URL,
  // which pushes a new history entry without router state, losing state.from on re-renders.
  const backTo = useRef('/' + ((routerLocation.state as { from?: string } | null)?.from ?? '')).current;
  const [listing, setListing] = useState<ListingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [soldPending, setSoldPending] = useState(false);
  const [favoritePending, setFavoritePending] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(null);
    getListing(Number(id))
      .then((data) => {
        setListing(data);
        setLoading(false);
      })
      .catch((err: Error) => {
        setError(err.message);
        setLoading(false);
      });
  }, [id]);

  if (loading) return <Spinner />;

  if (error) {
    return (
      <div className="max-w-2xl mx-auto">
        <Link
          to={backTo}
          className="text-sm mb-4 inline-block transition-colors"
          style={{ color: '#A78BFA' }}
        >
          ← Zurück zur Liste
        </Link>
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

  return (
    <div className="max-w-2xl mx-auto">
      {/* Back button */}
      <Link
        to={backTo}
        className="text-sm mb-4 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl transition-all duration-200"
        style={{
          color: '#A78BFA',
          background: 'rgba(167,139,250,0.08)',
          border: '1px solid rgba(167,139,250,0.2)',
        }}
      >
        ← Zurück zur Liste
      </Link>

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

              {/* Sold toggle */}
              <button
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
              </button>
            </div>
          </div>

          {/* Metadata grid */}
          <dl className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-6 pb-6" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            {/* Price — highlighted yellow, spans full width on small */}
            <div
              className="col-span-2 md:col-span-1 p-3 rounded-xl"
              style={{ background: 'rgba(253,230,138,0.06)', border: '1px solid rgba(253,230,138,0.12)' }}
            >
              <dt className="text-xs font-medium uppercase tracking-wide mb-0.5" style={{ color: 'rgba(248,250,252,0.35)' }}>
                Preis
              </dt>
              <dd className="text-lg font-bold" style={{ color: '#FDE68A' }}>
                {formatPrice(listing.price_numeric, listing.price)}
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

          {/* Image gallery */}
          {listing.images.length > 0 && (
            <div className="mb-6">
              <h2
                className="text-xs font-semibold uppercase tracking-wider mb-3"
                style={{ color: 'rgba(248,250,252,0.35)' }}
              >
                Bilder
              </h2>
              <div className="flex overflow-x-auto flex-nowrap sm:flex-wrap gap-2">
                {listing.images.map((src, i) => {
                  const abs = src.startsWith('/') ? `https://www.rc-network.de${src}` : src;
                  return (
                    <a key={i} href={abs} target="_blank" rel="noopener noreferrer">
                      <img
                        src={abs}
                        alt={`Bild ${i + 1}`}
                        className="h-32 w-auto rounded-xl object-cover hover:opacity-90 transition-opacity"
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
    </div>
  );
}
