import ListingCard from '../components/ListingCard';
import FilterPanel from '../components/FilterPanel';
import Pagination from '../components/Pagination';
import { useListings } from '../hooks/useListings';

function Spinner() {
  return (
    <div className="flex justify-center py-12">
      <div
        className="animate-spin h-8 w-8 border-4 rounded-full"
        style={{ borderColor: '#A78BFA', borderTopColor: 'transparent' }}
      />
    </div>
  );
}

export default function ListingsPage() {
  const { data, loading, error, filter, setFilter } = useListings();

  return (
    <div>
      <FilterPanel filter={filter} onChange={setFilter} />

      {loading && <Spinner />}

      {!loading && error && (
        <div
          className="rounded-xl p-4"
          style={{
            background: 'rgba(236,72,153,0.08)',
            border: '1px solid rgba(236,72,153,0.3)',
            color: '#EC4899',
          }}
        >
          Fehler beim Laden: {error}
        </div>
      )}

      {!loading && !error && data && (
        <>
          <p className="text-sm mb-4" style={{ color: 'rgba(248,250,252,0.65)' }}>
            <span className="font-semibold" style={{ color: '#F8FAFC' }}>{data.total}</span>{' '}
            Anzeigen gefunden
          </p>
          {data.items.length === 0 ? (
            <div className="text-center py-16">
              {/* Subtle empty state icon */}
              <svg
                className="w-12 h-12 mx-auto mb-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1}
                style={{ color: 'rgba(248,250,252,0.15)' }}
              >
                <rect x="3" y="3" width="18" height="18" rx="3" />
                <path strokeLinecap="round" d="M9 9h6M9 12h6M9 15h4" />
              </svg>
              <p style={{ color: 'rgba(248,250,252,0.35)' }}>Keine Anzeigen gefunden.</p>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {data.items.map((listing) => (
                  <ListingCard key={listing.id} listing={listing} />
                ))}
              </div>
              <Pagination
                page={data.page}
                totalPages={Math.ceil(data.total / data.per_page)}
                onPageChange={(p) => setFilter({ ...filter, page: p })}
              />
            </>
          )}
        </>
      )}
    </div>
  );
}
