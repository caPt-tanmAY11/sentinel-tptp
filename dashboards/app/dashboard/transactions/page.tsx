'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { sentinelApi } from '@/lib/api';

const fmtInr = (v: number) =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v);

export default function TransactionsPage() {
  const router = useRouter();
  const [limit, setLimit] = useState(200);

  const { data: liveData, isLoading } = useQuery({
    queryKey:        ['all-transactions', limit],
    queryFn:         () => sentinelApi.getLiveTransactions(limit).then(r => r.data),
    refetchInterval: 3000,
  });

  const transactions: any[] = liveData?.transactions || [];

  return (
    <div className="p-8">
      <header className="mb-8">
        <h2 className="text-3xl font-headline font-extrabold tracking-tight text-on-surface">
          Global Transaction Feed
        </h2>
        <p className="text-slate-500 font-body">Real-time view of all scored transactions across the portfolio.</p>
      </header>

      <div className="glass-card rounded-2xl ambient-shadow-sm overflow-hidden flex flex-col" style={{ minHeight: '600px' }}>
        <div className="px-6 py-4 flex items-center justify-between" style={{ borderBottom: '1px solid rgba(195,198,215,0.2)' }}>
          <div className="flex items-center gap-3">
            <span className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
            </span>
            <span className="text-[10px] font-label font-bold uppercase tracking-widest text-emerald-600">Live</span>
            <span className="text-sm font-semibold text-slate-500 ml-2">Showing last {transactions.length} events</span>
          </div>
          <select value={limit} onChange={(e) => setLimit(Number(e.target.value))} className="bg-white border border-slate-200 rounded-lg px-3 py-1 text-xs">
            <option value={50}>50 rows</option>
            <option value={200}>200 rows</option>
            <option value={500}>500 rows</option>
          </select>
        </div>

        <div className="grid px-6 py-2 text-[10px] font-label font-bold uppercase tracking-widest text-slate-400"
          style={{
            gridTemplateColumns: '120px 80px 80px 120px 1fr 180px 100px 90px 100px',
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

        <div className="overflow-y-auto flex-1 h-[700px]">
          {isLoading && transactions.length === 0 ? (
             <div className="py-12 text-center text-slate-500">Loading transactions...</div>
          ) : transactions.length === 0 ? (
            <div className="py-12 text-center text-slate-500">No transactions generated yet.</div>
          ) : (
            transactions.map((txn: any) => {
              const timeStr = new Date(txn.event_ts).toLocaleString('en-IN', {
                month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
              });

              return (
                <div key={txn.event_id} onClick={() => router.push(`/dashboard/${txn.customer_id}`)}
                  className="grid px-6 py-3 cursor-pointer hover:bg-white/60 transition-all duration-150 items-center text-xs"
                  style={{
                    gridTemplateColumns: '120px 80px 80px 120px 1fr 180px 100px 90px 100px',
                    borderBottom: '1px solid rgba(195,198,215,0.1)',
                  }}>
                  <span className="font-mono text-slate-500">{timeStr}</span>
                  <span className="font-bold text-blue-600 bg-blue-50 px-2 py-0.5 rounded-md w-fit">{txn.platform}</span>
                  <span className={`font-bold px-2 py-0.5 rounded-md w-fit ${txn.payment_status === 'failed' ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'}`}>{txn.payment_status}</span>
                  <span className="font-bold">{fmtInr(txn.amount)}</span>
                  <span className="truncate pr-4 text-slate-600" title={txn.receiver_id}>{txn.receiver_id || '—'}</span>
                  <span className="font-semibold text-slate-700 truncate pr-4">{txn.customer_name}</span>
                  <span className="text-slate-500 truncate pr-2">{txn.inferred_category.replace(/_/g, ' ')}</span>
                  <span className="font-mono text-slate-500">{txn.txn_severity.toFixed(3)}</span>
                  <span className={`font-mono font-bold ${txn.delta_applied > 0 ? 'text-red-500' : txn.delta_applied < 0 ? 'text-green-500' : 'text-slate-400'}`}>
                    {txn.delta_applied > 0 ? '+' : ''}{txn.delta_applied.toFixed(4)}
                  </span>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
