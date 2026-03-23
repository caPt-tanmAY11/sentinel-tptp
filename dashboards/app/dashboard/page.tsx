'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';
import {
  Users, AlertTriangle, TrendingUp, Activity,
  Search, LogOut, Shield, ChevronRight, RefreshCw,
} from 'lucide-react';
import { sentinelApi } from '@/lib/api';
import { useAuthStore } from '@/lib/authStore';

// ── Tier config ───────────────────────────────────────────────────────────────
const TIER_CONFIG: Record<string, { color: string; bg: string; border: string }> = {
  CRITICAL: { color: '#DC2626', bg: '#FEF2F2', border: '#FECACA' },
  HIGH:     { color: '#EA580C', bg: '#FFF7ED', border: '#FED7AA' },
  MODERATE: { color: '#D97706', bg: '#FFFBEB', border: '#FDE68A' },
  WATCH:    { color: '#CA8A04', bg: '#FEFCE8', border: '#FEF08A' },
  STABLE:   { color: '#16A34A', bg: '#F0FDF4', border: '#BBF7D0' },
};

function TierBadge({ label }: { label: string }) {
  const cfg = TIER_CONFIG[label] || TIER_CONFIG.STABLE;
  return (
    <span className="px-2.5 py-0.5 rounded-full text-xs font-bold"
      style={{ color: cfg.color, background: cfg.bg, border: `1px solid ${cfg.border}` }}>
      {label}
    </span>
  );
}

function KPICard({ title, value, sub, icon, color }: {
  title: string; value: string | number; sub: string;
  icon: React.ReactNode; color: string;
}) {
  return (
    <div className="bg-white rounded-2xl border border-slate-100 p-5 flex gap-4 items-start shadow-sm">
      <div className="w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0"
        style={{ background: `${color}18` }}>
        <div style={{ color }}>{icon}</div>
      </div>
      <div>
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide">{title}</p>
        <p className="text-2xl font-bold text-slate-800 mt-0.5">{value}</p>
        <p className="text-xs text-slate-400 mt-0.5">{sub}</p>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function DashboardPage() {
  const router   = useRouter();
  const logout   = useAuthStore(s => s.logout);
  const fullName = useAuthStore(s => s.fullName);

  const [search,     setSearch]     = useState('');
  const [filterTier, setFilterTier] = useState('all');
  const [page,       setPage]       = useState(0);
  const PAGE_SIZE = 50;

  // Portfolio metrics (auto-refresh every 30s)
  const { data: metrics, isLoading: metricsLoading, refetch: refetchMetrics } = useQuery({
    queryKey:       ['portfolio-metrics'],
    queryFn:        () => sentinelApi.getPortfolioMetrics().then(r => r.data),
    refetchInterval: 30_000,
  });

  // Customer list
  const { data: custData, isLoading: custsLoading } = useQuery({
    queryKey:       ['customers', filterTier, search],
    queryFn:        () => sentinelApi.getCustomers({
      risk_label: filterTier === 'all' ? undefined : filterTier,
      search:     search || undefined,
      limit:      1500,
    }).then(r => r.data),
    refetchInterval: 30_000,
  });

  const customers: any[] = custData?.customers || [];
  const totalPages  = Math.ceil(customers.length / PAGE_SIZE);
  const pageSlice   = customers.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const pieData = metrics ? [
    { name: 'Critical', value: metrics.critical_count,  fill: '#DC2626' },
    { name: 'High',     value: metrics.high_count,      fill: '#EA580C' },
    { name: 'Moderate', value: metrics.moderate_count,  fill: '#D97706' },
    { name: 'Watch',    value: metrics.watch_count,     fill: '#CA8A04' },
    { name: 'Stable',   value: metrics.stable_count,    fill: '#16A34A' },
  ].filter(d => d.value > 0) : [];

  const fmtInr = (v: number) =>
    new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR',
      maximumFractionDigits: 0 }).format(v);

  const handleLogout = () => { logout(); router.push('/login'); };

  return (
    <div className="min-h-screen bg-slate-50">

      {/* Top Nav */}
      <header className="bg-white border-b border-slate-100 px-6 py-4 flex items-center justify-between sticky top-0 z-20 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ background: 'linear-gradient(135deg,#3B82F6,#6366F1)' }}>
            <Shield className="w-4 h-4 text-white" />
          </div>
          <div>
            <h1 className="text-base font-bold text-slate-800 leading-tight">Sentinel V2</h1>
            <p className="text-xs text-slate-400">Pre-Delinquency Dashboard</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-slate-500">{fullName}</span>
          <button onClick={() => refetchMetrics()}
            className="p-2 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition">
            <RefreshCw className="w-4 h-4" />
          </button>
          <button onClick={handleLogout}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-slate-500 hover:bg-slate-100 transition">
            <LogOut className="w-3.5 h-3.5" /> Logout
          </button>
        </div>
      </header>

      <main className="max-w-[1400px] mx-auto px-6 py-6 space-y-6">

        {/* KPI Row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <KPICard title="Total Customers"  icon={<Users className="w-5 h-5" />}
            value={metricsLoading ? '…' : (metrics?.total_customers ?? 0).toLocaleString('en-IN')}
            sub={`${metrics?.scored_customers ?? 0} scored`} color="#3B82F6" />
          <KPICard title="High Risk"  icon={<AlertTriangle className="w-5 h-5" />}
            value={metricsLoading ? '…' : ((metrics?.critical_count ?? 0) + (metrics?.high_count ?? 0)).toLocaleString('en-IN')}
            sub="CRITICAL + HIGH tier" color="#DC2626" />
          <KPICard title="Avg Pulse Score"  icon={<TrendingUp className="w-5 h-5" />}
            value={metricsLoading ? '…' : (metrics?.avg_pulse_score ?? 0).toFixed(3)}
            sub="Portfolio average" color="#8B5CF6" />
          <KPICard title="Alerts (24h)"  icon={<Activity className="w-5 h-5" />}
            value={metricsLoading ? '…' : (metrics?.high_severity_24h ?? 0).toLocaleString('en-IN')}
            sub="Severity ≥ 0.55" color="#EA580C" />
        </div>

        {/* Charts + Table */}
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">

          {/* Pie Chart */}
          <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-5">
            <h2 className="text-sm font-bold text-slate-700 mb-4">Risk Distribution</h2>
            {pieData.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={200}>
                  <PieChart>
                    <Pie data={pieData} cx="50%" cy="50%" innerRadius={55} outerRadius={85}
                      dataKey="value" paddingAngle={2}>
                      {pieData.map((d, i) => <Cell key={i} fill={d.fill} />)}
                    </Pie>
                    <Tooltip formatter={(v: any) => [v.toLocaleString('en-IN'), 'Customers']} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="mt-3 space-y-1.5">
                  {pieData.map(d => (
                    <div key={d.name} className="flex items-center justify-between text-xs">
                      <span className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-full" style={{ background: d.fill }} />
                        <span className="text-slate-600">{d.name}</span>
                      </span>
                      <span className="font-semibold text-slate-700">{d.value.toLocaleString('en-IN')}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="h-48 flex items-center justify-center text-slate-400 text-sm">
                No score data yet.<br/>Run{' '}
                <code className="mx-1 px-1 py-0.5 bg-slate-100 rounded text-xs">
                  --step score
                </code>
              </div>
            )}
          </div>

          {/* Customer Table */}
          <div className="lg:col-span-3 bg-white rounded-2xl border border-slate-100 shadow-sm flex flex-col">
            {/* Table header */}
            <div className="px-5 py-4 border-b border-slate-100 flex flex-wrap gap-3 items-center">
              <div className="relative flex-1 min-w-[200px]">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input placeholder="Search name or account…" value={search}
                  onChange={e => { setSearch(e.target.value); setPage(0); }}
                  className="w-full pl-9 pr-4 py-2 text-sm rounded-xl border border-slate-200 outline-none focus:ring-2 focus:ring-blue-400 bg-slate-50" />
              </div>
              <div className="flex gap-1.5 flex-wrap">
                {['all','CRITICAL','HIGH','MODERATE','WATCH','STABLE'].map(tier => (
                  <button key={tier}
                    onClick={() => { setFilterTier(tier); setPage(0); }}
                    className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
                      filterTier === tier
                        ? 'bg-blue-600 text-white shadow-sm'
                        : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
                    }`}>
                    {tier === 'all' ? 'All' : tier}
                  </button>
                ))}
              </div>
            </div>

            {/* Table body */}
            <div className="overflow-x-auto flex-1">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 border-b border-slate-100">
                  <tr>
                    {['Customer', 'Account', 'Segment', 'State', 'Pulse Score', 'Risk Tier', 'Income'].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wide whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {custsLoading ? (
                    <tr><td colSpan={8} className="text-center py-12 text-slate-400">Loading customers…</td></tr>
                  ) : pageSlice.length === 0 ? (
                    <tr><td colSpan={8} className="text-center py-12 text-slate-400">No customers found</td></tr>
                  ) : pageSlice.map((c: any) => (
                    <tr key={c.customer_id}
                      onClick={() => router.push(`/dashboard/${c.customer_id}`)}
                      className="hover:bg-blue-50 cursor-pointer transition-colors group">
                      <td className="px-4 py-3 font-medium text-slate-800 whitespace-nowrap">{c.full_name}</td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-400">{c.account_id}</td>
                      <td className="px-4 py-3 text-slate-500">{c.segment}</td>
                      <td className="px-4 py-3 text-slate-500">{c.state}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="flex-1 h-1.5 bg-slate-100 rounded-full max-w-[60px]">
                            <div className="h-full rounded-full transition-all"
                              style={{
                                width: `${Math.min(100, c.pulse_score * 100)}%`,
                                background: TIER_CONFIG[c.risk_label]?.color || '#16A34A',
                              }} />
                          </div>
                          <span className="text-xs font-mono text-slate-600">{c.pulse_score.toFixed(3)}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3"><TierBadge label={c.risk_label} /></td>
                      <td className="px-4 py-3 text-slate-500 text-xs">{fmtInr(c.monthly_income)}</td>
                      <td className="px-4 py-3">
                        <ChevronRight className="w-4 h-4 text-slate-300 group-hover:text-blue-500 transition" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="px-5 py-3 border-t border-slate-100 flex items-center justify-between text-sm text-slate-500">
                <span>
                  Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, customers.length)} of {customers.length.toLocaleString('en-IN')}
                </span>
                <div className="flex gap-2">
                  <button disabled={page === 0}
                    onClick={() => setPage(p => p - 1)}
                    className="px-3 py-1 rounded-lg border border-slate-200 disabled:opacity-40 hover:bg-slate-50 transition text-xs">
                    ← Prev
                  </button>
                  <button disabled={page >= totalPages - 1}
                    onClick={() => setPage(p => p + 1)}
                    className="px-3 py-1 rounded-lg border border-slate-200 disabled:opacity-40 hover:bg-slate-50 transition text-xs">
                    Next →
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}