'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { sentinelApi } from '@/lib/api';

export default function InterventionsPage() {
  const queryClient = useQueryClient();
  const [isProcessing, setIsProcessing] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

  const { data: interventionsData, isLoading: isLoadingInterventions } = useQuery({
    queryKey: ['interventions'],
    queryFn: () => sentinelApi.getInterventions().then(res => res.data),
    refetchInterval: 15000,
  });

  const { data: pendingData, isLoading: isLoadingPending } = useQuery({
    queryKey: ['pendingInterventions'],
    queryFn: () => sentinelApi.getPendingInterventions().then(res => res.data),
    refetchInterval: 15000,
  });

  const dispatchMutation = useMutation({
    mutationFn: () => sentinelApi.processInterventions().then(res => res.data),
    onSuccess: (data) => {
      setToast({ message: data.message || 'Interventions processed successfully', type: 'success' });
      queryClient.invalidateQueries({ queryKey: ['interventions'] });
      queryClient.invalidateQueries({ queryKey: ['pendingInterventions'] });
      setTimeout(() => setToast(null), 5000);
    },
    onError: (err: any) => {
      setToast({ message: err.response?.data?.error || err.message || 'Failed to process interventions', type: 'error' });
      setTimeout(() => setToast(null), 8000);
    },
    onSettled: () => {
      setIsProcessing(false);
    }
  });

  const handleDispatch = () => {
    setIsProcessing(true);
    dispatchMutation.mutate();
  };

  const pendingCount = pendingData?.total || 0;
  const interventions = interventionsData?.interventions || [];

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">Interventions</h1>
          <p className="text-sm text-slate-500 mt-1">Manage outbound communications for high-risk accounts.</p>
        </div>
        
        <button
          onClick={handleDispatch}
          disabled={isProcessing || pendingCount === 0}
          className={`flex items-center gap-2 px-5 py-2.5 rounded-xl font-bold text-white transition-all shadow-md ${
            isProcessing || pendingCount === 0
              ? 'bg-slate-300 cursor-not-allowed text-slate-500 shadow-none'
              : 'bg-blue-600 hover:bg-blue-700 hover:shadow-lg active:scale-95'
          }`}
        >
          {isProcessing ? (
            <span className="material-symbols-outlined animate-spin text-lg">progress_activity</span>
          ) : (
            <span className="material-symbols-outlined text-lg">send</span>
          )}
          {isProcessing ? 'Dispatching...' : `Dispatch Pending (${pendingCount})`}
        </button>
      </div>

      {toast && (
        <div className={`p-4 rounded-xl border flex items-start gap-3 shadow-lg max-w-md ${
          toast.type === 'success' ? 'bg-green-50 border-green-200 text-green-800' : 'bg-red-50 border-red-200 text-red-800'
        }`}>
          <span className="material-symbols-outlined">
            {toast.type === 'success' ? 'check_circle' : 'error'}
          </span>
          <div className="text-sm font-medium">{toast.message}</div>
          <button onClick={() => setToast(null)} className="ml-auto opacity-50 hover:opacity-100">
            <span className="material-symbols-outlined text-sm">close</span>
          </button>
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white p-6 rounded-2xl border shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-orange-100 text-orange-600 flex items-center justify-center">
            <span className="material-symbols-outlined text-2xl">pending_actions</span>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-500">Pending This Week</div>
            <div className="text-2xl font-black text-slate-900">{isLoadingPending ? '...' : pendingCount}</div>
          </div>
        </div>
        <div className="bg-white p-6 rounded-2xl border shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-blue-100 text-blue-600 flex items-center justify-center">
            <span className="material-symbols-outlined text-2xl">outgoing_mail</span>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-500">Total Sent</div>
            <div className="text-2xl font-black text-slate-900">{isLoadingInterventions ? '...' : interventions.length}</div>
          </div>
        </div>
        <div className="bg-white p-6 rounded-2xl border shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-green-100 text-green-600 flex items-center justify-center">
            <span className="material-symbols-outlined text-2xl">mark_email_read</span>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-500">Acknowledged</div>
            <div className="text-2xl font-black text-slate-900">
              {isLoadingInterventions ? '...' : interventions.filter((i: any) => i.status === 'ACKNOWLEDGED').length}
            </div>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-2xl border shadow-sm overflow-hidden mt-6 flex flex-col min-h-[500px]">
        <div className="px-6 py-4 border-b flex items-center justify-between bg-slate-50/50">
          <h2 className="font-bold text-slate-800">Intervention History</h2>
        </div>
        
        {isLoadingInterventions ? (
          <div className="p-12 text-center text-slate-400">Loading...</div>
        ) : interventionsData?.total === 0 ? (
          <div className="p-12 text-center text-slate-400">
            <span className="material-symbols-outlined text-4xl mb-2 opacity-50">inbox</span>
            <p>No interventions have been recorded yet.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 border-b text-slate-500 font-medium">
                <tr>
                  <th className="px-6 py-4">Customer Name</th>
                  <th className="px-6 py-4">Risk Tier</th>
                  <th className="px-6 py-4">Date Sent</th>
                  <th className="px-6 py-4">Status</th>
                  <th className="px-6 py-4">Acknowledged At</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {interventions.map((row: any) => (
                  <tr key={row.intervention_id} className="hover:bg-slate-50/50 transition-colors">
                    <td className="px-6 py-4 font-semibold text-slate-800">{row.customer_name}</td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-1 rounded-md text-[11px] font-bold uppercase tracking-wider ${
                        row.risk_tier === 'CRITICAL' ? 'bg-red-100 text-red-700' : 'bg-orange-100 text-orange-700'
                      }`}>
                        {row.risk_tier}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-slate-500">
                      {new Date(row.sent_at).toLocaleString('en-IN', {
                        day: '2-digit', month: 'short', year: 'numeric',
                        hour: '2-digit', minute: '2-digit'
                      })}
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${row.status === 'ACKNOWLEDGED' ? 'bg-green-500' : 'bg-slate-300'}`} />
                        <span className={`font-semibold ${row.status === 'ACKNOWLEDGED' ? 'text-green-700' : 'text-slate-600'}`}>
                          {row.status}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-slate-500">
                      {row.acknowledged_at ? new Date(row.acknowledged_at).toLocaleString('en-IN', {
                        day: '2-digit', month: 'short', year: 'numeric',
                        hour: '2-digit', minute: '2-digit'
                      }) : '--'}
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
