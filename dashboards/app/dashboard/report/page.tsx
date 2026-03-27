'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { sentinelApi } from '@/lib/api';

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, { bg: string; text: string; dot: string }> = {
    STABLE:  { bg: '#F0FDF4', text: '#16A34A', dot: '#16A34A' },
    WATCH:   { bg: '#FEFCE8', text: '#CA8A04', dot: '#CA8A04' },
    RETRAIN: { bg: '#FEF2F2', text: '#DC2626', dot: '#DC2626' },
    ALERT:   { bg: '#FEF2F2', text: '#DC2626', dot: '#DC2626' },
  };
  const cfg = colors[status] || colors.STABLE;
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold"
      style={{ background: cfg.bg, color: cfg.text }}>
      <span className="w-2 h-2 rounded-full" style={{ background: cfg.dot }} />
      {status}
    </span>
  );
}

function EmptyState({ title, message }: { title: string; message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-12 h-12 rounded-full bg-blue-100 flex items-center justify-center mb-4">
        <span className="material-symbols-outlined text-2xl text-blue-500">info</span>
      </div>
      <h3 className="font-bold text-gray-700 mb-1">{title}</h3>
      <p className="text-sm text-gray-500 max-w-xs">{message}</p>
    </div>
  );
}

export default function ReportsPage() {
  const [activeTab, setActiveTab] = useState<'psi' | 'air' | 'audit'>('psi');
  const [auditCustomerId, setAuditCustomerId] = useState<string>('');

  // PSI/AIR monitoring data
  const { data: monitoringData, isLoading: monitoringLoading, isFetching } = useQuery({
    queryKey: ['psi-air-monitoring'],
    queryFn: () => sentinelApi.getPsiAirMonitoring().then(r => r.data),
    refetchInterval: 60_000,
  });

  // Audit trail data
  const { data: auditData, isLoading: auditLoading } = useQuery({
    queryKey: ['audit-trail', auditCustomerId],
    queryFn: () => sentinelApi.getFullAuditTrail(auditCustomerId || undefined, 200).then(r => r.data),
    enabled: activeTab === 'audit',
    refetchInterval: 30_000,
  });

  // PSI Chart Data
  const psi = monitoringData?.psi || [];
  const psiChartData = psi
    .sort((a: any, b: any) => b.psi_value - a.psi_value)
    .slice(0, 12)
    .map((item: any) => ({
      name: item.feature_name.length > 18 ? item.feature_name.substring(0, 15) + '...' : item.feature_name,
      value: parseFloat(item.psi_value.toFixed(4)),
      status: item.psi_status,
    }));

  // AIR Chart Data
  const air = monitoringData?.air || [];
  const airChartData = air.map((item: any) => ({
    name: item.air_group,
    value: parseFloat((item.air_value).toFixed(3)),
    status: item.air_status,
  }));

  // Summary stats
  const psiStats = {
    total: psi.length,
    stable: psi.filter((p: any) => p.psi_status === 'STABLE').length,
    watch: psi.filter((p: any) => p.psi_status === 'WATCH').length,
    retrain: psi.filter((p: any) => p.psi_status === 'RETRAIN').length,
  };

  const airStats = {
    total: air.length,
    stable: air.filter((a: any) => a.air_status === 'STABLE').length,
    alert: air.filter((a: any) => a.air_status === 'ALERT').length,
  };

  return (
    <main className="p-8 bg-white min-h-screenn">
      <div className="max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-10">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-5xl font-headline font-extrabold text-gray-900 mb-2">Reports & Monitoring</h1>
            <p className="text-gray-600 text-sm">Real-time drift detection, fairness audits, and transaction audit trail</p>
          </div>
          {isFetching && (
            <div className="text-sm text-gray-600 flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
              Syncing data...
            </div>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-8 border-b border-gray-200">
        {(['psi', 'air', 'audit'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-6 py-3 font-medium text-sm transition-all duration-200 border-b-2 ${
              activeTab === tab
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}>
            {tab === 'psi' && '📊 PSI Drift Analysis'}
            {tab === 'air' && '⚖️ AIR Fairness Audit'}
            {tab === 'audit' && '📋 Transaction Trail'}
          </button>
        ))}
      </div>

      {/* PSI Tab */}
      {activeTab === 'psi' && (
        <div className="space-y-6">
          {/* Stats Grid */}
          <div className="grid grid-cols-4 gap-4">
            <div className="p-6 rounded-xl bg-gradient-to-br from-blue-50 to-cyan-50 border border-blue-200 shadow-sm">
              <p className="text-xs font-bold text-blue-600 uppercase tracking-wide mb-3">Total Features</p>
              <p className="text-4xl font-extrabold text-blue-900">{psiStats.total}</p>
              <p className="text-xs text-blue-600 mt-2">Monitored for drift</p>
            </div>
            <div className="p-6 rounded-xl bg-gradient-to-br from-green-50 to-emerald-50 border border-green-200 shadow-sm">
              <p className="text-xs font-bold text-green-700 uppercase tracking-wide mb-3">✓ Stable</p>
              <p className="text-4xl font-extrabold text-green-700">{psiStats.stable}</p>
              <p className="text-xs text-green-600 mt-2">No drift detected</p>
            </div>
            <div className="p-6 rounded-xl bg-gradient-to-br from-amber-50 to-yellow-50 border border-amber-200 shadow-sm">
              <p className="text-xs font-bold text-amber-700 uppercase tracking-wide mb-3">⚠ Watch</p>
              <p className="text-4xl font-extrabold text-amber-700">{psiStats.watch}</p>
              <p className="text-xs text-amber-600 mt-2">Monitor closely</p>
            </div>
            <div className="p-6 rounded-xl bg-gradient-to-br from-red-50 to-orange-50 border border-red-200 shadow-sm">
              <p className="text-xs font-bold text-red-700 uppercase tracking-wide mb-3">🔴 Retrain Needed</p>
              <p className="text-4xl font-extrabold text-red-700">{psiStats.retrain}</p>
              <p className="text-xs text-red-600 mt-2">Action required</p>
            </div>
          </div>

          {/* PSI Chart */}
          {psiChartData.length > 0 ? (
            <div className="p-8 rounded-xl bg-gradient-to-br from-blue-50 to-cyan-50 border border-blue-200 shadow-sm">
              <h2 className="text-xl font-bold text-gray-900 mb-6">Top 12 Features by PSI Value</h2>
              <ResponsiveContainer width="100%" height={350}>
                <BarChart data={psiChartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.05)" />
                  <XAxis dataKey="name" tick={{ fontSize: 12, fill: '#666666' }} angle={-45} textAnchor="end" height={100} />
                  <YAxis tick={{ fontSize: 12, fill: '#666666' }} />
                  <Tooltip
                    contentStyle={{ background: '#ffffff', border: '1px solid #ddd', borderRadius: '8px', color: '#333' }}
                    formatter={(value: any) => [value.toFixed(6), 'PSI']}
                    labelStyle={{ color: '#333' }}
                  />
                  <Bar dataKey="value" fill="#2563eb" radius={[8, 8, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <EmptyState title="No Data Available" message="Run monitoring: python run_pipeline.py --step monitor" />
          )}

          {/* PSI Table */}
          <div className="p-8 rounded-xl bg-white border border-gray-200 shadow-sm overflow-hidden">
            <h2 className="text-xl font-bold text-gray-900 mb-6">All Monitored Features</h2>
            {monitoringLoading ? (
              <div className="text-center py-12 text-gray-500">Loading...</div>
            ) : psi.length === 0 ? (
              <EmptyState title="No PSI Data" message="No features are being monitored. Run baselines and monitor steps." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 bg-gray-50">
                      <th className="text-left py-4 px-4 font-bold text-xs text-gray-700 uppercase">Feature Name</th>
                      <th className="text-right py-4 px-4 font-bold text-xs text-gray-700 uppercase">PSI Value</th>
                      <th className="text-center py-4 px-4 font-bold text-xs text-gray-700 uppercase">Status</th>
                      <th className="text-left py-4 px-4 font-bold text-xs text-gray-700 uppercase">Details</th>
                      <th className="text-left py-4 px-4 font-bold text-xs text-gray-700 uppercase">Monitored At</th>
                    </tr>
                  </thead>
                  <tbody>
                    {psi.map((item: any, i: number) => (
                      <tr key={i} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                        <td className="py-4 px-4 font-mono text-xs text-gray-700">{item.feature_name}</td>
                        <td className="py-4 px-4 text-right font-bold text-gray-900">
                          {(item.psi_value).toFixed(6)}
                        </td>
                        <td className="py-4 px-4 text-center">
                          <StatusBadge status={item.psi_status} />
                        </td>
                        <td className="py-4 px-4 text-xs text-gray-600">
                          {item.details?.baseline_n && item.details?.current_n ? (
                            <span>n={item.details.baseline_n}→{item.details.current_n}</span>
                          ) : 'N/A'}
                        </td>
                        <td className="py-4 px-4 text-xs text-gray-500">
                          {new Date(item.created_at).toLocaleString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Reference */}
          <div className="p-6 rounded-xl bg-blue-50 border border-blue-200">
            <h3 className="font-bold text-blue-900 mb-3">📚 How to Read PSI</h3>
            <div className="grid grid-cols-3 gap-6 text-sm text-blue-900">
              <div className="flex gap-3">
                <span className="text-lg">✓</span>
                <div><span className="font-bold">STABLE</span><br/>PSI &lt; 0.10 (no action)</div>
              </div>
              <div className="flex gap-3">
                <span className="text-lg">⚠</span>
                <div><span className="font-bold">WATCH</span><br/>PSI 0.10–0.25 (monitor)</div>
              </div>
              <div className="flex gap-3">
                <span className="text-lg">🔴</span>
                <div><span className="font-bold">RETRAIN</span><br/>PSI &gt; 0.25 (retrain)</div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* AIR Tab */}
      {activeTab === 'air' && (
        <div className="space-y-6">
          {/* Stats Grid */}
          <div className="grid grid-cols-3 gap-4">
            <div className="p-6 rounded-xl bg-gradient-to-br from-purple-50 to-pink-50 border border-purple-200 shadow-sm">
              <p className="text-xs font-bold text-purple-700 uppercase tracking-wide mb-3">Total Groups</p>
              <p className="text-4xl font-extrabold text-purple-900">{airStats.total}</p>
              <p className="text-xs text-purple-600 mt-2">Audited for fairness</p>
            </div>
            <div className="p-6 rounded-xl bg-gradient-to-br from-green-50 to-emerald-50 border border-green-200 shadow-sm">
              <p className="text-xs font-bold text-green-700 uppercase tracking-wide mb-3">✓ Fair</p>
              <p className="text-4xl font-extrabold text-green-700">{airStats.stable}</p>
              <p className="text-xs text-green-600 mt-2">0.80 ≤ AIR ≤ 1.25</p>
            </div>
            <div className="p-6 rounded-xl bg-gradient-to-br from-orange-50 to-red-50 border border-red-200 shadow-sm">
              <p className="text-xs font-bold text-red-700 uppercase tracking-wide mb-3">⚠ Unfair</p>
              <p className="text-4xl font-extrabold text-red-700">{airStats.alert}</p>
              <p className="text-xs text-red-600 mt-2">Needs review</p>
            </div>
          </div>

          {/* AIR Chart */}
          {airChartData.length > 0 ? (
            <div className="p-8 rounded-xl bg-gradient-to-br from-purple-50 to-pink-50 border border-purple-200 shadow-sm">
              <h2 className="text-xl font-bold text-gray-900 mb-6">AIR by Demographic Group</h2>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={airChartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.05)" />
                  <XAxis dataKey="name" tick={{ fontSize: 12, fill: '#666666' }} />
                  <YAxis tick={{ fontSize: 12, fill: '#666666' }} />
                  <Tooltip
                    contentStyle={{ background: '#ffffff', border: '1px solid #ddd', borderRadius: '8px', color: '#333' }}
                    formatter={(value: any) => value.toFixed(3)}
                    labelStyle={{ color: '#333' }}
                  />
                  <Bar dataKey="value" fill="#9333ea" radius={[8, 8, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <EmptyState title="No Data Available" message="Run monitoring to generate AIR data" />
          )}

          {/* AIR Table */}
          <div className="p-8 rounded-xl bg-white border border-gray-200 shadow-sm overflow-hidden">
            <h2 className="text-xl font-bold text-gray-900 mb-6">Fairness Audit by Group</h2>
            {monitoringLoading ? (
              <div className="text-center py-12 text-gray-500">Loading...</div>
            ) : air.length === 0 ? (
              <EmptyState title="No AIR Data" message="No fairness audits have been run yet" />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 bg-gray-50">
                      <th className="text-left py-4 px-4 font-bold text-xs text-gray-700 uppercase">Group</th>
                      <th className="text-right py-4 px-4 font-bold text-xs text-gray-700 uppercase">AIR Value</th>
                      <th className="text-center py-4 px-4 font-bold text-xs text-gray-700 uppercase">Status</th>
                      <th className="text-left py-4 px-4 font-bold text-xs text-gray-700 uppercase">Assessment</th>
                      <th className="text-left py-4 px-4 font-bold text-xs text-gray-700 uppercase">Monitored At</th>
                    </tr>
                  </thead>
                  <tbody>
                    {air.map((item: any, i: number) => {
                      const val = item.air_value;
                      let assessment = '';
                      if (val < 0.80) assessment = 'Underrepresented';
                      else if (val > 1.25) assessment = 'Overrepresented';
                      else assessment = 'Fair Distribution';
                      return (
                        <tr key={i} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                          <td className="py-4 px-4 font-semibold text-gray-900">{item.air_group}</td>
                          <td className="py-4 px-4 text-right font-bold text-gray-900">
                            {val.toFixed(4)}
                          </td>
                          <td className="py-4 px-4 text-center">
                            <StatusBadge status={item.air_status} />
                          </td>
                          <td className="py-4 px-4 text-xs text-gray-600">{assessment}</td>
                          <td className="py-4 px-4 text-xs text-gray-500">
                            {new Date(item.created_at).toLocaleString()}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Reference */}
          <div className="p-6 rounded-xl bg-purple-50 border border-purple-200">
            <h3 className="font-bold text-purple-900 mb-3">⚖️ How to Read AIR (Adverse Impact Ratio)</h3>
            <div className="text-sm text-purple-900 space-y-2">
              <p>AIR = (% High Risk in Group) / (% High Risk in Reference Group)</p>
              <div className="grid grid-cols-3 gap-4 mt-4">
                <div className="p-3 rounded bg-orange-50 border border-orange-200">
                  <span className="font-bold text-orange-900">AIR &lt; 0.80</span><br/>
                  <span className="text-xs text-orange-700">Underrepresented</span>
                </div>
                <div className="p-3 rounded bg-green-50 border border-green-200">
                  <span className="font-bold text-green-700">0.80–1.25</span><br/>
                  <span className="text-xs text-green-700">Fair &amp; Unbiased</span>
                </div>
                <div className="p-3 rounded bg-orange-50 border border-orange-200">
                  <span className="font-bold text-orange-900">AIR &gt; 1.25</span><br/>
                  <span className="text-xs text-orange-700">Overrepresented</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Audit Tab */}
      {activeTab === 'audit' && (
        <div className="space-y-6">
          {/* Filter */}
          <div className="p-6 rounded-xl bg-gradient-to-br from-indigo-50 to-blue-50 border border-indigo-200 shadow-sm">
            <h2 className="text-lg font-bold text-gray-900 mb-4">Filter Audit Trail</h2>
            <div className="flex gap-3">
              <input
                type="text"
                placeholder="Filter by Customer ID (leave blank for all)"
                value={auditCustomerId}
                onChange={(e) => setAuditCustomerId(e.target.value)}
                className="flex-1 px-4 py-3 rounded-lg bg-white border border-gray-300 text-gray-900 text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <button
                onClick={() => setAuditCustomerId('')}
                className="px-6 py-3 rounded-lg text-sm font-medium bg-gray-200 hover:bg-gray-300 text-gray-900 transition-colors">
                Clear
              </button>
            </div>
          </div>

          {/* Audit Table */}
          <div className="p-8 rounded-xl bg-white border border-gray-200 shadow-sm overflow-hidden">
            <h2 className="text-xl font-bold text-gray-900 mb-6">Transaction Pulse Events</h2>
            {auditLoading ? (
              <div className="text-center py-12 text-gray-500">Loading...</div>
            ) : !auditData?.audit_events || auditData.audit_events.length === 0 ? (
              <EmptyState title="No Audit Events" message="No transactions have been scored yet. Inject transactions to populate." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 bg-gray-50">
                      <th className="text-left py-4 px-4 font-bold text-xs text-gray-700 uppercase">Timestamp</th>
                      <th className="text-left py-4 px-4 font-bold text-xs text-gray-700 uppercase">Customer</th>
                      <th className="text-right py-4 px-4 font-bold text-xs text-gray-700 uppercase">Amount</th>
                      <th className="text-left py-4 px-4 font-bold text-xs text-gray-700 uppercase">Category</th>
                      <th className="text-center py-4 px-4 font-bold text-xs text-gray-700 uppercase">Direction</th>
                      <th className="text-right py-4 px-4 font-bold text-xs text-gray-700 uppercase">Severity</th>
                      <th className="text-right py-4 px-4 font-bold text-xs text-gray-700 uppercase">Δ Score</th>
                      <th className="text-right py-4 px-4 font-bold text-xs text-gray-700 uppercase">New Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {auditData?.audit_events?.map((event: any, i: number) => (
                      <tr key={i} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                        <td className="py-4 px-4 text-xs text-gray-600">
                          {new Date(event.event_ts).toLocaleTimeString()}
                        </td>
                        <td className="py-4 px-4 font-mono text-xs text-gray-700">
                          {event.customer_id.substring(0, 8)}...
                        </td>
                        <td className="py-4 px-4 text-right font-bold text-gray-900">
                          ₹{(event.amount || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                        </td>
                        <td className="py-4 px-4 text-xs font-medium text-blue-600">{event.inferred_category}</td>
                        <td className="py-4 px-4 text-center">
                          <span className={`px-2 py-1 rounded text-xs font-bold ${
                            event.severity_direction === 'positive' ? 'bg-red-100 text-red-700' :
                            event.severity_direction === 'negative' ? 'bg-green-100 text-green-700' :
                            'bg-gray-100 text-gray-700'
                          }`}>
                            {event.severity_direction === 'positive' ? '↑ Stress' :
                             event.severity_direction === 'negative' ? '↓ Relief' : '— Neutral'}
                          </span>
                        </td>
                        <td className="py-4 px-4 text-right font-bold text-gray-900">
                          {(event.txn_severity * 100).toFixed(0)}%
                        </td>
                        <td className="py-4 px-4 text-right font-bold">
                          <span className={event.delta_applied >= 0 ? 'text-red-600' : 'text-green-600'}>
                            {event.delta_applied >= 0 ? '+' : ''}{(event.delta_applied * 100).toFixed(2)}%
                          </span>
                        </td>
                        <td className="py-4 px-4 text-right font-bold text-gray-900">
                          {(event.pulse_score_after * 100).toFixed(1)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
      </div>
    </main>
  );
}
