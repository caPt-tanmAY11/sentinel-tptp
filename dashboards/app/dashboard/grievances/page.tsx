'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { sentinelApi } from '@/lib/api';

// ─── Types ────────────────────────────────────────────────────────────────────
interface TransactionDispute {
  event_id:          string;
  transaction_id:    string;
  amount:            number;
  inferred_category: string | null;
  event_ts:          string;
  agreed:            boolean;
  dispute_reason:    string | null;
}

interface Grievance {
  grievance_id:         string;
  customer_id:          string;
  customer_name:        string;
  message:              string;
  transaction_disputes: TransactionDispute[] | null;
  additional_notes:     string | null;
  submitted_at:         string;
  status:               string;
  risk_tier:            string | null;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function formatINR(amount: number) {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency', currency: 'INR', maximumFractionDigits: 0,
  }).format(amount);
}

function formatCategory(cat: string | null) {
  if (!cat) return 'Unknown';
  return cat.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

// ─── Expanded Detail Panel ────────────────────────────────────────────────────
function GrievanceDetail({ g }: { g: Grievance }) {
  const disputes = g.transaction_disputes || [];
  const disputed = disputes.filter(d => !d.agreed);
  const agreed   = disputes.filter(d => d.agreed);

  return (
    <div className="px-6 pb-6 pt-2 bg-slate-50/70 border-t border-slate-100">

      {/* Summary pills */}
      {disputes.length > 0 && (
        <div className="flex gap-3 mb-4 flex-wrap">
          <span className="text-xs font-semibold px-3 py-1 rounded-full bg-slate-100 text-slate-600">
            {disputes.length} transaction{disputes.length !== 1 ? 's' : ''} reviewed
          </span>
          {agreed.length > 0 && (
            <span className="text-xs font-semibold px-3 py-1 rounded-full bg-green-100 text-green-700">
              ✓ {agreed.length} confirmed accurate
            </span>
          )}
          {disputed.length > 0 && (
            <span className="text-xs font-semibold px-3 py-1 rounded-full bg-red-100 text-red-700">
              ✗ {disputed.length} disputed
            </span>
          )}
        </div>
      )}

      {/* Transaction dispute table */}
      {disputes.length > 0 ? (
        <div className="mb-5">
          <div className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
            Transaction Breakdown
          </div>
          <div className="rounded-xl border border-slate-200 overflow-hidden">
            {disputes.map((d, i) => (
              <div
                key={d.event_id}
                className={`${i > 0 ? 'border-t border-slate-100' : ''} ${
                  !d.agreed ? 'bg-red-50/60' : 'bg-white'
                }`}
              >
                {/* Transaction row */}
                <div className="flex items-center justify-between gap-4 px-4 py-3 flex-wrap">
                  <div className="flex items-center gap-4 flex-wrap">
                    {/* Amount */}
                    <div className="text-sm font-bold text-slate-800 w-28 shrink-0">
                      {formatINR(d.amount)}
                    </div>
                    {/* Category */}
                    <div className="text-sm text-slate-600">
                      {formatCategory(d.inferred_category)}
                    </div>
                    {/* Date */}
                    <div className="text-xs text-slate-400">
                      {formatDate(d.event_ts)}
                    </div>
                  </div>
                  {/* Status badge */}
                  <div>
                    {d.agreed ? (
                      <span className="inline-flex items-center gap-1 text-[11px] font-bold px-2.5 py-1 rounded-md bg-green-100 text-green-700">
                        ✓ Accurate
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[11px] font-bold px-2.5 py-1 rounded-md bg-red-100 text-red-700">
                        ✗ Disputed
                      </span>
                    )}
                  </div>
                </div>

                {/* Dispute reason — only if disputed */}
                {!d.agreed && d.dispute_reason && (
                  <div className="px-4 pb-3">
                    <div className="bg-white border border-red-200 rounded-lg px-4 py-2.5">
                      <span className="text-xs font-semibold text-red-500 uppercase tracking-wide">
                        Customer's reason:
                      </span>
                      <p className="text-sm text-slate-700 mt-1 leading-relaxed">
                        {d.dispute_reason}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="text-sm text-slate-400 italic mb-4">
          No transaction-level dispute data — this grievance was submitted via the legacy form.
        </div>
      )}

      {/* Additional notes */}
      {g.additional_notes && (
        <div className="mb-4">
          <div className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
            Additional Notes from Customer
          </div>
          <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
            <p className="text-sm text-slate-700 leading-relaxed">{g.additional_notes}</p>
          </div>
        </div>
      )}

      {/* Legacy message fallback */}
      {disputes.length === 0 && g.message && g.message !== 'Transaction dispute submitted.' && (
        <div className="mb-4">
          <div className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
            Customer Message
          </div>
          <div className="bg-white border border-slate-200 rounded-xl px-4 py-3">
            <p className="text-sm text-slate-700 leading-relaxed">{g.message}</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────
export default function GrievancesPage() {
  const [search, setSearch]       = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['grievances'],
    queryFn: () => sentinelApi.getGrievances().then(res => res.data),
    refetchInterval: 15000,
  });

  const grievances: Grievance[] = data?.grievances || [];

  const filtered = grievances.filter(g =>
    g.customer_name?.toLowerCase().includes(search.toLowerCase()) ||
    g.customer_id?.toLowerCase().includes(search.toLowerCase()) ||
    g.message?.toLowerCase().includes(search.toLowerCase())
  );

  const openCount     = grievances.filter(g => g.status === 'OPEN').length;
  const disputedCount = grievances.filter(g =>
    (g.transaction_disputes || []).some(d => !d.agreed)
  ).length;

  const toggleExpand = (id: string) =>
    setExpandedId(prev => prev === id ? null : id);

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">

      {/* Page Header */}
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">Grievances</h1>
        <p className="text-sm text-slate-500 mt-1">
          Customer disputes submitted in response to risk tier alert emails. Click any row to expand details.
        </p>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="bg-white p-6 rounded-2xl border shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-blue-100 text-blue-600 flex items-center justify-center">
            <span className="material-symbols-outlined text-2xl">forum</span>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-500">Total</div>
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
          <div className="w-12 h-12 rounded-xl bg-red-100 text-red-600 flex items-center justify-center">
            <span className="material-symbols-outlined text-2xl">report</span>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-500">With Disputes</div>
            <div className="text-2xl font-black text-slate-900">
              {isLoading ? '...' : disputedCount}
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
        <div className="px-6 py-4 border-b bg-slate-50/50 flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h2 className="font-bold text-slate-800">All Grievances</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Refreshes every 15 seconds · Click a row to expand dispute details.
            </p>
          </div>
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
            <span className="material-symbols-outlined text-4xl mb-2 opacity-40 block">inbox</span>
            <p className="font-medium">
              {search ? 'No grievances match your search.' : 'No grievances submitted yet.'}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {filtered.map(g => {
              const isOpen     = expandedId === g.grievance_id;
              const disputes   = g.transaction_disputes || [];
              const nDisputed  = disputes.filter(d => !d.agreed).length;
              const hasDisputes = disputes.length > 0;

              return (
                <div key={g.grievance_id}>
                  {/* Clickable summary row */}
                  <div
                    onClick={() => toggleExpand(g.grievance_id)}
                    className="flex items-center gap-4 px-6 py-4 hover:bg-slate-50 cursor-pointer transition-colors select-none flex-wrap"
                  >
                    {/* Chevron */}
                    <div className={`text-slate-400 transition-transform duration-200 shrink-0 ${isOpen ? 'rotate-90' : ''}`}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M8.59 16.59L13.17 12 8.59 7.41 10 6l6 6-6 6z"/>
                      </svg>
                    </div>

                    {/* Customer */}
                    <div className="min-w-[160px] flex-1">
                      <div className="font-semibold text-slate-800 text-sm">{g.customer_name}</div>
                      <div className="text-xs text-slate-400 mt-0.5">{g.customer_id}</div>
                    </div>

                    {/* Risk Tier */}
                    <div className="shrink-0">
                      {g.risk_tier ? (
                        <span className={`px-2.5 py-1 rounded-md text-[11px] font-bold uppercase tracking-wider ${
                          g.risk_tier === 'CRITICAL'
                            ? 'bg-red-100 text-red-700'
                            : 'bg-amber-100 text-amber-700'
                        }`}>
                          {g.risk_tier}
                        </span>
                      ) : (
                        <span className="text-slate-400 text-sm">—</span>
                      )}
                    </div>

                    {/* Dispute summary */}
                    <div className="shrink-0 flex gap-2 flex-wrap">
                      {hasDisputes ? (
                        <>
                          {nDisputed > 0 && (
                            <span className="text-[11px] font-semibold px-2 py-1 rounded-full bg-red-100 text-red-700">
                              ✗ {nDisputed} disputed
                            </span>
                          )}
                          {disputes.length - nDisputed > 0 && (
                            <span className="text-[11px] font-semibold px-2 py-1 rounded-full bg-green-100 text-green-700">
                              ✓ {disputes.length - nDisputed} accurate
                            </span>
                          )}
                        </>
                      ) : (
                        <span className="text-xs text-slate-400 italic">Legacy submission</span>
                      )}
                    </div>

                    {/* Date */}
                    <div className="text-xs text-slate-400 shrink-0 whitespace-nowrap">
                      {formatDate(g.submitted_at)}
                    </div>

                    {/* Status */}
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className={`w-2 h-2 rounded-full ${
                        g.status === 'OPEN' ? 'bg-orange-400' : 'bg-green-500'
                      }`} />
                      <span className={`text-xs font-semibold uppercase tracking-wide ${
                        g.status === 'OPEN' ? 'text-orange-600' : 'text-green-700'
                      }`}>
                        {g.status}
                      </span>
                    </div>
                  </div>

                  {/* Expanded detail */}
                  {isOpen && <GrievanceDetail g={g} />}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
