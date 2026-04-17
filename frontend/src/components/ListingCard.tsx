import { useState, useRef } from 'react';
import { Link, useLocation } from 'react-router-dom';
import type { ListingSummary } from '../types/api';
import { getBackground } from '../lib/modalLocation';
import { toggleFavorite } from '../api/client';
import { formatPrice, formatDate } from '../utils/format';
import ComparablesModal from './ComparablesModal';

// Pin icon matching the mockup SVG
function PinIcon() {
  return (
    <svg
      className="w-3 h-3 shrink-0"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden="true"
    >
      <path d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
      <circle cx="12" cy="11" r="3" />
    </svg>
  );
}

interface PriceIndicatorBadgeProps {
  indicator: ListingSummary['price_indicator'];
  median?: number | null;
  count?: number | null;
  onClick?: (e: React.MouseEvent) => void;
  badgeRef?: React.RefObject<HTMLSpanElement | null>;
}

function PriceIndicatorBadge({ indicator, onClick, badgeRef }: PriceIndicatorBadgeProps) {
  if (indicator === 'deal') {
    return (
      <span
        ref={badgeRef}
        className="relative z-10 text-xs font-semibold px-2 py-0.5 rounded-full cursor-pointer"
        style={{ background: 'rgba(52,211,153,0.15)', color: '#34D399', border: '1px solid rgba(52,211,153,0.3)' }}
        onClick={onClick}
      >
        Günstig
      </span>
    );
  }
  if (indicator === 'fair') {
    return (
      <span
        ref={badgeRef}
        className="relative z-10 text-xs font-semibold px-2 py-0.5 rounded-full cursor-pointer"
        style={{ background: 'rgba(167,139,250,0.15)', color: '#A78BFA', border: '1px solid rgba(167,139,250,0.3)' }}
        onClick={onClick}
      >
        Gut
      </span>
    );
  }
  if (indicator === 'expensive') {
    return (
      <span
        ref={badgeRef}
        className="relative z-10 text-xs font-semibold px-2 py-0.5 rounded-full cursor-pointer"
        style={{ background: 'rgba(251,146,60,0.15)', color: '#FB923C', border: '1px solid rgba(251,146,60,0.3)' }}
        onClick={onClick}
      >
        Teuer
      </span>
    );
  }
  return null;
}

interface Props {
  listing: ListingSummary;
  onFavoriteChange?: (id: number, isFavorite: boolean) => void;
}

function isToday(dateStr: string | null): boolean {
  if (!dateStr) return false;
  const today = new Date();
  const d = new Date(dateStr);
  return (
    d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate()
  );
}

export default function ListingCard({ listing, onFavoriteChange }: Props) {
  const routerLocation = useLocation();
  const background = getBackground(routerLocation) ?? routerLocation;
  const location = listing.city ?? listing.plz ?? null;
  const hasDistance = listing.distance_km != null;
  const isNew = isToday(listing.posted_at);

  const [favorite, setFavorite] = useState(listing.is_favorite);
  const [favoriteLoading, setFavoriteLoading] = useState(false);
  const [comparablesOpen, setComparablesOpen] = useState(false);
  const badgeRef = useRef<HTMLSpanElement>(null);

  async function handleFavorite(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (favoriteLoading) return;
    const next = !favorite;
    setFavorite(next); // optimistic update
    setFavoriteLoading(true);
    try {
      await toggleFavorite(listing.id, next);
      onFavoriteChange?.(listing.id, next);
    } catch {
      setFavorite(!next); // revert on error
    } finally {
      setFavoriteLoading(false);
    }
  }

  return (
    <article
      className={`rounded-card card-transition overflow-hidden relative${listing.is_sold ? ' opacity-60' : ''}`}
      style={{
        background: 'rgba(15, 15, 35, 0.6)',
        border: '1px solid rgba(255, 255, 255, 0.08)',
        boxShadow: '0 0 60px rgba(99,102,241,0.06), 0 4px 16px rgba(0,0,0,0.2)',
      }}
    >
      {/* 16:9 image area */}
      <div className="aspect-[16/9] overflow-hidden relative" style={{ background: 'rgba(255,255,255,0.04)' }}>
        {listing.is_sold && (
          <div
            className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none"
            style={{ background: 'rgba(0, 0, 0, 0.45)' }}
          >
            <span className="bg-aurora-pink/80 text-white text-xs font-bold px-3 py-1 rounded-full rotate-[-8deg] shadow">
              VERKAUFT
            </span>
          </div>
        )}
        {isNew && !listing.is_sold && (
          <span
            className="absolute top-2 left-2 z-10 text-xs font-bold px-2 py-0.5 rounded-full shadow pointer-events-none"
            style={{ background: '#34D399', color: '#0f0f23' }}
          >
            NEU
          </span>
        )}
        {listing.is_sold && listing.images.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center" style={{ background: 'rgba(15, 15, 35, 0.8)' }}>
            <svg className="w-12 h-12" style={{ color: 'rgba(248,250,252,0.12)' }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <circle cx="8.5" cy="8.5" r="1.5" />
              <path d="M21 15l-5-5L5 21" />
            </svg>
          </div>
        )}
        {listing.images.length > 0 && (
          <img
            src={listing.images[0].startsWith('/') ? `https://www.rc-network.de${listing.images[0]}` : listing.images[0]}
            alt={listing.title}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        )}

        {/* Star button — z-20 to sit above the stretched link overlay */}
        <button
          onClick={handleFavorite}
          aria-label={favorite ? 'Von Merkliste entfernen' : 'Merken'}
          className="absolute top-2 right-2 z-20 p-1.5 rounded-full backdrop-blur-sm shadow transition"
          style={{ background: 'rgba(15, 15, 35, 0.7)', border: '1px solid rgba(255,255,255,0.12)' }}
        >
          <svg
            className="w-4 h-4 transition-colors"
            style={{ color: favorite ? '#FDE68A' : 'rgba(248,250,252,0.35)' }}
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
            fill={favorite ? 'currentColor' : 'none'}
            aria-hidden="true"
          >
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
          </svg>
        </button>
      </div>

      <div className="p-4 flex flex-col gap-0">
        {/* Title — stretched link covers the whole card */}
        <Link
          to={`/listings/${listing.id}`}
          state={{ background }}
          className="font-semibold text-sm leading-snug mb-2 line-clamp-2 transition-colors after:absolute after:inset-0"
          style={{ color: '#F8FAFC' }}
        >
          {listing.title}
        </Link>

        {/* Price + condition row */}
        <div className="flex items-center justify-between mb-3">
          <span
            data-testid="price"
            className="text-lg sm:text-xl font-bold"
            style={{ color: '#FDE68A' }}
          >
            {formatPrice(listing.price_numeric, listing.price)}
          </span>
          <div className="flex items-center gap-2">
            <PriceIndicatorBadge
              indicator={listing.price_indicator}
              median={listing.price_indicator_median}
              count={listing.price_indicator_count}
              badgeRef={badgeRef}
              onClick={(e) => {
                e.stopPropagation();
                e.preventDefault();
                setComparablesOpen(true);
              }}
            />
            <span
              data-testid="condition"
              className="text-xs font-medium px-2 py-0.5 rounded-full"
              style={{ color: 'rgba(248,250,252,0.5)', background: 'rgba(255,255,255,0.07)' }}
            >
              {listing.condition ?? '–'}
            </span>
          </div>
        </div>

        {/* Location + distance + date row */}
        <div
          className="flex flex-wrap items-center gap-3 text-xs pt-2.5"
          style={{ borderTop: '1px solid rgba(255,255,255,0.06)', color: 'rgba(248,250,252,0.65)' }}
        >
          {/* Location with pin icon */}
          <span
            data-testid="location"
            className="flex items-center gap-1"
          >
            <PinIcon />
            {location ?? '–'}
          </span>

          {/* Distance — indigo accent when present, muted dash when null */}
          {hasDistance ? (
            <span
              data-testid="distance"
              className="flex items-center gap-1 font-semibold"
              style={{ color: '#6366F1' }}
            >
              {listing.distance_km!.toFixed(1)} km
            </span>
          ) : (
            <span
              data-testid="distance"
              style={{ color: 'rgba(248,250,252,0.2)' }}
            >
              –
            </span>
          )}

          {/* Date pushed to the right */}
          <span className="ml-auto" style={{ color: 'rgba(248,250,252,0.35)' }}>
            {formatDate(listing.posted_at)}
          </span>
        </div>

      </div>

      {comparablesOpen && (
        <ComparablesModal
          listingId={listing.id}
          currentListingId={listing.id}
          anchorRef={badgeRef}
          onClose={() => setComparablesOpen(false)}
        />
      )}
    </article>
  );
}
