'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { sentinelApi } from '@/lib/api';

export default function InterventionsPage() {
  const queryClient = useQueryClient();
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [sendingIds, setSendingIds] = useState<Set<string>>(new Set());

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

  const sendMutation = useMutation({
    mutationFn: (customer: {
      customer_id: string;
      first_name: string;
      last_name: string;
      risk_tier: string;
    }) => sentinelApi.sendInterventionEmail(customer).then(res => res.data),

    onMutate: (customer) => {
      setSendingIds(prev => new Set(prev).add(customer.customer_id));
    },

    onSuccess: (data, customer) => {
      showToast(`Email sent successfully to ${customer.first_name} ${customer.last_name}`, 'success');
      queryClient.invalidateQueries({ queryKey: ['interventions'] });
      queryClient.invalidateQueries({ queryKey: ['pendingInterventions'] });
    },

    onError: (err: any, customer) => {
      showToast(
        err.response?.data?.error || `Failed to send email for ${customer.first_name} ${customer.last_name}`,
        'error'
      );
    },

    onSettled: (_, __, customer) => {
      setSendingIds(prev => {
        const next = new Set(prev);
        next.delete(customer.customer_id);
        return next;
      });
    },
  });

  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 5000);
  };

  const pendingList = pendingData?.pending || [];
  const interventions = interventionsData?.interventions || [];
  const acknowledgedCount = interventions.filter((i: any) => i.status === 'ACKNOWLEDGED').length;

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">

      {/* Page Header */}
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">Interventions</h1>
        <p className="text-sm text-slate-500 mt-1">
          Review at-risk customers and manually trigger outreach emails.
        </p>
      </div>

      {/* Toast */}
      {toast && (
        <div className={`p-4 rounded-xl border flex items-start gap-3 shadow-lg max-w-lg ${
          toast.type === 'success'
            ? 'bg-green-50 border-green-200 text-green-800'
            : 'bg-red-50 border-red-200 text-red-800'
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

      {/* Stats Row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white p-6 rounded-2xl border shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-orange-100 text-orange-600 flex items-center justify-center">
            <span className="material-symbols-outlined text-2xl">pending_actions</span>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-500">Awaiting Email</div>
            <div className="text-2xl font-black text-slate-900">
              {isLoadingPending ? '...' : pendingList.length}
            </div>
          </div>
        </div>
        <div className="bg-white p-6 rounded-2xl border shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-blue-100 text-blue-600 flex items-center justify-center">
            <span className="material-symbols-outlined text-2xl">outgoing_mail</span>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-500">Total Sent</div>
            <div className="text-2xl font-black text-slate-900">
              {isLoadingInterventions ? '...' : interventions.length}
            </div>
          </div>
        </div>
        <div className="bg-white p-6 rounded-2xl border shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-green-100 text-green-600 flex items-center justify-center">
            <span className="material-symbols-outlined text-2xl">mark_email_read</span>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-500">Acknowledged</div>
            <div className="text-2xl font-black text-slate-900">
              {isLoadingInterventions ? '...' : acknowledgedCount}
            </div>
          </div>
        </div>
      </div>

      {/* ── Pending Interventions Section ── */}
      <div className="bg-white rounded-2xl border shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b bg-slate-50/50 flex items-center justify-between">
          <div>
            <h2 className="font-bold text-slate-800">Pending Outreach</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Customers in HIGH or CRITICAL tier who have not been contacted this week.
            </p>
          </div>
          {pendingList.length > 0 && (
            <span className="bg-orange-100 text-orange-700 text-xs font-bold px-3 py-1 rounded-full">
              {pendingList.length} pending
            </span>
          )}
        </div>

        {isLoadingPending ? (
          <div className="p-12 text-center text-slate-400">Loading...</div>
        ) : pendingList.length === 0 ? (
          <div className="p-12 text-center text-slate-400">
            <span className="material-symbols-outlined text-4xl mb-2 opacity-40 block">
              check_circle
            </span>
            <p className="font-medium">No pending outreach.</p>
            <p className="text-sm mt-1">All HIGH / CRITICAL customers have been contacted this week.</p>
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {pendingList.map((customer: any) => {
              const isSending = sendingIds.has(customer.customer_id);
              const isCritical = customer.risk_tier === 1 || customer.risk_label === 'CRITICAL';

              return (
                <div
                  key={customer.customer_id}
                  className="flex items-center justify-between px-6 py-4 hover:bg-slate-50/60 transition-colors"
                >
                  {/* Customer Info */}
                  <div className="flex items-center gap-4">
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center text-white font-bold text-sm ${
                      isCritical ? 'bg-red-500' : 'bg-amber-500'
                    }`}>
                      {customer.first_name?.[0]}{customer.last_name?.[0]}
                    </div>
                    <div>
                      <div className="font-semibold text-slate-800">
                        {customer.first_name} {customer.last_name}
                      </div>
                      <div className="text-xs text-slate-500">ID: {customer.customer_id}</div>
                    </div>
                  </div>

                  {/* Right side: tier badge + button */}
                  <div className="flex items-center gap-4">
                    <span className={`px-2.5 py-1 rounded-md text-[11px] font-bold uppercase tracking-wider ${
                      isCritical
                        ? 'bg-red-100 text-red-700'
                        : 'bg-amber-100 text-amber-700'
                    }`}>
                      {customer.risk_label}
                    </span>

                    <button
                      onClick={() =>
                        sendMutation.mutate({
                          customer_id: customer.customer_id,
                          first_name: customer.first_name,
                          last_name: customer.last_name,
                          risk_tier: customer.risk_label,
                        })
                      }
                      disabled={isSending}
                      className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all ${
                        isSending
                          ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                          : 'bg-blue-600 text-white hover:bg-blue-700 active:scale-95 shadow-sm'
                      }`}
                    >
                      {isSending ? (
                        <>
                          <span className="material-symbols-outlined text-base animate-spin">
                            progress_activity
                          </span>
                          Sending...
                        </>
                      ) : (
                        <>
                          <span className="material-symbols-outlined text-base">send</span>
                          Send Email
                        </>
                      )}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Intervention History Section ── */}
      <div className="bg-white rounded-2xl border shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b bg-slate-50/50">
          <h2 className="font-bold text-slate-800">Intervention History</h2>
          <p className="text-xs text-slate-500 mt-0.5">All emails sent, with acknowledgement status.</p>
        </div>

        {isLoadingInterventions ? (
          <div className="p-12 text-center text-slate-400">Loading...</div>
        ) : interventions.length === 0 ? (
          <div className="p-12 text-center text-slate-400">
            <span className="material-symbols-outlined text-4xl mb-2 opacity-50 block">inbox</span>
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
                        row.risk_tier === 'CRITICAL'
                          ? 'bg-red-100 text-red-700'
                          : 'bg-orange-100 text-orange-700'
                      }`}>
                        {row.risk_tier}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-slate-500">
                      {new Date(row.sent_at).toLocaleString('en-IN', {
                        day: '2-digit', month: 'short', year: 'numeric',
                        hour: '2-digit', minute: '2-digit',
                      })}
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${
                          row.status === 'ACKNOWLEDGED' ? 'bg-green-500' : 'bg-slate-300'
                        }`} />
                        <span className={`font-semibold ${
                          row.status === 'ACKNOWLEDGED' ? 'text-green-700' : 'text-slate-600'
                        }`}>
                          {row.status}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-slate-500">
                      {row.acknowledged_at
                        ? new Date(row.acknowledged_at).toLocaleString('en-IN', {
                            day: '2-digit', month: 'short', year: 'numeric',
                            hour: '2-digit', minute: '2-digit',
                          })
                        : '--'}
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