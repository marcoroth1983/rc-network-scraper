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

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</dt>
      <dd className="mt-0.5 text-sm text-gray-900">{value ?? '–'}</dd>
    </div>
  );
}

function Spinner() {
  return (
    <div className="flex justify-center py-16">
      <div className="animate-spin h-8 w-8 border-4 border-brand border-t-transparent rounded-full" />
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
      <div>
        <Link to={backTo} className="text-brand hover:underline text-sm mb-4 inline-block">
          ← Zurück zur Liste
        </Link>
        <div className="rounded-md bg-red-50 border border-red-200 p-4 text-red-700">
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
      <Link to={backTo} className="text-brand hover:underline text-sm mb-4 inline-block">
        ← Zurück zur Liste
      </Link>

      <div className="bg-white rounded-card shadow-card overflow-hidden">
        <div className="p-6">
          <div className="flex items-start justify-between gap-3 mb-4">
            <h1 className="text-2xl font-bold text-gray-900 leading-tight">
              {listing.title}
            </h1>
            <div className="flex items-center gap-2 shrink-0">
              {/* Favorite star */}
              <button
                onClick={handleToggleFavorite}
                disabled={favoritePending}
                aria-label={listing.is_favorite ? 'Von Merkliste entfernen' : 'Merken'}
                className="p-1.5 rounded-full bg-gray-100 hover:bg-gray-200 transition disabled:opacity-50"
              >
                <svg
                  className={`w-5 h-5 transition-colors ${listing.is_favorite ? 'text-yellow-400' : 'text-gray-400'}`}
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                  fill={listing.is_favorite ? 'currentColor' : 'none'}
                  aria-hidden="true"
                >
                  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                </svg>
              </button>
              {/* Sold toggle */}
              <button
                onClick={handleToggleSold}
                disabled={soldPending}
                className={`text-xs font-semibold px-3 py-1.5 rounded-full border transition-colors ${
                  listing.is_sold
                    ? 'bg-red-100 text-red-700 border-red-300 hover:bg-red-200'
                    : 'bg-gray-100 text-gray-600 border-gray-300 hover:bg-gray-200'
                } disabled:opacity-50`}
              >
                {listing.is_sold ? 'Verkauft ✓' : 'Als verkauft markieren'}
              </button>
            </div>
          </div>

          <dl className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-6 pb-6 border-b border-gray-100">
            <Field label="Preis" value={formatPrice(listing.price_numeric, listing.price)} />
            <Field label="Zustand" value={listing.condition} />
            <Field label="Versand" value={listing.shipping} />
            <div>
              <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">Ort</dt>
              <dd className="mt-0.5 flex items-center gap-2">
                <span className="text-sm text-gray-900">{location}</span>
                {location !== '–' && (
                  <a
                    href={mapsHref}
                    target="_blank"
                    rel="noopener noreferrer"
                    title="Route in Google Maps"
                    className="text-brand hover:text-brand-dark"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                      <circle cx="12" cy="11" r="3" />
                    </svg>
                  </a>
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">Original</dt>
              <dd className="mt-0.5">
                <a
                  href={listing.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-brand hover:underline"
                >
                  rc-network.de →
                </a>
              </dd>
            </div>
            <Field label="Inserent" value={listing.author} />
            <Field label="Datum" value={formatDate(listing.posted_at)} />
            {distanceKm != null && (
              <div>
                <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">Entfernung</dt>
                <dd className="mt-0.5 text-sm font-semibold text-brand">
                  {distanceKm.toFixed(1)} km{refCity ? ` von ${refCity}` : ''}
                </dd>
              </div>
            )}
          </dl>

          {listing.images.length > 0 && (
            <div className="mb-6">
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                Bilder
              </h2>
              <div className="flex flex-wrap gap-2">
                {listing.images.map((src, i) => {
                  const abs = src.startsWith('/') ? `https://www.rc-network.de${src}` : src;
                  return (
                  <a key={i} href={abs} target="_blank" rel="noopener noreferrer">
                    <img
                      src={abs}
                      alt={`Bild ${i + 1}`}
                      className="h-32 w-auto rounded border border-gray-200 object-cover hover:opacity-90 transition-opacity"
                      loading="lazy"
                    />
                  </a>
                  );
                })}
              </div>
            </div>
          )}

          {listing.description && (
            <div className="mb-6">
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                Beschreibung
              </h2>
              <div className="text-sm text-gray-700 whitespace-pre-line leading-relaxed">
                {listing.description}
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
