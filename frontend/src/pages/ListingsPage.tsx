import ListingCard from '../components/ListingCard';
import FilterPanel from '../components/FilterPanel';
import Pagination from '../components/Pagination';
import { useListings } from '../hooks/useListings';

function Spinner() {
  return (
    <div className="flex justify-center py-12">
      <div className="animate-spin h-8 w-8 border-4 border-brand border-t-transparent rounded-full" />
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
        <div className="rounded-md bg-red-50 border border-red-200 p-4 text-red-700">
          Fehler beim Laden: {error}
        </div>
      )}

      {!loading && !error && data && (
        <>
          <p className="text-sm text-gray-500 mb-4">
            <span className="font-semibold text-gray-700">{data.total}</span>{' '}
            Anzeigen gefunden
          </p>
          {data.items.length === 0 ? (
            <div className="text-center py-12 text-gray-500">Keine Anzeigen gefunden.</div>
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
