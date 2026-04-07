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
    <article className={`flex gap-4 p-4 bg-white rounded-xl border border-gray-100 shadow-sm relative${listing.is_sold ? ' opacity-70' : ''}`}>
      {/* Thumbnail */}
      <div className="relative shrink-0 w-24 h-20 rounded-lg overflow-hidden bg-gray-100">
        {listing.images.length > 0 ? (
          <img
            src={listing.images[0].startsWith('/') ? `https://www.rc-network.de${listing.images[0]}` : listing.images[0]}
            alt={listing.title}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full bg-gray-200" />
        )}
        {listing.images.length > 1 && (
          <span className="absolute bottom-1 right-1 bg-black/60 text-white text-[10px] px-1 rounded">
            {listing.images.length}
          </span>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between text-xs text-gray-400 mb-1">
          <span>{location || '–'}</span>
          <span>{formatDate(listing.posted_at)}</span>
        </div>

        <Link
          to={`/listings/${listing.id}`}
          className="block text-sm font-semibold text-gray-900 leading-snug line-clamp-2 hover:text-brand transition-colors mb-1.5 after:absolute after:inset-0"
        >
          {listing.title}
        </Link>

        {listing.condition && (
          <p className="text-xs text-gray-500 line-clamp-1">{listing.condition}</p>
        )}

        <div className="flex items-center gap-2 mt-1.5">
          <span className="text-base font-bold text-gray-900">{formatPrice(listing.price_numeric, listing.price)}</span>
          {listing.is_sold && (
            <span className="bg-red-600 text-white text-[10px] font-bold px-2 py-0.5 rounded-full">
              VERKAUFT
            </span>
          )}
        </div>
      </div>

      {/* Remove button — z-20 to reliably sit above the stretched link overlay (after:inset-0) */}
      <button
        onClick={handleRemove}
        aria-label="Von Merkliste entfernen"
        className="relative z-20 shrink-0 self-center flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-gray-200 text-xs text-gray-500 hover:border-red-300 hover:text-red-500 transition"
      >
        <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <polyline points="3 6 5 6 21 6" />
          <path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" />
          <path d="M10 11v6M14 11v6M9 6V4h6v2" />
        </svg>
        Von Merkliste entfernen
      </button>
    </article>
  );
}
