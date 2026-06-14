import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MiniChart } from '../MiniChart';
import type { TimeseriesPoint } from '../../types/api';

const series: TimeseriesPoint[] = [
  { day: '2026-06-01', value: 2 },
  { day: '2026-06-02', value: 0 },
  { day: '2026-06-03', value: 5 },
];

describe('MiniChart', () => {
  it('renders a line chart with an accessible summary label', () => {
    render(<MiniChart title="Logins" data={series} type="line" accent="#A78BFA" />);
    expect(screen.getByRole('img', { name: /Logins: 7 insgesamt/ })).toBeInTheDocument();
  });

  it('shows an empty state when all values are zero', () => {
    const zero = series.map((p) => ({ ...p, value: 0 }));
    render(<MiniChart title="Logins" data={zero} type="bar" accent="#A78BFA" />);
    expect(screen.getByText('Keine Daten im Zeitraum')).toBeInTheDocument();
  });
});
