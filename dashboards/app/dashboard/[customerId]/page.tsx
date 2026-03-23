'use client';

import { useParams, useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, BarChart, Bar, Cell,
} from 'recharts';
import { ArrowLeft, TrendingUp, TrendingDown, Minus,
         AlertTriangle, CheckCircle, Activity } from 'lucide-react';
import { sentinelApi } from '@/lib/api';

// ── Tier helpers ──────────────────────────────────────────────────────────────
const TIER_COLOR: Record<string, string> = {
  CRITICAL: '#DC2626', HIGH: '#EA580C', MODERATE: '#D97706',
  WATCH: '#CA8A04',    STABLE: '#16A34A',
};
const TIER_BG: Record<string, string> = {
  CRITICAL: '#FEF2F2', HIGH: '#FFF7ED', MODERATE: '#FFFBEB',
  WATCH: '#FEFCE8',    STABLE: '#F0FDF4',
};

function TierBadge({ label }: { label: string }) {
  return (
    <span className="px-3 py-1 rounded-full text-sm font-bold"
      style={{ color: TIER_COLOR[label] || '#16A34A', background: TIER_BG[label] || '#F0FDF4' }}>
      {label}
    </span>
  );
}

function DirectionIcon({ dir }: { dir: string }) {
  if (dir === 'positive')  return <TrendingUp  className="w-3.5 h-3.5 text-red-500" />;
  if (dir === 'negative')  return <TrendingDown className="w-3.5 h-3.5 text-green-600" />;
  return <Minus className="w-3.5 h-3.5 text-slate-400" />;
}

const fmtInr = (v: number) =>
  new Intl.NumberFormat('en-IN', { style:'currency', currency:'INR', maximumFractionDigits:0 }).format(v);

const fmtTime = (iso: string) =>
  new Date(iso).toLocaleString('en-IN', { day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit', hour12:true });

// ── Severity colour ───────────────────────────────────────────────────────────
function severityColor(s: number): string {
  if (s >= 0.75) return '#DC2626';
  if (s >= 0.55) return '#EA580C';
  if (s >= 0.40) return '#D97706';
  if (s >= 0.10) return '#CA8A04';
  return '#16A34A';
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function CustomerDetailPage() {
  const { customerId } = useParams<{ customerId: string }>();
  const router = useRouter();

  const { data: pulse, isLoading: pulseLoading } = useQuery({
    queryKey: ['pulse', customerId],
    queryFn:  () => sentinelApi.getCustomerPulse(customerId).then(r => r.data),
    refetchInterval: 15_000,
  });

  const { data: histData, isLoading: histLoading } = useQuery({
    queryKey: ['pulse-history', customerId],
    queryFn:  () => sentinelApi.getCustomerPulseHistory(customerId, 60).then(r => r.data),
    refetchInterval: 15_000,
  });

  const { data: baseline } = useQuery({
    queryKey: ['baseline', customerId],
    queryFn:  () => sentinelApi.getCustomerBaseline(customerId).then(r => r.data),
  });

  const events: any[] = histData?.events || [];

  // Build chart data (oldest first)
  const chartData = [...events].reverse().map((e, i) => ({
    idx:    i + 1,
    score:  parseFloat((e.pulse_score_after * 100).toFixed(1)),
    sev:    parseFloat((e.txn_severity * 100).toFixed(1)),
    cat:    e.inferred_category,
    dir:    e.severity_direction,
    time:   fmtTime(e.event_ts),
    amount: e.amount,
  }));

  // Top SHAP features from most recent event
  const topFeatures: any[] = events[0]?.top_features || [];

  const isLoading = pulseLoading || histLoading;

  if (isLoading) return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="animate-spin h-8 w-8 rounded-full border-2 border-blue-500 border-t-transparent" />
    </div>
  );

  const currentScore = pulse?.pulse_score ?? 0;
  const riskLabel    = pulse?.risk_label  ?? 'STABLE';

  return (
    <div className="min-h-screen bg-slate-50">

      {/* Header */}
      <header className="bg-white border-b border-slate-100 px-6 py-4 flex items-center gap-4 sticky top-0 z-20 shadow-sm">
        <button onClick={() => router.back()}
          className="p-2 rounded-xl hover:bg-slate-100 transition text-slate-400 hover:text-slate-600">
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="flex-1">
          <h1 className="text-base font-bold text-slate-800">Customer Detail</h1>
          <p className="text-xs text-slate-400 font-mono">{customerId}</p>
        </div>
        <TierBadge label={riskLabel} />
      </header>

      <main className="max-w-[1200px] mx-auto px-6 py-6 space-y-5">

        {/* Pulse Score Hero */}
        <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-6 flex flex-wrap gap-6 items-center">

          {/* Gauge */}
          <div className="flex-shrink-0 text-center">
            <div className="relative w-36 h-36">
              <svg viewBox="0 0 120 120" className="w-full h-full -rotate-90">
                <circle cx="60" cy="60" r="50" fill="none" stroke="#F1F5F9" strokeWidth="12" />
                <circle cx="60" cy="60" r="50" fill="none"
                  stroke={TIER_COLOR[riskLabel] || '#16A34A'} strokeWidth="12"
                  strokeDasharray={`${currentScore * 314} 314`}
                  strokeLinecap="round" className="transition-all duration-700" />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-3xl font-black text-slate-800">
                  {(currentScore * 100).toFixed(0)}
                </span>
                <span className="text-xs text-slate-400 -mt-1">/ 100</span>
              </div>
            </div>
            <p className="text-xs text-slate-400 mt-2">Overall Pulse Score</p>
          </div>

          {/* Stats grid */}
          <div className="flex-1 grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: 'Risk Tier',      value: <TierBadge label={riskLabel} /> },
              { label: 'Score (raw)',    value: currentScore.toFixed(5) },
              { label: 'Events scored', value: (pulse?.score_count ?? 0).toLocaleString('en-IN') },
              { label: 'Last updated',  value: pulse?.last_updated ? fmtTime(pulse.last_updated) : '—' },
              { label: 'Baseline txns', value: (baseline?.transaction_count ?? '—').toLocaleString?.() || '—' },
              { label: 'Confidence',    value: baseline?.low_confidence ? '⚠ Low' : '✓ High' },
              { label: 'Baseline start',value: baseline?.history_start || '—' },
              { label: 'Baseline end',  value: baseline?.history_end   || '—' },
            ].map(s => (
              <div key={s.label} className="bg-slate-50 rounded-xl p-3">
                <p className="text-xs text-slate-400 mb-1">{s.label}</p>
                <div className="text-sm font-semibold text-slate-700">{s.value}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Pulse Score Timeline */}
        <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-5">
          <h2 className="text-sm font-bold text-slate-700 mb-4 flex items-center gap-2">
            <Activity className="w-4 h-4 text-blue-500" />
            Pulse Score Timeline
            <span className="text-xs font-normal text-slate-400 ml-1">(last {chartData.length} transactions)</span>
          </h2>

          {chartData.length === 0 ? (
            <div className="h-48 flex items-center justify-center text-slate-400 text-sm">
              No transaction events yet. Inject some transactions to see the timeline.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" />
                <XAxis dataKey="idx" tick={{ fontSize: 11, fill: '#94A3B8' }}
                  label={{ value: 'Transaction #', position: 'insideBottom', offset: -2, fontSize: 11, fill: '#94A3B8' }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: '#94A3B8' }}
                  tickFormatter={v => `${v}`} width={35} />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #E2E8F0' }}
                  formatter={(v: any, n: string) => [n === 'score' ? `${v}/100` : `${v}%`, n === 'score' ? 'Pulse' : 'Severity']}
                  labelFormatter={(_: any, payload: any[]) => payload?.[0]?.payload?.time || ''} />
                {/* Tier reference lines */}
                {[
                  { y: 75, color: '#DC2626', label: 'CRITICAL' },
                  { y: 55, color: '#EA580C', label: 'HIGH' },
                  { y: 40, color: '#D97706', label: 'MODERATE' },
                  { y: 25, color: '#CA8A04', label: 'WATCH' },
                ].map(t => (
                  <ReferenceLine key={t.label} y={t.y} stroke={t.color}
                    strokeDasharray="4 3" strokeOpacity={0.5}
                    label={{ value: t.label, position: 'right', fontSize: 9, fill: t.color }} />
                ))}
                <Line type="monotone" dataKey="score" stroke="#3B82F6" strokeWidth={2.5}
                  dot={false} activeDot={{ r: 5, fill: '#3B82F6' }} name="score" />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* SHAP Features + Transaction History */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">

          {/* SHAP */}
          <div className="lg:col-span-2 bg-white rounded-2xl border border-slate-100 shadow-sm p-5">
            <h2 className="text-sm font-bold text-slate-700 mb-4">Top Score Drivers</h2>
            {topFeatures.length === 0 ? (
              <p className="text-xs text-slate-400 py-6 text-center">No SHAP data yet</p>
            ) : (
              <div className="space-y-3">
                {topFeatures.map((f: any, i: number) => {
                  const isStress  = f.direction === 'stress';
                  const barColor  = isStress ? '#DC2626' : '#16A34A';
                  const maxAbs    = Math.max(...topFeatures.map((x: any) => Math.abs(x.shap)));
                  const pct       = maxAbs > 0 ? (Math.abs(f.shap) / maxAbs) * 100 : 0;
                  return (
                    <div key={i}>
                      <div className="flex justify-between items-center mb-1">
                        <span className="text-xs text-slate-600 truncate pr-2" title={f.feature}>
                          {f.feature.replace(/_/g, ' ')}
                        </span>
                        <span className="text-xs font-mono font-semibold flex-shrink-0"
                          style={{ color: barColor }}>
                          {isStress ? '+' : ''}{f.shap.toFixed(3)}
                        </span>
                      </div>
                      <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                        <div className="h-full rounded-full transition-all"
                          style={{ width: `${pct}%`, background: barColor }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Transaction History */}
          <div className="lg:col-span-3 bg-white rounded-2xl border border-slate-100 shadow-sm flex flex-col">
            <div className="px-5 py-4 border-b border-slate-100">
              <h2 className="text-sm font-bold text-slate-700">Transaction Pulse Events</h2>
              <p className="text-xs text-slate-400 mt-0.5">Most recent first</p>
            </div>
            <div className="overflow-y-auto flex-1" style={{ maxHeight: 380 }}>
              {events.length === 0 ? (
                <div className="p-6 text-center text-sm text-slate-400">
                  No events yet. Inject transactions to see results.
                </div>
              ) : events.map((e: any, i: number) => {
                const isStress = e.severity_direction === 'positive';
                const isRelief = e.severity_direction === 'negative';
                return (
                  <div key={i}
                    className="px-5 py-3.5 border-b border-slate-50 flex items-start gap-3 hover:bg-slate-50 transition-colors">

                    {/* Icon */}
                    <div className={`mt-0.5 w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 ${
                      isStress ? 'bg-red-50' : isRelief ? 'bg-green-50' : 'bg-slate-100'
                    }`}>
                      {isStress
                        ? <AlertTriangle className="w-3.5 h-3.5 text-red-500" />
                        : isRelief
                          ? <CheckCircle className="w-3.5 h-3.5 text-green-600" />
                          : <Activity className="w-3.5 h-3.5 text-slate-400" />
                      }
                    </div>

                    {/* Content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-semibold text-slate-700">
                          {e.inferred_category.replace(/_/g, ' ')}
                        </span>
                        <span className="text-xs px-1.5 py-0.5 rounded font-mono"
                          style={{
                            background: `${severityColor(e.txn_severity)}15`,
                            color: severityColor(e.txn_severity),
                          }}>
                          sev {e.txn_severity.toFixed(3)}
                        </span>
                        <span className={`text-xs font-mono ${
                          e.delta_applied > 0 ? 'text-red-500' :
                          e.delta_applied < 0 ? 'text-green-600' : 'text-slate-400'
                        }`}>
                          {e.delta_applied > 0 ? '+' : ''}{e.delta_applied.toFixed(4)}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 mt-0.5">
                        <span className="text-xs text-slate-500">
                          {fmtInr(e.amount)} · {e.platform}
                        </span>
                        <span className="text-xs text-slate-400">{fmtTime(e.event_ts)}</span>
                      </div>
                      <div className="flex items-center gap-1 mt-1 text-xs text-slate-400">
                        <span>{e.pulse_score_before.toFixed(3)}</span>
                        <DirectionIcon dir={e.severity_direction} />
                        <span className="font-semibold" style={{ color: severityColor(e.pulse_score_after) }}>
                          {e.pulse_score_after.toFixed(3)}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

      </main>
    </div>
  );
}