import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import type { ListingSummary } from '../types/api';
import { toggleFavorite } from '../api/client';
import { formatPrice, formatDate } from '../utils/format';

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
  const location = listing.city ?? listing.plz ?? null;
  const hasDistance = listing.distance_km != null;
  const isNew = isToday(listing.posted_at);

  const [favorite, setFavorite] = useState(listing.is_favorite);
  const [favoriteLoading, setFavoriteLoading] = useState(false);

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
    <article className={`bg-white rounded-card shadow-card card-transition overflow-hidden relative${listing.is_sold ? ' opacity-60' : ''}`}>
      {/* 16:9 image area */}
      <div className="aspect-[16/9] bg-gray-100 overflow-hidden relative">
        {listing.is_sold && (
          <div className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
            <span className="bg-red-600 text-white text-xs font-bold px-3 py-1 rounded-full rotate-[-8deg] shadow">
              VERKAUFT
            </span>
          </div>
        )}
        {isNew && !listing.is_sold && (
          <span className="absolute top-2 left-2 z-10 bg-green-500 text-white text-xs font-bold px-2 py-0.5 rounded-full shadow pointer-events-none">
            NEU
          </span>
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
          className="absolute top-2 right-2 z-20 p-1.5 rounded-full bg-white/80 backdrop-blur-sm shadow hover:bg-white transition"
        >
          <svg
            className={`w-4 h-4 transition-colors ${favorite ? 'text-yellow-400' : 'text-gray-400'}`}
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
          state={{ from: routerLocation.search }}
          className="font-semibold text-gray-900 text-sm leading-snug mb-2 line-clamp-2 hover:text-brand transition-colors after:absolute after:inset-0"
        >
          {listing.title}
        </Link>

        {/* Price + condition row */}
        <div className="flex items-center justify-between mb-3">
          <span
            data-testid="price"
            className="text-xl font-bold text-gray-900"
          >
            {formatPrice(listing.price_numeric, listing.price)}
          </span>
          <span
            data-testid="condition"
            className="text-xs font-medium text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full"
          >
            {listing.condition ?? '–'}
          </span>
        </div>

        {/* Location + distance + date row */}
        <div className="flex items-center gap-3 text-xs text-gray-500 border-t border-gray-50 pt-2.5">
          {/* Location with pin icon */}
          <span
            data-testid="location"
            className="flex items-center gap-1"
          >
            <PinIcon />
            {location ?? '–'}
          </span>

          {/* Distance — brand blue when present, muted dash when null */}
          {hasDistance ? (
            <span
              data-testid="distance"
              className="flex items-center gap-1 font-semibold text-brand"
            >
              {listing.distance_km!.toFixed(1)} km
            </span>
          ) : (
            <span
              data-testid="distance"
              className="text-gray-300 text-xs"
            >
              –
            </span>
          )}

          {/* Date pushed to the right */}
          <span className="ml-auto text-gray-400">
            {formatDate(listing.posted_at)}
          </span>
        </div>

      </div>
    </article>
  );
}
