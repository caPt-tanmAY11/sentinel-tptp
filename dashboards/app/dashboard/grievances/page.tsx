'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { sentinelApi } from '@/lib/api';

export default function GrievancesPage() {
  const [search, setSearch] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['grievances'],
    queryFn: () => sentinelApi.getGrievances().then(res => res.data),
    refetchInterval: 15000,
  });

  const grievances = data?.grievances || [];

  const filtered = grievances.filter((g: any) =>
    g.customer_name?.toLowerCase().includes(search.toLowerCase()) ||
    g.customer_id?.toLowerCase().includes(search.toLowerCase()) ||
    g.message?.toLowerCase().includes(search.toLowerCase())
  );

  const openCount = grievances.filter((g: any) => g.status === 'OPEN').length;

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">

      {/* Page Header */}
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">Grievances</h1>
        <p className="text-sm text-slate-500 mt-1">
          Customer queries submitted in response to risk tier alert emails.
        </p>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white p-6 rounded-2xl border shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-blue-100 text-blue-600 flex items-center justify-center">
            <span className="material-symbols-outlined text-2xl">forum</span>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-500">Total Grievances</div>
            <div className="text-2xl font-black text-slate-900">
              {isLoading ? '...' : grievances.length}
            </div>
          </div>
        </div>

        <div className="bg-white p-6 rounded-2xl border shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-orange-100 text-orange-600 flex items-center justify-center">
            <span className="material-symbols-outlined text-2xl">pending_actions</span>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-500">Open</div>
            <div className="text-2xl font-black text-slate-900">
              {isLoading ? '...' : openCount}
            </div>
          </div>
        </div>

        <div className="bg-white p-6 rounded-2xl border shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-green-100 text-green-600 flex items-center justify-center">
            <span className="material-symbols-outlined text-2xl">check_circle</span>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-500">Resolved</div>
            <div className="text-2xl font-black text-slate-900">
              {isLoading ? '...' : grievances.length - openCount}
            </div>
          </div>
        </div>
      </div>

      {/* Grievances Table */}
      <div className="bg-white rounded-2xl border shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b bg-slate-50/50 flex items-center justify-between gap-4">
          <div>
            <h2 className="font-bold text-slate-800">All Grievances</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Refreshes every 15 seconds automatically.
            </p>
          </div>
          {/* Search */}
          <div className="relative">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-lg">
              search
            </span>
            <input
              type="text"
              placeholder="Search by name, ID or message..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="pl-9 pr-4 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 w-72"
            />
          </div>
        </div>

        {isLoading ? (
          <div className="p-12 text-center text-slate-400">Loading...</div>
        ) : filtered.length === 0 ? (
          <div className="p-12 text-center text-slate-400">
            <span className="material-symbols-outlined text-4xl mb-2 opacity-40 block">
              inbox
            </span>
            <p className="font-medium">
              {search ? 'No grievances match your search.' : 'No grievances submitted yet.'}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 border-b text-slate-500 font-medium">
                <tr>
                  <th className="px-6 py-4">Customer</th>
                  <th className="px-6 py-4">Risk Tier</th>
                  <th className="px-6 py-4">Message</th>
                  <th className="px-6 py-4">Submitted At</th>
                  <th className="px-6 py-4">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filtered.map((g: any) => (
                  <tr key={g.grievance_id} className="hover:bg-slate-50/50 transition-colors">

                    {/* Customer */}
                    <td className="px-6 py-4">
                      <div className="font-semibold text-slate-800">{g.customer_name}</div>
                      <div className="text-xs text-slate-400 mt-0.5">{g.customer_id}</div>
                    </td>

                    {/* Risk Tier */}
                    <td className="px-6 py-4">
                      {g.risk_tier ? (
                        <span className={`px-2.5 py-1 rounded-md text-[11px] font-bold uppercase tracking-wider ${
                          g.risk_tier === 'CRITICAL'
                            ? 'bg-red-100 text-red-700'
                            : 'bg-amber-100 text-amber-700'
                        }`}>
                          {g.risk_tier}
                        </span>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>

                    {/* Message — truncated, expands on hover via title */}
                    <td className="px-6 py-4 max-w-sm">
                      <p
                        title={g.message}
                        className="text-slate-700 line-clamp-2 leading-relaxed"
                      >
                        {g.message}
                      </p>
                    </td>

                    {/* Submitted At */}
                    <td className="px-6 py-4 text-slate-500 whitespace-nowrap">
                      {new Date(g.submitted_at).toLocaleString('en-IN', {
                        day: '2-digit', month: 'short', year: 'numeric',
                        hour: '2-digit', minute: '2-digit',
                      })}
                    </td>

                    {/* Status */}
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${
                          g.status === 'OPEN' ? 'bg-orange-400' : 'bg-green-500'
                        }`} />
                        <span className={`font-semibold text-xs uppercase tracking-wide ${
                          g.status === 'OPEN' ? 'text-orange-600' : 'text-green-700'
                        }`}>
                          {g.status}
                        </span>
                      </div>
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