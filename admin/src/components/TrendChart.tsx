import { useId } from 'react';
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

// Structural colour constants — map to styleguide tokens surface-2, border, text-primary, text-tertiary.
// Using inline hex here because Recharts SVG props do not accept Tailwind class names.
const COLOR_SURFACE_2 = '#1C1C1C';   // --surface-2
const COLOR_BORDER = '#262626';       // --border
const COLOR_TEXT_PRIMARY = '#FAFAFA'; // --text-primary
const COLOR_TEXT_TERTIARY = '#6B6B70'; // --text-tertiary
const COLOR_GRID = '#1C1C1C';         // same as --surface-2 per styleguide chart spec

const TOOLTIP_STYLE = {
  background: COLOR_SURFACE_2,
  border: `1px solid ${COLOR_BORDER}`,
  borderRadius: 8,
  color: COLOR_TEXT_PRIMARY,
  fontSize: 12,
} as const;

export function TrendChart({ title, data, type, accent, loading }: TrendChartProps) {
  // useId() guarantees a unique, stable id per component instance — immune to
  // title/accent collisions and safe under concurrent rendering.
  const uid = useId();
  const gradId = `grad-${uid.replace(/:/g, '')}`;
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
            <CartesianGrid strokeDasharray="3 3" stroke={COLOR_GRID} vertical={false} />
            <XAxis
              dataKey="day"
              tickFormatter={fmtDay}
              tick={{ fill: COLOR_TEXT_TERTIARY, fontSize: 11 }}
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
            <CartesianGrid strokeDasharray="3 3" stroke={COLOR_GRID} vertical={false} />
            <XAxis
              dataKey="day"
              tickFormatter={fmtDay}
              tick={{ fill: COLOR_TEXT_TERTIARY, fontSize: 11 }}
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
