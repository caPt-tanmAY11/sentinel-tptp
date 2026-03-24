'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
         AreaChart, Area, XAxis, YAxis, CartesianGrid } from 'recharts';
import { sentinelApi } from '@/lib/api';
import { useAuthStore } from '@/lib/authStore';

// ── Tier config ───────────────────────────────────────────────────────────────
const TIER_CFG: Record<string, { color: string; bg: string; dot: string }> = {
  CRITICAL: { color: '#DC2626', bg: '#FEF2F2', dot: '#DC2626' },
  HIGH:     { color: '#EA580C', bg: '#FFF7ED', dot: '#EA580C' },
  MODERATE: { color: '#D97706', bg: '#FFFBEB', dot: '#D97706' },
  WATCH:    { color: '#CA8A04', bg: '#FEFCE8', dot: '#CA8A04' },
  STABLE:   { color: '#16A34A', bg: '#F0FDF4', dot: '#16A34A' },
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

// ── Sidebar nav item ──────────────────────────────────────────────────────────
function NavItem({ icon, label, active, onClick }: {
  icon: string; label: string; active?: boolean; onClick?: () => void;
}) {
  return (
    <button onClick={onClick}
      className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm transition-all duration-200 ${
        active
          ? 'bg-white/80 text-blue-700 font-bold ambient-shadow-sm'
          : 'text-slate-500 hover:bg-white/50 hover:translate-x-0.5'
      }`}>
      <span className="material-symbols-outlined text-xl"
        style={{ fontVariationSettings: active ? "'FILL' 1" : "'FILL' 0" }}>
        {icon}
      </span>
      <span className="font-label">{label}</span>
    </button>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function DashboardPage() {
  const router    = useRouter();
  const logout    = useAuthStore(s => s.logout);
  const fullName  = useAuthStore(s => s.fullName);

  const [search,     setSearch]     = useState('');
  const [filterTier, setFilterTier] = useState('all');
  const [page,       setPage]       = useState(0);
  const [chartRange, setChartRange] = useState<'Live' | '1W' | '1M'>('Live');
  const PAGE_SIZE = 50;

  const { data: metrics, isLoading: metricsLoading, refetch: refetchMetrics } = useQuery({
    queryKey:        ['portfolio-metrics'],
    queryFn:         () => sentinelApi.getPortfolioMetrics().then(r => r.data),
    refetchInterval: 30_000,
  });

  const { data: custData, isLoading: custsLoading } = useQuery({
    queryKey:        ['customers', filterTier, search],
    queryFn:         () => sentinelApi.getCustomers({
      risk_label: filterTier === 'all' ? undefined : filterTier,
      search:     search || undefined,
      limit:      1500,
    }).then(r => r.data),
    refetchInterval: 30_000,
  });

  const { data: highRiskData } = useQuery({
    queryKey: ['high-risk'],
    queryFn:  () => sentinelApi.getHighRisk(0.55, 20).then(r => r.data),
    refetchInterval: 30_000,
  });

  const customers: any[] = custData?.customers || [];
  const totalPages = Math.ceil(customers.length / PAGE_SIZE);
  const pageSlice  = customers.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const pieData = metrics ? [
    { name: 'Critical', value: metrics.critical_count, fill: '#DC2626' },
    { name: 'High',     value: metrics.high_count,     fill: '#EA580C' },
    { name: 'Moderate', value: metrics.moderate_count, fill: '#D97706' },
    { name: 'Watch',    value: metrics.watch_count,     fill: '#CA8A04' },
    { name: 'Stable',  value: metrics.stable_count,    fill: '#16A34A' },
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

  const handleLogout = () => { logout(); router.push('/login'); };

  // Pulse ring SVG
  const pulseOffset = 552.92 - (systemPulse / 100) * 552.92;

  return (
    <div className="flex min-h-screen crystalline-bg">

      {/* ── Sidebar ── */}
      <aside className="sidebar-glass h-screen w-64 fixed left-0 top-0 z-40 flex flex-col p-4 gap-2"
        style={{ background: 'linear-gradient(to bottom, rgba(247,249,251,0.5), rgba(242,244,246,0.5))' }}>
        {/* Brand */}
        <div className="flex items-center gap-3 px-2 mb-8 mt-2">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center text-white"
            style={{ background: 'linear-gradient(135deg, #2b4bb9, #4865d3)' }}>
            <span className="material-symbols-outlined text-xl"
              style={{ fontVariationSettings: "'FILL' 1" }}>security</span>
          </div>
          <div>
            <h1 className="font-headline font-extrabold tracking-tighter text-blue-800 text-lg leading-tight">Sentinel AI</h1>
            <p className="text-[10px] font-label uppercase tracking-widest text-slate-400">Institutional Risk</p>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 space-y-1">
          <NavItem icon="dashboard"   label="Overview"       active />
          <NavItem icon="security"    label="Risk Monitoring" />
          <NavItem icon="insights"    label="Pulse Scores"   />
          <NavItem icon="bolt"        label="Interventions"  />
          <NavItem icon="assessment"  label="Reports"        />
        </nav>

        {/* System status */}
        <div className="pt-4 space-y-1" style={{ borderTop: '1px solid rgba(195,198,215,0.2)' }}>
          <div className="px-4 py-2">
            <div className="flex items-center gap-2 text-[10px] font-bold text-[#005a82] bg-[#e4f2ff] px-2.5 py-1 rounded-full w-fit">
              <span className="w-1.5 h-1.5 rounded-full bg-[#005a82] animate-pulse" />
              System Status: Normal
            </div>
          </div>
          <NavItem icon="help"   label="Support" />
          <button onClick={handleLogout}
            className="w-full flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm text-slate-500 hover:bg-white/50 transition-all">
            <span className="material-symbols-outlined text-xl">logout</span>
            <span className="font-label">Sign Out</span>
          </button>
        </div>

        {/* User */}
        <div className="flex items-center gap-3 px-2 pt-3 mt-1" style={{ borderTop: '1px solid rgba(195,198,215,0.2)' }}>
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-400 to-blue-700 flex items-center justify-center text-white text-xs font-bold">
            {fullName?.[0] ?? 'A'}
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-on-surface truncate">{fullName}</p>
            <p className="text-[10px] text-slate-400">Credit Officer</p>
          </div>
        </div>
      </aside>

      {/* ── Main Content ── */}
      <main className="ml-64 flex-1 p-8">

        {/* Top App Bar */}
        <header className="flex justify-between items-center mb-10">
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
              <button className="flex-1 py-3 rounded-xl font-bold text-sm shadow-lg transition-opacity hover:opacity-90 text-white"
                style={{ background: 'linear-gradient(135deg, #2b4bb9, #4865d3)', boxShadow: '0 8px 24px rgba(43,75,185,0.2)' }}>
                Full Audit
              </button>
              <button className="px-4 py-3 rounded-xl text-on-surface font-bold text-sm hover:bg-white transition-colors"
                style={{ background: 'rgba(242,244,246,0.9)' }}>
                <span className="material-symbols-outlined text-xl">share</span>
              </button>
            </div>
          </div>

          {/* ─── Behavioral Drift Analysis (col-span-8) ─── */}
          <div className="col-span-12 lg:col-span-8 glass-card rounded-2xl p-8 ambient-shadow-sm">
            <div className="flex justify-between items-start mb-8">
              <div>
                <h3 className="font-headline font-bold text-lg text-on-surface">Behavioral Drift Analysis</h3>
                <p className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Temporal variance monitoring</p>
              </div>
              <div className="flex p-1 rounded-lg" style={{ background: 'rgba(242,244,246,0.8)' }}>
                {(['Live', '1W', '1M'] as const).map(range => (
                  <button key={range} onClick={() => setChartRange(range)}
                    className={`px-3 py-1 text-xs font-bold rounded-md transition-all ${
                      chartRange === range ? 'bg-white shadow-sm text-blue-700' : 'text-slate-500'
                    }`}>
                    {range}
                  </button>
                ))}
              </div>
            </div>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={driftChartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                  <defs>
                    <linearGradient id="driftGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#2b4bb9" stopOpacity={0.2} />
                      <stop offset="100%" stopColor="#2b4bb9" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.04)" />
                  <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#94A3B8' }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: '#94A3B8' }} axisLine={false} tickLine={false} width={32} />
                  <Tooltip
                    contentStyle={{ borderRadius: 12, border: 'none', background: 'rgba(255,255,255,0.95)', boxShadow: '0 4px 24px rgba(0,0,0,0.08)', fontSize: 11 }}
                    formatter={(v: any) => [`${v}%`, 'Drift']} />
                  <Area type="monotone" dataKey="drift" stroke="#2b4bb9" strokeWidth={2.5}
                    fill="url(#driftGradient)" activeDot={{ r: 5, stroke: '#2b4bb9', fill: '#2b4bb9' }} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div className="grid grid-cols-4 mt-6 gap-4 pt-6" style={{ borderTop: '1px solid rgba(242,244,246,0.8)' }}>
              {[
                { label: 'Peak Drift', value: metricsLoading ? '…' : `${((metrics?.avg_pulse_score ?? 0) * 100 + 7).toFixed(1)}%` },
                { label: 'Avg. Latency', value: '24ms' },
                { label: 'Node Count', value: metricsLoading ? '…' : (metrics?.total_customers ?? 0).toLocaleString('en-IN') },
                { label: 'Confidence', value: metricsLoading ? '…' : `${(identityPct)}%`, accent: true },
              ].map(s => (
                <div key={s.label}>
                  <div className="text-xs text-slate-400 mb-1">{s.label}</div>
                  <div className={`font-bold text-on-surface ${(s as any).accent ? 'text-[#005a82]' : ''}`}>{s.value}</div>
                </div>
              ))}
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
                { icon: 'send',  title: 'Empathetic Outreach',     sub: 'Automated SMS Cluster' },
                { icon: 'event', title: 'Schedule Human Review',   sub: 'Tier 2 Analyst Alert' },
                { icon: 'block', title: 'Limit Credit Velocity',   sub: 'Temporary Soft Cap' },
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
            <div className="px-5 py-4 flex flex-wrap gap-3 items-center">
              <h3 className="font-headline font-bold text-base text-on-surface flex-1 min-w-0">Customer Portfolio</h3>
              <div className="flex gap-1.5 flex-wrap">
                {['all','CRITICAL','HIGH','MODERATE','WATCH','STABLE'].map(tier => (
                  <button key={tier}
                    onClick={() => { setFilterTier(tier); setPage(0); }}
                    className={`px-3 py-1.5 rounded-lg text-[11px] font-bold transition-all ${
                      filterTier === tier
                        ? 'bg-blue-600 text-white shadow-sm shadow-blue-500/20'
                        : 'text-slate-500 hover:bg-white/70'
                    }`}
                    style={{ background: filterTier === tier ? undefined : 'rgba(242,244,246,0.8)' }}>
                    {tier === 'all' ? 'All' : tier}
                  </button>
                ))}
              </div>
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
      </main>
    </div>
  );
}