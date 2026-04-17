import { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { getListing, toggleSold, toggleFavorite, getListingsByAuthor } from '../api/client';
import { useAuth } from '../hooks/useAuth';
import ListingCard from '../components/ListingCard';
import { useConfirm } from '../components/ConfirmDialog';
import ComparablesModal from '../components/ComparablesModal';
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

interface PriceIndicatorBadgeProps {
  indicator: PriceIndicator;
  median?: number | null;
  count?: number | null;
  onClick?: () => void;
  badgeRef?: React.RefObject<HTMLButtonElement | null>;
}

// <button> for reliable touch dispatch on iOS Safari; touchAction:manipulation
// removes the 300ms tap delay. See ListingCard.tsx for the same rationale.
const BADGE_CLASSES = "relative z-10 text-xs font-semibold px-2 py-0.5 rounded-full cursor-pointer";
const BADGE_TOUCH_STYLE: React.CSSProperties = { touchAction: 'manipulation' };

function PriceIndicatorBadge({ indicator, onClick, badgeRef }: PriceIndicatorBadgeProps) {
  if (indicator === 'deal') {
    return (
      <button
        type="button"
        ref={badgeRef}
        className={BADGE_CLASSES}
        style={{ ...BADGE_TOUCH_STYLE, background: 'rgba(52,211,153,0.15)', color: '#34D399', border: '1px solid rgba(52,211,153,0.3)' }}
        onClick={onClick}
      >
        Günstig
      </button>
    );
  }
  if (indicator === 'fair') {
    return (
      <button
        type="button"
        ref={badgeRef}
        className={BADGE_CLASSES}
        style={{ ...BADGE_TOUCH_STYLE, background: 'rgba(167,139,250,0.15)', color: '#A78BFA', border: '1px solid rgba(167,139,250,0.3)' }}
        onClick={onClick}
      >
        Gut
      </button>
    );
  }
  if (indicator === 'expensive') {
    return (
      <button
        type="button"
        ref={badgeRef}
        className={BADGE_CLASSES}
        style={{ ...BADGE_TOUCH_STYLE, background: 'rgba(251,146,60,0.15)', color: '#FB923C', border: '1px solid rgba(251,146,60,0.3)' }}
        onClick={onClick}
      >
        Teuer
      </button>
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

interface MetaRowProps {
  label: string;
  children: React.ReactNode;
}

function MetaRow({ label, children }: MetaRowProps) {
  return (
    <div className="flex items-start gap-2 py-1.5" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
      <span className="text-xs font-medium shrink-0 w-20" style={{ color: 'rgba(248,250,252,0.35)', paddingTop: '1px' }}>
        {label}
      </span>
      <span className="text-sm font-medium flex-1" style={{ color: '#F8FAFC' }}>
        {children}
      </span>
    </div>
  );
}

interface ModelDetailsProps {
  listing: ListingDetail;
}

function ModelDetails({ listing }: ModelDetailsProps) {
  const [expanded, setExpanded] = useState(false);

  // Build list of all model detail fields that have values
  const allFields: { label: string; value: string }[] = [];
  if (listing.manufacturer) allFields.push({ label: 'Hersteller', value: listing.manufacturer });
  if (listing.model_name) allFields.push({ label: 'Modell', value: listing.model_name });
  if (listing.model_type) allFields.push({ label: 'Typ', value: listing.model_type });
  if (listing.model_subtype) allFields.push({ label: 'Subtyp', value: listing.model_subtype });
  if (listing.drive_type) allFields.push({ label: 'Antrieb', value: listing.drive_type });
  if (listing.completeness) allFields.push({ label: 'Vollst.', value: listing.completeness });
  Object.entries(listing.attributes).forEach(([key, val]) => {
    allFields.push({ label: humanizeAttributeKey(key), value: val });
  });

  if (allFields.length === 0) return null;

  const VISIBLE = 3;
  const visibleFields = allFields.slice(0, VISIBLE);
  const hiddenFields = allFields.slice(VISIBLE);
  const hasMore = hiddenFields.length > 0;

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)' }}
    >
      {/* Header */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 transition-colors duration-150"
        style={{ color: 'rgba(248,250,252,0.55)' }}
        onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.03)'; }}
        onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = ''; }}
        aria-expanded={expanded}
      >
        <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'rgba(248,250,252,0.35)' }}>
          Modelldetails
        </span>
        <svg
          className="w-4 h-4 transition-transform duration-200"
          style={{ transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)', color: 'rgba(248,250,252,0.3)' }}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Always-visible fields */}
      <div className="px-4 pb-1">
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6">
          {visibleFields.map(({ label, value }) => (
            <div key={label} className="flex items-start gap-2 py-1.5" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              <dt className="text-xs font-medium shrink-0 w-24" style={{ color: 'rgba(248,250,252,0.35)', paddingTop: '1px' }}>
                {label}
              </dt>
              <dd className="text-sm font-medium flex-1" style={{ color: '#F8FAFC' }}>{value}</dd>
            </div>
          ))}
        </dl>
      </div>

      {/* Expandable fields */}
      {hasMore && (
        <div
          className="overflow-hidden transition-all duration-300 ease-in-out"
          style={{ maxHeight: expanded ? `${hiddenFields.length * 60}px` : '0px' }}
        >
          <div className="px-4 pb-3">
            <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6">
              {hiddenFields.map(({ label, value }) => (
                <div key={label} className="flex items-start gap-2 py-1.5" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                  <dt className="text-xs font-medium shrink-0 w-24" style={{ color: 'rgba(248,250,252,0.35)', paddingTop: '1px' }}>
                    {label}
                  </dt>
                  <dd className="text-sm font-medium flex-1" style={{ color: '#F8FAFC' }}>{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      )}

      {/* Toggle button */}
      {hasMore && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="w-full px-4 py-2.5 text-xs font-semibold transition-colors duration-150 flex items-center justify-center gap-1"
          style={{
            color: '#A78BFA',
            borderTop: '1px solid rgba(255,255,255,0.06)',
            background: 'rgba(167,139,250,0.04)',
          }}
        >
          {expanded ? (
            <>
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 15l7-7 7 7" />
              </svg>
              Weniger anzeigen
            </>
          ) : (
            <>
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
              {hiddenFields.length} weitere Felder
            </>
          )}
        </button>
      )}
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
  const navigate = useNavigate();
  const routerLocation = useLocation();
  const locationState = routerLocation.state as { from?: string; isDirectHit?: boolean } | null;
  const isDirectHit = locationState?.isDirectHit === true;
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const confirm = useConfirm();
  const [listing, setListing] = useState<ListingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [soldPending, setSoldPending] = useState(false);
  const [favoritePending, setFavoritePending] = useState(false);
  const [authorListings, setAuthorListings] = useState<ListingSummary[]>([]);
  const [shareCopied, setShareCopied] = useState(false);
  const [comparablesOpen, setComparablesOpen] = useState(false);
  const badgeRef = useRef<HTMLButtonElement>(null);

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

  const heroImageSrc = listing.images.length > 0
    ? (listing.images[0].startsWith('/') ? `https://www.rc-network.de${listing.images[0]}` : listing.images[0])
    : null;

  async function handleToggleSold() {
    const next = !listing!.is_sold;
    if (next) {
      const ok = await confirm({
        title: 'Als verkauft markieren?',
        message: `„${listing!.title}" wird als verkauft gekennzeichnet.`,
        confirmLabel: 'Verkauft',
      });
      if (!ok) return;
    }
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
      }
    }
    try {
      await navigator.clipboard.writeText(url);
      setShareCopied(true);
      setTimeout(() => setShareCopied(false), 2000);
    } catch {
      // Clipboard unavailable
    }
  }

  return (
    <div className="w-full pt-3 pb-6 sm:pt-0 sm:pb-10">
      {/* Back button */}
      <div className="flex justify-end mb-3">
        <button
          onClick={() => isDirectHit ? navigate('/', { replace: true }) : navigate(-1)}
          className="flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded-full transition-all duration-200"
          style={{
            background: 'rgba(255,255,255,0.06)',
            border: '1px solid rgba(255,255,255,0.1)',
            color: 'rgba(248,250,252,0.6)',
          }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = '#F8FAFC'; (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(255,255,255,0.2)'; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = 'rgba(248,250,252,0.6)'; (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(255,255,255,0.1)'; }}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          Zurück
        </button>
      </div>

      {/* Main card */}
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

          {/* Title */}
          <h1 className="text-xl sm:text-2xl font-bold leading-tight mb-4" style={{ color: '#F8FAFC' }}>
            {listing.title}
          </h1>

          {/* Hero row: image left, meta right */}
          <div className="flex flex-col sm:flex-row gap-4 mb-5">

            {/* Image */}
            <div className="sm:w-2/5 shrink-0">
              {heroImageSrc ? (
                <a href={heroImageSrc} target="_blank" rel="noopener noreferrer" className="block">
                  <div className="relative overflow-hidden rounded-xl" style={{ aspectRatio: '4/3' }}>
                    <img
                      src={heroImageSrc}
                      alt={listing.title}
                      className="w-full h-full object-cover"
                      style={{ border: '1px solid rgba(255,255,255,0.08)' }}
                    />
                    {listing.is_sold && (
                      <div className="absolute inset-0 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.5)' }}>
                        <span className="text-white text-sm font-bold px-3 py-1 rounded-full" style={{ background: 'rgba(236,72,153,0.8)' }}>
                          VERKAUFT
                        </span>
                      </div>
                    )}
                  </div>
                </a>
              ) : (
                <div
                  className="w-full rounded-xl flex items-center justify-center"
                  style={{ aspectRatio: '4/3', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}
                >
                  <svg className="w-10 h-10" style={{ color: 'rgba(248,250,252,0.12)' }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
                    <rect x="3" y="3" width="18" height="18" rx="2" />
                    <circle cx="8.5" cy="8.5" r="1.5" />
                    <path d="M21 15l-5-5L5 21" />
                  </svg>
                </div>
              )}
            </div>

            {/* Meta column */}
            <div className="flex-1 flex flex-col gap-3 min-w-0">

              {/* Price + indicator + action buttons row */}
              <div className="flex items-start justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-2xl font-bold" style={{ color: '#FDE68A' }}>
                    {formatPrice(listing.price_numeric, listing.price)}
                  </span>
                  <PriceIndicatorBadge
                    indicator={listing.price_indicator}
                    median={listing.price_indicator_median}
                    count={listing.price_indicator_count}
                    badgeRef={badgeRef}
                    onClick={() => setComparablesOpen(true)}
                  />
                </div>

                {/* Action buttons */}
                <div className="flex items-center gap-2 shrink-0">
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
                      className="w-5 h-5"
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
                        <circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" />
                        <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
                        <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
                      </svg>
                    )}
                  </button>

                  {isAdmin && (
                    <button
                      onClick={handleToggleSold}
                      disabled={soldPending}
                      className="text-xs font-semibold px-3 py-1.5 rounded-full transition-all duration-200 disabled:opacity-50"
                      style={
                        listing.is_sold
                          ? { background: 'rgba(236,72,153,0.12)', border: '1px solid rgba(236,72,153,0.35)', color: '#EC4899' }
                          : { background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)', color: 'rgba(248,250,252,0.6)' }
                      }
                    >
                      {listing.is_sold ? 'Verkauft ✓' : 'Als verkauft'}
                    </button>
                  )}
                </div>
              </div>

              {/* Key meta rows */}
              <div className="flex flex-col">
                <MetaRow label="Zustand">{listing.condition ?? '–'}</MetaRow>
                <MetaRow label="Versand">{listing.shipping ?? '–'}</MetaRow>
                <MetaRow label="Ort">
                  <span className="flex items-center gap-2">
                    {location}
                    {location !== '–' && (
                      <a
                        href={mapsHref}
                        target="_blank"
                        rel="noopener noreferrer"
                        title="Route in Google Maps"
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
                  </span>
                </MetaRow>
                {distanceKm != null && (
                  <MetaRow label="Entfernung">
                    <span style={{ color: '#A78BFA', fontWeight: 600 }}>
                      {distanceKm.toFixed(1)} km{refCity ? ` von ${refCity}` : ''}
                    </span>
                  </MetaRow>
                )}
                <MetaRow label="Inserent">{listing.author}</MetaRow>
                <MetaRow label="Datum">{formatDate(listing.posted_at)}</MetaRow>
                <MetaRow label="Original">
                  <a
                    href={listing.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="transition-colors"
                    style={{ color: '#6366F1' }}
                    onMouseEnter={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = '#818CF8'; }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = '#6366F1'; }}
                  >
                    rc-network.de →
                  </a>
                </MetaRow>
              </div>
            </div>
          </div>

          {/* Collapsible model details */}
          <ModelDetails listing={listing} />

          {/* Tags */}
          {listing.tags.length > 0 && (
            <div className="mt-4">
              <div className="flex flex-wrap gap-1.5">
                {listing.tags.map((tag) => (
                  <span
                    key={tag}
                    className="text-xs px-2 py-0.5 rounded-full"
                    style={{ background: 'rgba(255,255,255,0.06)', color: 'rgba(248,250,252,0.55)', border: '1px solid rgba(255,255,255,0.08)' }}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Description */}
          {listing.description && (
            <div className="mt-5 pt-5" style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
              <h2 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: 'rgba(248,250,252,0.35)' }}>
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

          {/* Additional images gallery */}
          {listing.images.length > 1 && (
            <div className="mt-5 pt-5" style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
              <h2 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: 'rgba(248,250,252,0.35)' }}>
                Weitere Bilder
              </h2>
              <div className="flex overflow-x-auto flex-nowrap sm:flex-wrap gap-2 pb-1">
                {listing.images.slice(1).map((src, i) => {
                  const abs = src.startsWith('/') ? `https://www.rc-network.de${src}` : src;
                  return (
                    <a key={i} href={abs} target="_blank" rel="noopener noreferrer" className="flex-shrink-0">
                      <img
                        src={abs}
                        alt={`Bild ${i + 2}`}
                        className="h-24 w-auto rounded-xl object-cover hover:opacity-90 transition-opacity"
                        style={{ border: '1px solid rgba(255,255,255,0.1)' }}
                        loading="lazy"
                      />
                    </a>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Author listings */}
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

      {comparablesOpen && listing.price_indicator && (
        <ComparablesModal
          listingId={listing.id}
          currentListingId={listing.id}
          anchorRef={badgeRef}
          onClose={() => setComparablesOpen(false)}
        />
      )}
    </div>
  );
}
