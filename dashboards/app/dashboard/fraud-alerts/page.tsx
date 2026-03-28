'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { sentinelApi } from '@/lib/api';
import { useRouter } from 'next/navigation';

export default function FraudAlertsPage() {
  const router = useRouter();
  const [search, setSearch] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['portfolio-fraud-alerts'],
    queryFn: () => sentinelApi.getFraudAlerts('OPEN', 100).then(res => res.data),
    refetchInterval: 15000,
  });

  const alerts = data?.fraud_alerts || [];

  const filtered = alerts.filter((a: any) =>
    (a.first_name + ' ' + a.last_name)?.toLowerCase().includes(search.toLowerCase()) ||
    a.customer_id?.toLowerCase().includes(search.toLowerCase()) ||
    a.fraud_reason?.toLowerCase().includes(search.toLowerCase())
  );

  const openCount = alerts.filter((a: any) => a.status === 'OPEN').length;
  const reviewedCount = alerts.filter((a: any) => a.status === 'REVIEWED' || a.status === 'CONFIRMED' || a.status === 'DISMISSED').length;

  const fmtInr = (v: number) =>
    new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v);

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">

      {/* Page Header */}
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">Fraud Detection Queue</h1>
        <p className="text-sm text-slate-500 mt-1">
          Review probable fault and fraudulent transactions flagged by the real-time detection engine.
        </p>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white p-6 rounded-2xl border shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-slate-100 text-slate-600 flex items-center justify-center">
            <span className="material-symbols-outlined text-2xl">security</span>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-500">Total Flagged</div>
            <div className="text-2xl font-black text-slate-900">
              {isLoading ? '...' : alerts.length}
            </div>
          </div>
        </div>

        <div className="bg-white p-6 rounded-2xl border shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-red-100 text-red-600 flex items-center justify-center">
            <span className="material-symbols-outlined text-2xl">warning</span>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-500">Action Required</div>
            <div className="text-2xl font-black text-slate-900">
              {isLoading ? '...' : openCount}
            </div>
          </div>
        </div>

        <div className="bg-white p-6 rounded-2xl border shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-blue-100 text-blue-600 flex items-center justify-center">
            <span className="material-symbols-outlined text-2xl">fact_check</span>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-500">Reviewed / Closed</div>
            <div className="text-2xl font-black text-slate-900">
              {isLoading ? '...' : reviewedCount}
            </div>
          </div>
        </div>
      </div>

      {/* Alerts Table */}
      <div className="bg-white rounded-2xl border shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b bg-slate-50/50 flex items-center justify-between gap-4">
          <div>
            <h2 className="font-bold text-slate-800">Queue</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Refreshes every 15 seconds. High severity events are at the top.
            </p>
          </div>
          {/* Search */}
          <div className="relative">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-lg">
              search
            </span>
            <input
              type="text"
              placeholder="Search customers or reasons..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="pl-9 pr-4 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 w-72"
            />
          </div>
        </div>

        {isLoading ? (
          <div className="p-12 text-center text-slate-400">Loading alerts data...</div>
        ) : filtered.length === 0 ? (
          <div className="p-12 text-center text-slate-400">
            <span className="material-symbols-outlined text-4xl mb-2 opacity-40 block">
              task_alt
            </span>
            <p className="font-medium">
              {search ? 'No open alerts match your search.' : 'Great job! The fraud detection queue is empty.'}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 border-b text-slate-500 font-medium">
                <tr>
                  <th className="px-6 py-4 whitespace-nowrap">Customer</th>
                  <th className="px-6 py-4 whitespace-nowrap">Transaction</th>
                  <th className="px-6 py-4 whitespace-nowrap">Fraud Score</th>
                  <th className="px-6 py-4">Triggered Signals</th>
                  <th className="px-6 py-4 whitespace-nowrap">Status</th>
                  <th className="px-6 py-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filtered.map((a: any) => (
                  <tr key={a.alert_id} className="hover:bg-slate-50/50 transition-colors">

                    {/* Customer */}
                    <td className="px-6 py-4 max-w-[200px]">
                      <div className="font-semibold text-slate-800 truncate" title={`${a.first_name} ${a.last_name}`}>{a.first_name} {a.last_name}</div>
                      <div className="text-[10px] font-mono text-slate-400 mt-0.5 truncate" title={a.customer_id}>{a.customer_id}</div>
                    </td>

                    {/* Transaction Details */}
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="font-bold text-slate-800">{fmtInr(a.txn_amount)}</div>
                      <div className="text-xs text-slate-500 mt-0.5">{a.platform} &middot; {a.currency}</div>
                    </td>

                    {/* Score */}
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className={`font-mono font-bold ${a.fraud_score >= 0.75 ? 'text-red-600' : 'text-orange-600'}`}>
                        {a.fraud_score.toFixed(3)}
                      </div>
                    </td>

                    {/* Signals */}
                    <td className="px-6 py-4">
                      <div className="flex gap-1.5 flex-wrap">
                        {a.signal_international && <span className="text-[10px] px-2 py-0.5 bg-red-100 text-red-700 rounded-md font-bold border border-red-200 whitespace-nowrap">Intl Txn</span>}
                        {a.signal_amount_spike && <span className="text-[10px] px-2 py-0.5 bg-orange-100 text-orange-700 rounded-md font-bold border border-orange-200 whitespace-nowrap">Amount Spike</span>}
                        {a.signal_freq_spike && <span className="text-[10px] px-2 py-0.5 bg-amber-100 text-amber-700 rounded-md font-bold border border-amber-200 whitespace-nowrap">Freq Spike</span>}
                      </div>
                      <div className="text-xs text-slate-500 mt-1.5 line-clamp-1" title={a.fraud_reason}>
                        {a.fraud_reason}
                      </div>
                    </td>

                    {/* Status */}
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${
                          a.status === 'OPEN' ? 'bg-red-500' : 
                          a.status === 'REVIEWED' ? 'bg-blue-500' : 'bg-green-500'
                        }`} />
                        <span className={`font-semibold text-[11px] uppercase tracking-wide ${
                          a.status === 'OPEN' ? 'text-red-700' : 
                          a.status === 'REVIEWED' ? 'text-blue-700' : 'text-green-700'
                        }`}>
                          {a.status}
                        </span>
                      </div>
                    </td>

                    {/* Action */}
                    <td className="px-6 py-4 text-right">
                      <button
                        onClick={() => router.push(`/dashboard/${a.customer_id}`)}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold text-blue-700 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors border border-blue-200"
                      >
                        <span className="material-symbols-outlined text-[16px]">visibility</span>
                        Review Profile
                      </button>
                    </td>

                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
