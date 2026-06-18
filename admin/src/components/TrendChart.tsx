import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import type { TimeseriesPoint } from '../types/api';

interface TrendChartProps {
  title: string;
  data: TimeseriesPoint[];
  type: 'line' | 'bar';
  accent: string;
  loading?: boolean;
}

function fmtDay(iso: string): string {
  const [, m, d] = iso.split('-');
  return `${d}.${m}`;
}

const TOOLTIP_STYLE = {
  background: '#1C1C1C',
  border: '1px solid #262626',
  borderRadius: 8,
  color: '#FAFAFA',
  fontSize: 12,
} as const;

export function TrendChart({ title, data, type, accent, loading }: TrendChartProps) {
  const gradId = `grad-${accent.replace('#', '')}`;
  const isEmpty = data.length === 0 || data.every((p) => p.value === 0);

  return (
    <div className="bg-surface rounded-card p-5 border border-border">
      <p className="text-[14px] font-semibold text-text-primary mb-4">{title}</p>

      {loading && data.length === 0 ? (
        <div className="animate-pulse bg-surface-2 rounded-card h-[220px]" />
      ) : isEmpty ? (
        <div className="flex items-center justify-center h-[220px]">
          <span className="text-text-tertiary text-sm">Keine Daten im Zeitraum</span>
        </div>
      ) : type === 'bar' ? (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1C1C1C" vertical={false} />
            <XAxis
              dataKey="day"
              tickFormatter={fmtDay}
              tick={{ fill: '#6B6B70', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis hide />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelFormatter={fmtDay}
            />
            <Bar dataKey="value" fill={accent} radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={data}>
            <defs>
              <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={accent} stopOpacity={0.25} />
                <stop offset="100%" stopColor={accent} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#1C1C1C" vertical={false} />
            <XAxis
              dataKey="day"
              tickFormatter={fmtDay}
              tick={{ fill: '#6B6B70', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis hide />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelFormatter={fmtDay}
            />
            <Area
              type="monotone"
              dataKey="value"
              stroke={accent}
              strokeWidth={2}
              fill={`url(#${gradId})`}
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
