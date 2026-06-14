import type { TimeseriesPoint } from '../types/api';

interface Props {
  title: string;
  data: TimeseriesPoint[];
  type: 'line' | 'bar';
  accent: string;       // e.g. '#A78BFA'
  height?: number;      // px, default 96
}

const W = 320;          // viewBox width (scales to container)
const PAD = 4;

function fmtDay(iso: string): string {
  const [, m, d] = iso.split('-');
  return `${d}.${m}`;
}

export function MiniChart({ title, data, type, accent, height = 96 }: Props) {
  const total = data.reduce((s, p) => s + p.value, 0);
  const max = Math.max(1, ...data.map((p) => p.value));
  const H = height;
  const innerH = H - PAD * 2;
  const stepX = data.length > 1 ? (W - PAD * 2) / (data.length - 1) : 0;
  const x = (i: number) => PAD + i * stepX;
  const y = (v: number) => PAD + innerH * (1 - v / max);

  const empty = total === 0;
  const label = `${title}: ${total} insgesamt über ${data.length} Tage`;

  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <p className="text-xs font-semibold" style={{ color: accent }}>{title}</p>
        <p className="text-xs tabular-nums" style={{ color: 'rgba(248,250,252,0.55)' }}>{total}</p>
      </div>

      {empty ? (
        <div className="flex items-center justify-center text-[11px]"
             style={{ height: H, color: 'rgba(248,250,252,0.3)' }}>
          Keine Daten im Zeitraum
        </div>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img"
             aria-label={label} preserveAspectRatio="none">
          {/* baseline + one mid gridline */}
          {[0.5, 1].map((g) => (
            <line key={g} x1={PAD} x2={W - PAD} y1={PAD + innerH * g} y2={PAD + innerH * g}
                  stroke="rgba(255,255,255,0.06)" strokeWidth={1} />
          ))}

          {type === 'line' ? (
            <>
              <polyline fill="none" stroke={accent} strokeWidth={2}
                        strokeLinejoin="round" strokeLinecap="round"
                        vectorEffect="non-scaling-stroke"
                        points={data.map((p, i) => `${x(i)},${y(p.value)}`).join(' ')} />
              {/* Use transparent full-height <rect> hit-areas instead of <circle> to avoid distortion */}
              {data.map((p, i) => (
                <rect key={i}
                  x={x(i) - (stepX > 0 ? stepX / 2 : 4)}
                  y={PAD}
                  width={stepX > 0 ? stepX : 8}
                  height={innerH}
                  fill="transparent">
                  <title>{`${fmtDay(p.day)}: ${p.value}`}</title>
                </rect>
              ))}
              {/* Dot markers as small fixed-size rects to avoid ellipse distortion */}
              {data.map((p, i) => (
                <rect key={`dot-${i}`}
                  x={x(i) - 2}
                  y={y(p.value) - 2}
                  width={4}
                  height={4}
                  fill={accent}
                  rx={1} />
              ))}
            </>
          ) : (
            data.map((p, i) => {
              const bw = Math.max(1, stepX * 0.6);
              const bh = innerH * (p.value / max);
              return (
                <rect key={i} x={x(i) - bw / 2} y={PAD + innerH - bh} width={bw} height={bh}
                      rx={1} fill={accent} opacity={0.85}>
                  <title>{`${fmtDay(p.day)}: ${p.value}`}</title>
                </rect>
              );
            })
          )}
        </svg>
      )}

      {!empty && (
        <div className="flex justify-between mt-1 text-[10px] tabular-nums"
             style={{ color: 'rgba(248,250,252,0.35)' }}>
          <span>{fmtDay(data[0].day)}</span>
          <span>{fmtDay(data[data.length - 1].day)}</span>
        </div>
      )}
    </div>
  );
}
