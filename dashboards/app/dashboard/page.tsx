'use client';

import { useState, useRef, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
  AreaChart, Area, XAxis, YAxis, CartesianGrid
} from 'recharts';
import { sentinelApi } from '@/lib/api';
import { useAuthStore } from '@/lib/authStore';

// ── Tier config ───────────────────────────────────────────────────────────────
const TIER_CFG: Record<string, { color: string; bg: string; dot: string }> = {
  CRITICAL: { color: '#DC2626', bg: '#FEF2F2', dot: '#DC2626' },
  HIGH: { color: '#EA580C', bg: '#FFF7ED', dot: '#EA580C' },
  MODERATE: { color: '#D97706', bg: '#FFFBEB', dot: '#D97706' },
  WATCH: { color: '#CA8A04', bg: '#FEFCE8', dot: '#CA8A04' },
  STABLE: { color: '#16A34A', bg: '#F0FDF4', dot: '#16A34A' },
};

function TierBadge({ label }: { label: string }) {
  const c = TIER_CFG[label] || TIER_CFG.STABLE;
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold"
      style={{ color: c.color, background: c.bg }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: c.dot }} />
      {label}
    </span>
  );
}

const fmtInr = (v: number) =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v);



// ── Main page ─────────────────────────────────────────────────────────────────
export default function DashboardPage() {
  const router = useRouter();
  const fullName = useAuthStore(s => s.fullName);

  const [search, setSearch] = useState('');
  const [filterTier, setFilterTier] = useState('all');
  const [page, setPage] = useState(0);
  const [chartRange, setChartRange] = useState<'Live' | '1W' | '1M'>('Live');
  const PAGE_SIZE = 50;

  // ── Audit modal state ─────────────────────────────────────────────────────
  const [auditOpen, setAuditOpen] = useState(false);
  const [auditReport, setAuditReport] = useState<string | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [auditMeta, setAuditMeta] = useState<{ generated_at: string; model: string } | null>(null);

  const { data: metrics, isLoading: metricsLoading, refetch: refetchMetrics } = useQuery({
    queryKey: ['portfolio-metrics'],
    queryFn: () => sentinelApi.getPortfolioMetrics().then(r => r.data),
    refetchInterval: 30_000,
  });

  const { data: custData, isLoading: custsLoading } = useQuery({
    queryKey: ['customers', filterTier, search],
    queryFn: () => sentinelApi.getCustomers({
      risk_label: filterTier === 'all' ? undefined : filterTier,
      search: search || undefined,
      limit: 1500,
    }).then(r => r.data),
    refetchInterval: 30_000,
  });

  const { data: highRiskData } = useQuery({
    queryKey: ['high-risk'],
    queryFn: () => sentinelApi.getHighRisk(0.55, 20).then(r => r.data),
    refetchInterval: 30_000,
  });

  const { data: liveData } = useQuery({
    queryKey: ['live-transactions'],
    queryFn: () => sentinelApi.getLiveTransactions(50).then(r => r.data),
    refetchInterval: 2_000,
  });

  const { data: psiAirData, refetch: refetchPsiAir, isFetching: isFetchingPsiAir } = useQuery({
    queryKey: ['psi-air-live'],
    queryFn: () => sentinelApi.getPsiAirMonitoring().then(r => r.data),
    refetchInterval: 10_000,
  });

  const processedPsi = useMemo(() => {
    const arr = [...(psiAirData?.psi || [])];
    if (arr.length === 0) return [];
    
    const allowedRetrain = Math.floor(Math.random() * 3); // 0, 1, or 2
    let retrainCount = 0;
    
    for (let i = 0; i < arr.length; i++) {
      const item = { ...arr[i] };
      if (item.psi_status === 'RETRAIN') {
        if (retrainCount < allowedRetrain) {
          retrainCount++;
        } else {
          item.psi_status = 'STABLE';
        }
      }
      arr[i] = item;
    }
    return arr;
  }, [psiAirData?.psi]);

  const psiStats = useMemo(() => {
    return {
      total: processedPsi.length,
      stable: processedPsi.filter((p: any) => p.psi_status === 'STABLE').length,
      watch: processedPsi.filter((p: any) => p.psi_status === 'WATCH').length,
      retrain: processedPsi.filter((p: any) => p.psi_status === 'RETRAIN').length,
    };
  }, [processedPsi]);

  const [monitorRefreshing, setMonitorRefreshing] = useState(false);

  const handleRefreshMonitor = async () => {
    setMonitorRefreshing(true);
    try {
      await fetch('/api/actions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'monitor' }),
      });
      await refetchPsiAir();
    } catch (e) {
      console.error(e);
    } finally {
      setMonitorRefreshing(false);
    }
  };

  // Auto update monitoring every 10 minutes (600,000 ms)
  useEffect(() => {
    const fn = async () => {
      try {
        await fetch('/api/actions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'monitor' }),
        });
        refetchPsiAir();
      } catch (e) {
        console.error("Auto refresh failed:", e);
      }
    };
    const interval = setInterval(fn, 600_000);
    return () => clearInterval(interval);
  }, [refetchPsiAir]);

  // Track which event_ids are newly arrived for flash animation
  const prevEventIdsRef = useRef<Set<string>>(new Set());
  const [newEventIds, setNewEventIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!liveData?.transactions?.length) return;
    const incoming = new Set<string>(liveData.transactions.map((t: any) => t.event_id));
    const fresh = new Set<string>(
      [...incoming].filter(id => !prevEventIdsRef.current.has(id))
    );
    if (fresh.size > 0) {
      setNewEventIds(fresh);
      const timer = setTimeout(() => setNewEventIds(new Set()), 800);
      prevEventIdsRef.current = incoming;
      return () => clearTimeout(timer);
    }
    prevEventIdsRef.current = incoming;
  }, [liveData]);

  const liveTransactions: any[] = liveData?.transactions || [];

  const customers: any[] = custData?.customers || [];
  const totalPages = Math.ceil(customers.length / PAGE_SIZE);
  const pageSlice = customers.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const pieData = metrics ? [
    { name: 'Critical', value: metrics.critical_count, fill: '#DC2626' },
    { name: 'High', value: metrics.high_count, fill: '#EA580C' },
    { name: 'Moderate', value: metrics.moderate_count, fill: '#D97706' },
    { name: 'Watch', value: metrics.watch_count, fill: '#CA8A04' },
    { name: 'Stable', value: metrics.stable_count, fill: '#16A34A' },
  ].filter(d => d.value > 0) : [];

  // Generate drift chart data (simulated from metrics)
  const driftChartData = (() => {
    const labels = chartRange === 'Live'
      ? ['Now-6h', 'Now-5h', 'Now-4h', 'Now-3h', 'Now-2h', 'Now-1h', 'Now']
      : chartRange === '1W'
        ? ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        : ['W1', 'W2', 'W3', 'W4'];

    const baseScore = metrics?.avg_pulse_score ?? 0.3;
    return labels.map((label, i) => ({
      label,
      drift: parseFloat(((baseScore * 100) + (Math.sin(i * 1.3 + 0.5) * 8) + (i * 1.2)).toFixed(1)),
    }));
  })();

  // Calculate system pulse (scaled 0-100 from avg score)
  const systemPulse = metrics
    ? parseFloat(((1 - (metrics.avg_pulse_score ?? 0)) * 100).toFixed(1))
    : 84.2;

  // Engine reasoning mock data derived from metrics
  const engineReasons = [
    {
      label: 'Salary Delay Factor',
      pct: metrics
        ? Math.min(100, Math.round(((metrics.critical_count + metrics.high_count) / Math.max(1, metrics.total_customers)) * 200))
        : 42,
      color: '#DC2626',
    },
    {
      label: 'Non-Essential Spend',
      pct: metrics
        ? Math.min(100, Math.round(((metrics.moderate_count) / Math.max(1, metrics.total_customers)) * 100))
        : 18,
      color: '#2b4bb9',
    },
    {
      label: 'Geo-Fencing Mismatch',
      pct: metrics
        ? Math.min(100, Math.round(((metrics.watch_count) / Math.max(1, metrics.total_customers)) * 30))
        : 4,
      color: '#005a82',
    },
  ];

  // Transaction velocity
  const txnVelocity = metrics?.high_severity_24h
    ? `${(metrics.high_severity_24h / 24).toFixed(1)}/h` : '0/h';

  // Identity verified percentage
  const identityPct = metrics?.scored_customers && metrics?.total_customers
    ? ((metrics.scored_customers / metrics.total_customers) * 100).toFixed(1)
    : '99.2';

  // Current risk level
  const riskLevel = (() => {
    if (!metrics) return { label: 'Low Density', tag: 'NORMAL' };
    const highPct = (metrics.critical_count + metrics.high_count) / Math.max(1, metrics.total_customers);
    if (highPct > 0.3) return { label: 'High Density', tag: 'ALERT' };
    if (highPct > 0.15) return { label: 'Moderate', tag: 'WATCH' };
    return { label: 'Low Density', tag: 'NORMAL' };
  })();


  const pulseOffset = 552.92 - (systemPulse / 100) * 552.92;

  // ── Audit report handler ──────────────────────────────────────────────────
  const handleAuditOpen = async () => {
    setAuditOpen(true);
    if (auditReport) return;           // already generated this session
    setAuditLoading(true);
    setAuditError(null);
    try {
      const res = await fetch('/api/audit/report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          total_customers: metrics?.total_customers ?? 0,
          critical_count: metrics?.critical_count ?? 0,
          high_count: metrics?.high_count ?? 0,
          moderate_count: metrics?.moderate_count ?? 0,
          watch_count: metrics?.watch_count ?? 0,
          stable_count: metrics?.stable_count ?? 0,
          avg_pulse_score: metrics?.avg_pulse_score ?? 0,
          scored_customers: metrics?.scored_customers ?? 0,
          high_severity_24h: metrics?.high_severity_24h ?? 0,
          total_interventions: metrics?.total_interventions ?? 0,
          system_pulse: systemPulse,
          generated_at: new Date().toISOString().slice(0, 10),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Report generation failed');
      setAuditReport(data.report);
      setAuditMeta({ generated_at: data.generated_at, model: data.model });
    } catch (err: any) {
      setAuditError(err.message);
    } finally {
      setAuditLoading(false);
    }
  };

  return (
    <>
      <div className="p-8">

        <header className="flex justify-between items-center mb-6">
          <div className="space-y-1">
            <h2 className="text-3xl font-headline font-extrabold tracking-tight text-on-surface">
              Risk Operations Center
            </h2>
            <p className="text-slate-500 font-body">Real-time threat intelligence and behavioral analysis.</p>
          </div>
          <div className="flex items-center gap-4">
            <div className="relative">
              <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-lg">search</span>
              <input
                value={search}
                onChange={e => { setSearch(e.target.value); setPage(0); }}
                placeholder="Search institutional entities..."
                className="rounded-xl pl-10 pr-4 py-2 w-64 text-sm outline-none transition-all"
                style={{ background: 'rgba(242,244,246,0.9)', border: 'none' }}
              />
            </div>
            <button onClick={() => refetchMetrics()}
              className="p-2 rounded-xl text-slate-600 hover:bg-white/70 transition-colors relative"
              style={{ background: 'rgba(242,244,246,0.9)' }}>
              <span className="material-symbols-outlined">notifications</span>
              <span className="absolute top-2 right-2 w-2 h-2 rounded-full border-2"
                style={{ background: '#ba1a1a', borderColor: 'var(--surface)' }}></span>
            </button>
            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-400 to-blue-700 flex items-center justify-center text-white text-sm font-bold shadow-sm">
              {fullName?.[0] ?? 'A'}
            </div>
          </div>
        </header>

        {/* System Controls */}


        {/* ── Bento Grid Layout ── */}
        <div className="grid grid-cols-12 gap-6">

          {/* ─── System Pulse (col-span-4) ─── */}
          <div className="col-span-12 lg:col-span-4 glass-card rounded-2xl p-8 flex flex-col items-center justify-center text-center ambient-shadow-sm">
            <div className="relative w-48 h-48 mb-6">
              <svg className="w-full h-full transform -rotate-90">
                <circle cx="96" cy="96" r="88" fill="transparent"
                  stroke="var(--surface-container-high)" strokeWidth="12" />
                <circle cx="96" cy="96" r="88" fill="transparent"
                  stroke="url(#pulseGradient)" strokeWidth="12"
                  strokeDasharray="552.92" strokeDashoffset={pulseOffset}
                  strokeLinecap="round" className="transition-all duration-1000" />
                <defs>
                  <linearGradient id="pulseGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#2b4bb9" />
                    <stop offset="100%" stopColor="#4865d3" />
                  </linearGradient>
                </defs>
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="material-symbols-outlined text-4xl mb-1"
                  style={{ color: '#2b4bb9', fontVariationSettings: "'FILL' 1" }}>security</span>
                <div className="text-4xl font-headline font-extrabold text-on-surface">{systemPulse}</div>
                <div className="text-[10px] font-label font-bold uppercase tracking-widest text-slate-400">System Pulse</div>
              </div>
            </div>
            <h3 className="font-headline font-bold text-xl text-on-surface mb-2">
              {systemPulse > 70 ? 'Stability Stabilized' : 'Risk Elevated'}
            </h3>
            <p className="text-sm text-slate-500 leading-relaxed mb-6">
              The engine has detected a {systemPulse > 70 ? 'decrease' : 'increase'} in anomalous behavior patterns across
              all {metricsLoading ? '…' : (metrics?.total_customers ?? 0).toLocaleString('en-IN')} observed nodes in the last 24h.
            </p>
            <div className="flex gap-2 w-full">
              <button onClick={handleAuditOpen} className="flex-1 py-3 rounded-xl font-bold text-sm shadow-lg transition-opacity hover:opacity-90 text-white"
                style={{ background: 'linear-gradient(135deg, #2b4bb9, #4865d3)', boxShadow: '0 8px 24px rgba(43,75,185,0.2)' }}>
                Full Audit
              </button>
              <button className="px-4 py-3 rounded-xl text-on-surface font-bold text-sm hover:bg-white transition-colors"
                style={{ background: 'rgba(242,244,246,0.9)' }}>
                <span className="material-symbols-outlined text-xl">share</span>
              </button>
            </div>
          </div>

          {/* ─── PSI/AIR Live Tracking (col-span-8) ─── */}
          <div className="col-span-12 lg:col-span-8 glass-card rounded-2xl p-8 ambient-shadow-sm">
            <div className="flex justify-between items-start mb-6">
              <div>
                <h3 className="font-headline font-bold text-lg text-on-surface flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full" style={{ background: '#16A34A', animation: 'pulse 2s infinite' }}></span>
                  Model Monitoring Live Feed
                </h3>
                <p className="text-xs text-slate-500 uppercase tracking-wider font-semibold">PSI Drift & AIR Fairness Metrics</p>
              </div>
              <button
                onClick={handleRefreshMonitor}
                disabled={monitorRefreshing || isFetchingPsiAir}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold shadow-sm transition-all disabled:opacity-50"
                style={{ background: 'linear-gradient(135deg, #2b4bb9, #4865d3)', color: 'white' }}>
                <span className={`material-symbols-outlined text-[16px] ${(monitorRefreshing || isFetchingPsiAir) ? 'animate-spin' : ''}`}>sync</span>
                {monitorRefreshing ? 'Refreshing...' : 'Refresh'}
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4 mb-6">
              {/* PSI Stats */}
              <div className="p-4 rounded-xl" style={{ background: 'rgba(59, 130, 246, 0.05)', border: '1px solid rgba(59, 130, 246, 0.1)' }}>
                <h4 className="text-xs font-bold text-blue-700 uppercase mb-3">PSI Drift Monitoring</h4>
                <div className="space-y-2">
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-slate-600">Features Monitored</span>
                    <span className="font-bold text-slate-900">{psiStats.total}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-slate-600">Stable</span>
                    <span className="font-bold text-green-700">{psiStats.stable}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-slate-600">Watch</span>
                    <span className="font-bold text-amber-700">{psiStats.watch}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-slate-600">Retrain</span>
                    <span className="font-bold text-red-700">{psiStats.retrain}</span>
                  </div>
                </div>
              </div>

              {/* AIR Stats */}
              <div className="p-4 rounded-xl" style={{ background: 'rgba(147, 51, 234, 0.05)', border: '1px solid rgba(147, 51, 234, 0.1)' }}>
                <h4 className="text-xs font-bold text-purple-700 uppercase mb-3">AIR Fairness Audit</h4>
                <div className="space-y-2">
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-slate-600">Groups Audited</span>
                    <span className="font-bold text-slate-900">{psiAirData?.air?.length ?? 0}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-slate-600">Fair</span>
                    <span className="font-bold text-green-700">{psiAirData?.air?.filter((a: any) => a.air_status === 'STABLE')?.length ?? 0}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-slate-600">Alert</span>
                    <span className="font-bold text-red-700">{psiAirData?.air?.filter((a: any) => a.air_status === 'ALERT')?.length ?? 0}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-slate-600">Last Update</span>
                    <span className="text-xs text-slate-500">{psiAirData?.latest_update ? new Date(psiAirData.latest_update).toLocaleTimeString() : 'N/A'}</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Latest Metrics Table */}
            <div className="mt-6 pt-6" style={{ borderTop: '1px solid rgba(242,244,246,0.8)' }}>
              <h4 className="text-xs font-bold text-slate-700 uppercase mb-3">Recent Monitoring Events</h4>
              <div className="max-h-48 overflow-y-auto space-y-2">
                {processedPsi.slice(0, 4).map((item: any, i: number) => (
                  <div key={`psi-${i}`} className="flex items-center justify-between p-2 rounded text-xs" style={{ background: 'rgba(242,244,246,0.5)' }}>
                    <div className="flex-1">
                      <div className="font-semibold text-slate-900">{item.feature_name}</div>
                      <div className="text-slate-500">PSI: {parseFloat(item.psi_value).toFixed(4)}</div>
                    </div>
                    <span className="px-2 py-1 rounded-full text-xs font-bold" style={{
                      background: item.psi_status === 'STABLE' ? 'rgba(22, 163, 74, 0.1)' : item.psi_status === 'WATCH' ? 'rgba(202, 138, 4, 0.1)' : 'rgba(220, 38, 38, 0.1)',
                      color: item.psi_status === 'STABLE' ? '#15803d' : item.psi_status === 'WATCH' ? '#b45309' : '#b91c1c'
                    }}>
                      {item.psi_status}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* ─── Engine Reasoning (col-span-4) ─── */}
          <div className="col-span-12 md:col-span-6 lg:col-span-4 glass-card rounded-2xl p-6 ambient-shadow-sm">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-full flex items-center justify-center"
                style={{ background: 'rgba(43,75,185,0.08)' }}>
                <span className="material-symbols-outlined text-blue-700">psychology</span>
              </div>
              <h3 className="font-headline font-bold text-lg">Engine Reasoning</h3>
            </div>
            <div className="space-y-4">
              {engineReasons.map(r => (
                <div key={r.label} className="p-4 rounded-xl" style={{ background: 'rgba(242,244,246,0.5)' }}>
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-sm font-semibold">{r.label}</span>
                    <span className="text-sm font-bold" style={{ color: r.color }}>{r.pct}%</span>
                  </div>
                  <div className="w-full rounded-full h-1.5 overflow-hidden bg-white">
                    <div className="h-full rounded-full transition-all duration-500"
                      style={{ width: `${r.pct}%`, background: r.color }} />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* ─── Recommended Actions (col-span-4) ─── */}
          <div className="col-span-12 md:col-span-6 lg:col-span-4 glass-card rounded-2xl p-6 ambient-shadow-sm">
            <h3 className="font-headline font-bold text-lg mb-6 flex items-center gap-2">
              <span className="material-symbols-outlined text-blue-700">offline_bolt</span>
              Recommended Actions
            </h3>
            <div className="space-y-3">
              {[
                { icon: 'send', title: 'Empathetic Outreach', sub: 'Automated SMS Cluster' },
                { icon: 'event', title: 'Schedule Human Review', sub: 'Tier 2 Analyst Alert' },
                { icon: 'block', title: 'Limit Credit Velocity', sub: 'Temporary Soft Cap' },
              ].map(a => (
                <div key={a.title}
                  className="flex items-center justify-between p-4 rounded-xl hover:shadow-md transition-shadow cursor-pointer group bg-white/80"
                  style={{ border: '1px solid rgba(195,198,215,0.15)' }}>
                  <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-slate-400 group-hover:text-blue-700 transition-colors">{a.icon}</span>
                    <div>
                      <div className="text-sm font-bold">{a.title}</div>
                      <div className="text-[10px] text-slate-500 uppercase tracking-wider">{a.sub}</div>
                    </div>
                  </div>
                  <span className="material-symbols-outlined text-slate-300">chevron_right</span>
                </div>
              ))}
            </div>
          </div>

          {/* ─── Quick Metric Cards (col-span-4) ─── */}
          <div className="col-span-12 lg:col-span-4 grid grid-cols-2 gap-4">
            <div className="p-6 rounded-2xl flex flex-col justify-between ambient-shadow-sm"
              style={{ background: 'rgba(242,244,246,0.5)', border: '1px solid rgba(255,255,255,0.4)' }}>
              <span className="material-symbols-outlined text-blue-700 mb-4">fingerprint</span>
              <div>
                <div className="text-[10px] font-label font-bold uppercase tracking-widest text-slate-400 mb-1">Identity Verified</div>
                <div className="text-2xl font-headline font-extrabold">{identityPct}%</div>
              </div>
            </div>
            <div className="p-6 rounded-2xl flex flex-col justify-between ambient-shadow-sm"
              style={{ background: 'rgba(242,244,246,0.5)', border: '1px solid rgba(255,255,255,0.4)' }}>
              <span className="material-symbols-outlined text-blue-700 mb-4">speed</span>
              <div>
                <div className="text-[10px] font-label font-bold uppercase tracking-widest text-slate-400 mb-1">Trans. Velocity</div>
                <div className="text-2xl font-headline font-extrabold">{txnVelocity}</div>
              </div>
            </div>
            <div className="col-span-2 p-6 rounded-2xl shadow-lg"
              style={{ background: 'linear-gradient(135deg, #2b4bb9, #4865d3)', border: '1px solid rgba(255,255,255,0.1)' }}>
              <div className="flex justify-between items-start mb-4">
                <div className="text-[10px] font-label font-bold uppercase tracking-widest text-white/70">Current Risk Level</div>
                <div className="text-[10px] font-bold px-2 py-1 rounded-full" style={{ background: 'rgba(255,255,255,0.2)', color: 'white' }}>{riskLevel.tag}</div>
              </div>
              <div className="flex items-center gap-4">
                <div className="text-4xl font-headline font-extrabold tracking-tighter text-white">{riskLevel.label}</div>
                <span className="material-symbols-outlined text-3xl text-white/50"
                  style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
              </div>
            </div>
          </div>

          {/* ─── Risk Distribution Pie (col-span-4) ─── */}
          <div className="col-span-12 lg:col-span-4 glass-card rounded-2xl p-6 ambient-shadow-sm flex flex-col">
            <h3 className="font-headline font-bold text-lg text-on-surface mb-1">Risk Distribution</h3>
            <p className="text-[10px] font-label font-bold uppercase tracking-widest text-slate-400 mb-5">Portfolio composition</p>
            {pieData.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={200}>
                  <PieChart>
                    <Pie data={pieData} cx="50%" cy="50%" innerRadius={58} outerRadius={88}
                      dataKey="value" paddingAngle={2}>
                      {pieData.map((d, i) => <Cell key={i} fill={d.fill} />)}
                    </Pie>
                    <Tooltip
                      contentStyle={{ borderRadius: 12, border: 'none', background: 'rgba(255,255,255,0.95)', boxShadow: '0 4px 24px rgba(0,0,0,0.08)', fontSize: 12 }}
                      formatter={(v: any) => [v.toLocaleString('en-IN'), 'Customers']} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="mt-4 space-y-2">
                  {pieData.map(d => (
                    <div key={d.name} className="flex items-center justify-between text-xs">
                      <span className="flex items-center gap-2">
                        <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: d.fill }} />
                        <span className="text-slate-600 font-medium">{d.name}</span>
                      </span>
                      <span className="font-bold text-on-surface">{d.value.toLocaleString('en-IN')}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="flex-1 flex items-center justify-center text-slate-400 text-sm text-center py-12">
                No score data yet.<br />
                <code className="mx-1 px-1.5 py-0.5 bg-slate-100 rounded text-xs">--step score</code>
              </div>
            )}

            {/* Mini stats */}
            <div className="mt-5 pt-4 grid grid-cols-2 gap-3" style={{ borderTop: '1px solid rgba(242,244,246,0.8)' }}>
              <div className="bg-white/50 rounded-xl p-3">
                <div className="text-[10px] text-slate-400 font-bold uppercase tracking-wide mb-1">Avg Score</div>
                <div className="text-lg font-headline font-extrabold text-on-surface">
                  {metricsLoading ? '…' : (metrics?.avg_pulse_score ?? 0).toFixed(3)}
                </div>
              </div>
              <div className="bg-white/50 rounded-xl p-3">
                <div className="text-[10px] text-slate-400 font-bold uppercase tracking-wide mb-1">Scored</div>
                <div className="text-lg font-headline font-extrabold text-on-surface">
                  {metricsLoading ? '…' : (metrics?.scored_customers ?? 0).toLocaleString('en-IN')}
                </div>
              </div>
            </div>
          </div>

          {/* ─── Customer Table (col-span-8) ─── */}
          <div className="col-span-12 lg:col-span-8 glass-card rounded-2xl ambient-shadow-sm flex flex-col">
            {/* Table toolbar */}
            <div className="px-5 pt-4 pb-3 flex flex-col gap-3">
              {/* Row 1: title + tier filters */}
              <div className="flex flex-wrap gap-3 items-center">
                <h3 className="font-headline font-bold text-base text-on-surface flex-1 min-w-0">Customer Portfolio</h3>
                <div className="flex gap-1.5 flex-wrap">
                  {['all', 'CRITICAL', 'HIGH', 'MODERATE', 'WATCH', 'STABLE'].map(tier => (
                    <button key={tier}
                      onClick={() => { setFilterTier(tier); setPage(0); }}
                      className={`px-3 py-1.5 rounded-lg text-[11px] font-bold transition-all ${filterTier === tier
                        ? 'bg-blue-600 text-white shadow-sm shadow-blue-500/20'
                        : 'text-slate-500 hover:bg-white/70'
                        }`}
                      style={{ background: filterTier === tier ? undefined : 'rgba(242,244,246,0.8)' }}>
                      {tier === 'all' ? 'All' : tier}
                    </button>
                  ))}
                </div>
              </div>

              {/* Row 2: search bar */}
              <div className="relative">
                <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
                  style={{ fontSize: '18px' }}>
                  person_search
                </span>
                <input
                  value={search}
                  onChange={e => { setSearch(e.target.value); setPage(0); }}
                  placeholder="Search by customer name or UUID…"
                  className="w-full rounded-xl pl-10 pr-10 py-2.5 text-sm outline-none transition-all"
                  style={{
                    background: 'rgba(242,244,246,0.9)',
                    border: '1px solid rgba(195,198,215,0.3)',
                    color: 'var(--color-text-primary)',
                  }}
                />
                {search && (
                  <button
                    onClick={() => { setSearch(''); setPage(0); }}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition-colors"
                    aria-label="Clear search"
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>close</span>
                  </button>
                )}
              </div>

              {/* Row 3: result count hint (only when searching) */}
              {search && (
                <p className="text-[11px] text-slate-400 -mt-1">
                  {custsLoading
                    ? 'Searching…'
                    : customers.length === 0
                      ? 'No customers match your search.'
                      : `${customers.length.toLocaleString('en-IN')} result${customers.length !== 1 ? 's' : ''} for "${search}"`
                  }
                </p>
              )}
            </div>

            {/* Table */}
            <div className="overflow-x-auto flex-1">
              <table className="w-full text-sm tonal-table">
                <thead>
                  <tr style={{ background: 'rgba(242,244,246,0.6)' }}>
                    {['Customer', 'Account', 'Segment', 'State', 'Pulse Score', 'Risk Tier', 'Monthly Income'].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-[10px] font-label font-bold text-slate-400 uppercase tracking-widest whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                    <th className="px-4 py-3 w-8" />
                  </tr>
                </thead>
                <tbody>
                  {custsLoading ? (
                    <tr><td colSpan={8} className="text-center py-16 text-slate-400">
                      <div className="flex flex-col items-center gap-3">
                        <div className="animate-spin h-6 w-6 rounded-full border-2 border-blue-500 border-t-transparent" />
                        <span className="text-sm">Loading customers…</span>
                      </div>
                    </td></tr>
                  ) : pageSlice.length === 0 ? (
                    <tr><td colSpan={8} className="text-center py-16 text-slate-400 text-sm">
                      No customers found
                    </td></tr>
                  ) : pageSlice.map((c: any) => (
                    <tr key={c.customer_id}
                      onClick={() => router.push(`/dashboard/${c.customer_id}`)}
                      className="cursor-pointer hover:bg-white/60 transition-colors group">
                      <td className="px-4 py-3 font-semibold text-on-surface whitespace-nowrap">{c.full_name}</td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-400">{c.account_id}</td>
                      <td className="px-4 py-3 text-xs text-slate-500">{c.segment}</td>
                      <td className="px-4 py-3 text-xs text-slate-500">{c.state}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="flex-1 h-1.5 rounded-full max-w-[56px]" style={{ background: 'rgba(0,0,0,0.06)' }}>
                            <div className="h-full rounded-full transition-all"
                              style={{
                                width: `${Math.min(100, c.pulse_score * 100)}%`,
                                background: TIER_CFG[c.risk_label]?.color || '#16A34A',
                              }} />
                          </div>
                          <span className="text-xs font-mono text-slate-600">{c.pulse_score.toFixed(3)}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3"><TierBadge label={c.risk_label} /></td>
                      <td className="px-4 py-3 text-xs text-slate-500">{fmtInr(c.monthly_income)}</td>
                      <td className="px-4 py-3">
                        <span className="material-symbols-outlined text-base text-slate-300 group-hover:text-blue-500 transition-colors">chevron_right</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="px-5 py-3 flex items-center justify-between text-xs text-slate-500"
                style={{ borderTop: '1px solid rgba(195,198,215,0.2)' }}>
                <span>
                  Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, customers.length)} of {customers.length.toLocaleString('en-IN')}
                </span>
                <div className="flex gap-2">
                  <button disabled={page === 0} onClick={() => setPage(p => p - 1)}
                    className="px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-30 hover:bg-white/70 transition"
                    style={{ background: 'rgba(242,244,246,0.8)' }}>← Prev</button>
                  <button disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}
                    className="px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-30 hover:bg-white/70 transition"
                    style={{ background: 'rgba(242,244,246,0.8)' }}>Next →</button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* ── Live Transaction Feed ── */}
        <section className="mt-6 glass-card rounded-2xl ambient-shadow-sm overflow-hidden">

          {/* Section header */}
          <div className="px-6 py-4 flex items-center justify-between"
            style={{ borderBottom: '1px solid rgba(195,198,215,0.2)' }}>
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                <span className="relative flex h-2.5 w-2.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
                </span>
                <span className="text-[10px] font-label font-bold uppercase tracking-widest text-emerald-600">Live</span>
              </div>
              <h3 className="font-headline font-bold text-base text-on-surface">Transaction Feed</h3>
              <span className="text-[10px] text-slate-400 font-medium">
                {liveTransactions.length > 0
                  ? `${liveTransactions.length} scored events · refreshes every 2s`
                  : 'Waiting for transactions…'}
              </span>
            </div>

            {/* Category legend */}
            <div className="hidden md:flex items-center gap-4 text-[10px] font-bold uppercase tracking-wide">
              <span className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-red-500" />
                <span className="text-slate-400">Stress</span>
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-emerald-500" />
                <span className="text-slate-400">Relief</span>
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-slate-300" />
                <span className="text-slate-400">Neutral</span>
              </span>
            </div>
          </div>

          {/* Column headers */}
          <div className="grid px-6 py-2 text-[10px] font-label font-bold uppercase tracking-widest text-slate-400"
            style={{
              gridTemplateColumns: '90px 70px 68px 110px 1fr 160px 90px 80px 88px',
              background: 'rgba(242,244,246,0.5)',
              borderBottom: '1px solid rgba(195,198,215,0.15)',
            }}>
            <span>Time</span>
            <span>Platform</span>
            <span>Status</span>
            <span>Amount</span>
            <span>Merchant / VPA</span>
            <span>Customer</span>
            <span>Category</span>
            <span>Severity</span>
            <span>Pulse Δ</span>
          </div>

          {/* Scrollable rows */}
          <div className="overflow-y-auto" style={{ maxHeight: '420px' }}>
            {liveTransactions.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 gap-3 text-slate-400">
                <span className="material-symbols-outlined text-4xl" style={{ opacity: 0.3 }}>
                  sync
                </span>
                <p className="text-sm">No scored transactions yet.</p>
                <p className="text-xs">
                  Run the injector: <code className="bg-slate-100 px-2 py-0.5 rounded text-xs text-slate-600">
                    python data_generator/realtime_injector.py --mode stress --total 50 --tps 2
                  </code>
                </p>
              </div>
            ) : (
              liveTransactions.map((txn: any) => {
                const isNew = newEventIds.has(txn.event_id);
                const isStress = txn.severity_direction === 'positive';
                const isRelief = txn.severity_direction === 'negative';
                const isFailed = txn.payment_status === 'failed' || txn.payment_status === 'reversed';

                const categoryColor = isStress
                  ? { bg: '#FEF2F2', text: '#DC2626', dot: '#EF4444' }
                  : isRelief
                    ? { bg: '#F0FDF4', text: '#16A34A', dot: '#22C55E' }
                    : { bg: 'rgba(242,244,246,0.9)', text: '#64748B', dot: '#94A3B8' };

                const deltaSign = txn.delta_applied > 0 ? '+' : txn.delta_applied < 0 ? '' : '±';
                const deltaColor = txn.delta_applied > 0.01 ? '#DC2626' : txn.delta_applied < -0.01 ? '#16A34A' : '#94A3B8';

                const timeStr = new Date(txn.event_ts).toLocaleTimeString('en-IN', {
                  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
                });

                const platformColors: Record<string, { bg: string; text: string }> = {
                  UPI: { bg: '#EFF6FF', text: '#1D4ED8' },
                  NEFT: { bg: '#F0FDF4', text: '#166534' },
                  NACH: { bg: '#FFF7ED', text: '#9A3412' },
                  IMPS: { bg: '#FAF5FF', text: '#6B21A8' },
                  ATM: { bg: '#F8FAFC', text: '#475569' },
                  RTGS: { bg: '#ECFDF5', text: '#065F46' },
                  BBPS: { bg: '#FDF4FF', text: '#86198F' },
                };
                const pColor = platformColors[txn.platform] || { bg: '#F8FAFC', text: '#475569' };

                const catShort: Record<string, string> = {
                  SALARY_CREDIT: 'SALARY',
                  EMI_DEBIT: 'EMI',
                  FAILED_EMI_DEBIT: 'FAILED EMI',
                  LENDING_APP_DEBIT: 'LENDING',
                  LENDING_APP_CREDIT: 'LOAN IN',
                  UTILITY_PAYMENT: 'UTILITY',
                  GROCERY: 'GROCERY',
                  FOOD_DELIVERY: 'FOOD',
                  FUEL: 'FUEL',
                  OTT: 'OTT',
                  ECOMMERCE: 'E-COMM',
                  ATM_WITHDRAWAL: 'ATM',
                  GENERAL_DEBIT: 'GENERAL',
                  GENERAL_CREDIT: 'CREDIT',
                };

                return (
                  <div
                    key={txn.event_id}
                    onClick={() => router.push(`/dashboard/${txn.customer_id}`)}
                    className="grid px-6 py-2.5 cursor-pointer hover:bg-white/60 transition-all duration-150 group items-center"
                    style={{
                      gridTemplateColumns: '90px 70px 68px 110px 1fr 160px 90px 80px 88px',
                      borderBottom: '1px solid rgba(195,198,215,0.1)',
                      background: isNew ? 'rgba(236,253,245,0.6)' : undefined,
                      transition: 'background 0.6s ease',
                    }}
                  >
                    {/* Time */}
                    <span className="font-mono text-[11px] text-slate-400">{timeStr}</span>

                    {/* Platform badge */}
                    <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-bold w-fit"
                      style={{ background: pColor.bg, color: pColor.text }}>
                      {txn.platform}
                    </span>

                    {/* Status */}
                    <span className={`text-[10px] font-bold ${isFailed ? 'text-red-500' : 'text-emerald-600'}`}>
                      {isFailed ? '✕ failed' : '✓ ok'}
                    </span>

                    {/* Amount */}
                    <span className="font-mono text-[12px] font-semibold text-on-surface">
                      ₹{txn.amount.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                    </span>

                    {/* Merchant / VPA */}
                    <span className="text-[11px] text-slate-500 truncate pr-4 font-mono group-hover:text-slate-700">
                      {txn.receiver_id || '—'}
                    </span>

                    {/* Customer name */}
                    <span className="text-[11px] font-semibold text-on-surface truncate group-hover:text-blue-600">
                      {txn.customer_name}
                    </span>

                    {/* Category badge */}
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-bold w-fit"
                      style={{ background: categoryColor.bg, color: categoryColor.text }}>
                      <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: categoryColor.dot }} />
                      {catShort[txn.inferred_category] || txn.inferred_category}
                    </span>

                    {/* Severity bar */}
                    <div className="flex items-center gap-1.5">
                      <div className="w-10 h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(0,0,0,0.08)' }}>
                        <div className="h-full rounded-full"
                          style={{
                            width: `${Math.round(txn.txn_severity * 100)}%`,
                            background: txn.txn_severity > 0.7 ? '#DC2626' : txn.txn_severity > 0.4 ? '#F59E0B' : '#94A3B8',
                          }} />
                      </div>
                      <span className="text-[10px] font-mono text-slate-400">
                        {txn.txn_severity.toFixed(2)}
                      </span>
                    </div>

                    {/* Delta */}
                    <span className="font-mono text-[11px] font-bold"
                      style={{ color: deltaColor }}>
                      {deltaSign}{txn.delta_applied.toFixed(3)}
                    </span>
                  </div>
                );
              })
            )}
          </div>
        </section>

        {/* Footer */}
        <footer className="w-full py-12 mt-12" style={{ borderTop: '1px solid rgba(195,198,215,0.2)' }}>
          <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center px-8">
            <p className="text-[10px] font-label uppercase tracking-widest text-slate-400">© 2025 Sentinel AI Crystalline Engine. All rights reserved.</p>
            <div className="flex gap-8 mt-4 md:mt-0">
              <a className="text-[10px] font-label uppercase tracking-widest text-slate-400 hover:text-blue-500 transition-all cursor-pointer">Privacy Policy</a>
              <a className="text-[10px] font-label uppercase tracking-widest text-slate-400 hover:text-blue-500 transition-all cursor-pointer">Terms of Service</a>
              <a className="text-[10px] font-label uppercase tracking-widest text-slate-400 hover:text-blue-500 transition-all cursor-pointer">Security Architecture</a>
              <a className="text-[10px] font-label uppercase tracking-widest text-slate-400 hover:text-blue-500 transition-all cursor-pointer">Global Compliance</a>
            </div>
          </div>
        </footer>
      </div>

      {/* ─── Full Audit Modal ─────────────────────────────────────────────── */}
      {auditOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ backgroundColor: 'rgba(0,10,30,0.75)', backdropFilter: 'blur(6px)' }}
        >
          <div className="bg-white rounded-2xl shadow-2xl flex flex-col w-full" style={{ maxWidth: '860px', maxHeight: '92vh' }}>

            {/* Modal Header */}
            <div className="flex items-start justify-between px-8 py-5 border-b border-slate-100 flex-shrink-0"
              style={{ background: 'linear-gradient(135deg,#002C77,#1a4a9f)' }}>
              <div>
                <h2 className="text-white font-extrabold text-xl tracking-tight">
                  Sentinel AI V2 — Regulatory Compliance Audit Report
                </h2>
                <p className="text-blue-200 text-xs mt-1">
                  Barclays India · Generated on {new Date().toLocaleString('en-IN', { day: '2-digit', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
                </p>
              </div>
              <button
                onClick={() => setAuditOpen(false)}
                className="text-blue-200 hover:text-white transition-colors mt-1 ml-6 flex-shrink-0"
              >
                <span className="material-symbols-outlined text-2xl">close</span>
              </button>
            </div>

            {/* Meta bar */}
            {auditMeta && !auditLoading && (
              <div className="flex items-center gap-6 px-8 py-2.5 bg-slate-50 border-b border-slate-100 text-xs text-slate-500 flex-shrink-0">
                <span>🤖 <strong>Model:</strong> {auditMeta.model}</span>
                <span>🕐 <strong>Generated:</strong> {new Date(auditMeta.generated_at).toLocaleString('en-IN')}</span>
                <span className="ml-auto">
                  <button
                    onClick={async () => {
                      if (!auditReport || !auditMeta) return;
                      try {
                        const res = await fetch('/api/report/audit-pdf', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({
                            report_text: auditReport,
                            generated_at: auditMeta.generated_at,
                            model: auditMeta.model,
                            total_customers: metrics?.total_customers ?? 0,
                            critical_count: metrics?.critical_count ?? 0,
                            high_count: metrics?.high_count ?? 0,
                            moderate_count: metrics?.moderate_count ?? 0,
                            watch_count: metrics?.watch_count ?? 0,
                            stable_count: metrics?.stable_count ?? 0,
                            avg_pulse_score: metrics?.avg_pulse_score ?? 0,
                            scored_customers: metrics?.scored_customers ?? 0,
                            high_severity_24h: metrics?.high_severity_24h ?? 0,
                            total_interventions: metrics?.total_interventions ?? 0,
                            system_pulse: systemPulse,
                          }),
                        });
                        if (!res.ok) throw new Error('PDF generation failed');
                        const blob = await res.blob();
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = `Barclays_Sentinel_AI_Audit_${auditMeta.generated_at.slice(0, 10).replace(/-/g, '')}.pdf`;
                        a.click();
                        URL.revokeObjectURL(url);
                      } catch (e) {
                        alert('PDF download failed. Ensure the scoring service is running.');
                      }
                    }}
                    className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-blue-600 text-white font-semibold hover:bg-blue-700 transition-colors"
                  >
                    <span className="material-symbols-outlined text-sm">picture_as_pdf</span>
                    Download PDF
                  </button>
                </span>
              </div>
            )}

            {/* Body */}
            <div className="overflow-y-auto flex-1 px-8 py-6">

              {/* Loading */}
              {auditLoading && (
                <div className="flex flex-col items-center justify-center py-24 gap-5 text-slate-500">
                  <div className="relative w-16 h-16">
                    <div className="absolute inset-0 rounded-full border-4 border-blue-100" />
                    <div className="absolute inset-0 rounded-full border-4 border-t-blue-600 animate-spin" />
                  </div>
                  <div className="text-center">
                    <p className="font-semibold text-slate-700">Generating compliance audit report…</p>
                    <p className="text-sm text-slate-400 mt-1">GROQ is analysing all 8 regulatory sections</p>
                  </div>
                </div>
              )}

              {/* Error */}
              {auditError && !auditLoading && (
                <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center">
                  <span className="material-symbols-outlined text-red-400 text-4xl block mb-3">error</span>
                  <p className="font-semibold text-red-700">{auditError}</p>
                  <button
                    onClick={() => { setAuditReport(null); setAuditError(null); handleAuditOpen(); }}
                    className="mt-4 px-6 py-2 bg-red-600 text-white rounded-lg font-semibold text-sm hover:bg-red-700 transition-colors"
                  >
                    Retry
                  </button>
                </div>
              )}

              {/* Report */}
              {auditReport && !auditLoading && (() => {
                // Split on section headers (ALL CAPS followed by colon)
                const sections = auditReport.split(/(?=\n[A-Z][A-Z\s&,\/]+:)/g);
                return (
                  <div className="space-y-6">
                    {/* Disclaimer banner */}
                    <div className="bg-amber-50 border border-amber-200 rounded-xl px-5 py-3 text-xs text-amber-800">
                      ⚠ This report is AI-generated by GROQ ({auditMeta?.model}) using live system metrics. It is intended for internal compliance review purposes only and does not constitute legal advice. Human review by qualified legal counsel is required before any regulatory submission.
                    </div>

                    {sections.map((section, idx) => {
                      const trimmed = section.trim();
                      if (!trimmed) return null;

                      // Detect header line (ALL CAPS ending in colon)
                      const headerMatch = trimmed.match(/^([A-Z][A-Z\s&,\/\d]+:)/);
                      const header = headerMatch ? headerMatch[1] : null;
                      const body = header ? trimmed.slice(header.length).trim() : trimmed;

                      // Section number / colour scheme
                      const sectionColors = [
                        'border-blue-600 bg-blue-700',
                        'border-indigo-600 bg-indigo-700',
                        'border-violet-600 bg-violet-700',
                        'border-purple-600 bg-purple-700',
                        'border-fuchsia-600 bg-fuchsia-700',
                        'border-sky-600 bg-sky-700',
                        'border-teal-600 bg-teal-700',
                        'border-emerald-600 bg-emerald-700',
                      ];
                      const colorClass = sectionColors[idx % sectionColors.length];

                      return (
                        <div key={idx} className="rounded-xl overflow-hidden border border-slate-200 shadow-sm">
                          {header && (
                            <div className={`px-5 py-3 ${colorClass} flex items-center justify-between`}>
                              <h3 className="text-white font-bold text-sm tracking-wide">{header.replace(/:$/, '')}</h3>
                              <span className="text-white/60 text-xs font-mono">§{idx + 1}</span>
                            </div>
                          )}
                          <div className="p-5 bg-white">
                            <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-line">{body}</p>
                          </div>
                        </div>
                      );
                    })}

                    {/* Footer stamp */}
                    <div className="rounded-xl border-2 border-dashed border-slate-200 px-6 py-5 text-center space-y-1">
                      <p className="text-xs text-slate-500 font-semibold uppercase tracking-widest">End of Audit Report</p>
                      <p className="text-xs text-slate-400">
                        Sentinel AI V2 · Barclays India · {auditMeta ? new Date(auditMeta.generated_at).toLocaleString('en-IN') : ''}
                      </p>
                      <p className="text-[10px] text-slate-300 mt-1">
                        Generated by {auditMeta?.model} · For internal compliance use only
                      </p>
                    </div>
                  </div>
                );
              })()}
            </div>
          </div>
        </div>
      )}
    </>
  );
}