import { Link } from 'react-router-dom';
import type { ListingSummary } from '../types/api';

function formatDate(iso: string | null): string {
  if (!iso) return '–';
  return new Date(iso).toLocaleDateString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });
}

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
}

export default function ListingCard({ listing }: Props) {
  const location = listing.city ?? listing.plz ?? null;
  const hasDistance = listing.distance_km != null;

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
        {listing.images.length > 0 && (
          <img
            src={listing.images[0].startsWith('/') ? `https://www.rc-network.de${listing.images[0]}` : listing.images[0]}
            alt={listing.title}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        )}
      </div>

      <div className="p-4 flex flex-col gap-0">
        {/* Title — stretched link covers the whole card */}
        <Link
          to={`/listings/${listing.id}`}
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
            {listing.price ?? '–'}
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

        {/* Author footer */}
        <div className="text-xs text-gray-400 flex items-center mt-2 pt-1 border-t border-gray-100">
          <span data-testid="author">{listing.author}</span>
        </div>
      </div>
    </article>
  );
}
