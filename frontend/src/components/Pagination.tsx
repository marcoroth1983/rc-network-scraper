import type { CSSProperties } from 'react';

interface Props {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

export default function Pagination({ page, totalPages, onPageChange }: Props) {
  if (totalPages <= 1) return null;

  const btnBase: CSSProperties = {
    background: 'rgba(255, 255, 255, 0.05)',
    border: '1px solid rgba(255, 255, 255, 0.1)',
    color: '#F8FAFC',
  };

  return (
    <div className="flex items-center justify-center gap-3 mt-8">
      <button
        onClick={() => onPageChange(page - 1)}
        disabled={page <= 1}
        className="px-3 py-2.5 sm:px-4 sm:py-2 rounded-md text-sm font-medium transition disabled:opacity-40 disabled:cursor-not-allowed"
        style={btnBase}
      >
        ← Zurück
      </button>

      <span className="text-sm" style={{ color: 'rgba(248, 250, 252, 0.65)' }}>
        Seite{' '}
        <span className="font-semibold" style={{ color: '#6366F1' }}>{page}</span>
        {' '}von{' '}
        <span className="font-semibold" style={{ color: '#F8FAFC' }}>{totalPages}</span>
      </span>

      <button
        onClick={() => onPageChange(page + 1)}
        disabled={page >= totalPages}
        className="px-3 py-2.5 sm:px-4 sm:py-2 rounded-md text-sm font-medium transition disabled:opacity-40 disabled:cursor-not-allowed"
        style={btnBase}
      >
        Weiter →
      </button>
    </div>
  );
}
