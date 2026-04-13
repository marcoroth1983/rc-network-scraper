import { Link } from 'react-router-dom';
import type { ListingSummary } from '../types/api';
import { toggleFavorite } from '../api/client';
import { formatPrice, formatDate } from '../utils/format';

interface Props {
  listing: ListingSummary;
  onRemove: (id: number) => void;
}

export default function FavoriteCard({ listing, onRemove }: Props) {
  const location = [listing.plz, listing.city].filter(Boolean).join(' ');

  async function handleRemove(e: React.MouseEvent) {
    e.preventDefault();
    try {
      await toggleFavorite(listing.id, false);
      onRemove(listing.id);
    } catch {
      // API failed — do not remove from UI, user can retry
    }
  }

  return (
    <article
      className={`relative flex gap-3 py-3 transition-all duration-200${listing.is_sold ? ' opacity-60' : ''}`}
    >
      {/* Left column: fixed square thumbnail only */}
      <div className="relative shrink-0 w-20 h-20 rounded-xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.05)' }}>
        {listing.images.length > 0 ? (
          <img
            src={listing.images[0].startsWith('/') ? `https://www.rc-network.de${listing.images[0]}` : listing.images[0]}
            alt={listing.title}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full" style={{ background: 'rgba(255,255,255,0.04)' }} />
        )}

        {/* Image count badge — bottom-right corner */}
        {listing.images.length > 1 && (
          <span
            className="absolute bottom-1 right-1 text-[9px] font-semibold px-1 py-0.5 rounded"
            style={{ background: 'rgba(0,0,0,0.55)', color: 'rgba(248,250,252,0.75)' }}
          >
            {listing.images.length}
          </span>
        )}
      </div>

      {/* Right column: 3 rows */}
      <div className="flex-1 min-w-0 pl-3 flex flex-col justify-between">
        {/* Row 1: title — stretched link covers the whole article, pr-8 reserves space for trash button */}
        <Link
          to={`/listings/${listing.id}`}
          className="block text-sm font-semibold leading-snug line-clamp-2 pr-8 after:absolute after:inset-0 transition-colors"
          style={{ color: '#F8FAFC' }}
        >
          {listing.title}
        </Link>

        {/* Row 2: PLZ + city on left, date on right */}
        <div className="flex justify-between items-center mt-1">
          <span className="text-xs truncate" style={{ color: 'rgba(248,250,252,0.4)' }}>
            {location || '–'}
          </span>
          <span className="text-xs shrink-0 ml-2" style={{ color: 'rgba(248,250,252,0.35)' }}>
            {formatDate(listing.posted_at)}
          </span>
        </div>

        {/* Row 3: price / sold badge on left, distance (or condition fallback) on right */}
        <div className="flex justify-between items-center mt-1.5">
          <div className="flex items-center gap-1.5 min-w-0">
            {listing.is_sold ? (
              <span className="bg-red-600/80 text-white text-[10px] font-bold px-2 py-0.5 rounded-full">
                VERKAUFT
              </span>
            ) : (
              <span className="text-base font-bold" style={{ color: '#FDE68A' }}>
                {formatPrice(listing.price_numeric, listing.price)}
              </span>
            )}

            {/* Condition — shown only when there is no distance */}
            {listing.distance_km == null && listing.condition && (
              <span className="text-xs truncate" style={{ color: 'rgba(248,250,252,0.4)' }}>
                {listing.condition}
              </span>
            )}
          </div>

          {listing.distance_km != null && (
            <span className="text-xs shrink-0 ml-2" style={{ color: 'rgba(248,250,252,0.4)' }}>
              {Math.round(listing.distance_km)} km
            </span>
          )}
        </div>
      </div>

      {/* Trash button — absolute top-right, z-20 to sit above stretched link overlay */}
      <button
        onClick={handleRemove}
        aria-label="Von Merkliste entfernen"
        className="absolute top-3 right-0 z-20 flex items-center justify-center w-8 h-8 rounded-lg transition-all duration-200"
        style={{
          border: '1px solid rgba(255,255,255,0.1)',
          background: 'rgba(255,255,255,0.06)',
          color: 'rgba(248,250,252,0.4)',
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLButtonElement).style.color = '#ef4444';
          (e.currentTarget as HTMLButtonElement).style.background = 'rgba(239,68,68,0.12)';
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLButtonElement).style.color = 'rgba(248,250,252,0.4)';
          (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.06)';
        }}
      >
        <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <polyline points="3 6 5 6 21 6" />
          <path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" />
          <path d="M10 11v6M14 11v6M9 6V4h6v2" />
        </svg>
      </button>
    </article>
  );
}
