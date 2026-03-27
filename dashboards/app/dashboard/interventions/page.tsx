'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { sentinelApi } from '@/lib/api';

// ─── Types ────────────────────────────────────────────────────────────────────

interface Suggestion {
  id: number;
  title: string;
  description: string;
}

interface PendingCustomer {
  customer_id: string;
  first_name: string;
  last_name: string;
  risk_label: string;
  risk_tier: number;
  risk_score?: number;
  anomaly_score?: number;
  txn_severity?: number;
}

interface CustomerSnapshot {
  profile: any | null;
  pulse: any | null;
  loans: any[] | null;
  transactions: any[] | null;
  loading: boolean;
  error: string | null;
}

type ModalStep = 'suggestions' | 'confirm';

interface ModalState {
  customer: PendingCustomer;
  step: ModalStep;
  suggestions: Suggestion[];
  selectedSuggestion: Suggestion | null;
  officerComment: string;
  loadingSuggestions: boolean;
  suggestionError: string | null;
  snapshot: CustomerSnapshot;
}

// ─── Small helpers ────────────────────────────────────────────────────────────

function RiskBadge({ tier }: { tier: string }) {
  const isCritical = tier === 'CRITICAL';
  return (
    <span className={`px-2.5 py-0.5 rounded text-[11px] font-bold uppercase tracking-wider ${
      isCritical ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
    }`}>
      {tier}
    </span>
  );
}

function MiniStat({ label, value, highlight }: { label: string; value: string | number; highlight?: boolean }) {
  return (
    <div className={`rounded-lg p-3 ${highlight ? 'bg-red-50 border border-red-100' : 'bg-slate-50 border border-slate-100'}`}>
      <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">{label}</div>
      <div className={`text-sm font-bold mt-0.5 ${highlight ? 'text-red-700' : 'text-slate-800'}`}>{value}</div>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function InterventionsPage() {
  const queryClient = useQueryClient();
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [modal, setModal] = useState<ModalState | null>(null);

  // ── Queries ──────────────────────────────────────────────────────────────

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

  // ── Send mutation ─────────────────────────────────────────────────────────

  const sendMutation = useMutation({
    mutationFn: (payload: {
      customer_id: string;
      first_name: string;
      last_name: string;
      risk_tier: string;
      selected_relief?: Suggestion;
      officer_comment?: string;
    }) => sentinelApi.sendInterventionEmail(payload).then(res => res.data),

    onSuccess: (_data, payload) => {
      showToast(`Email sent successfully to ${payload.first_name} ${payload.last_name}`, 'success');
      queryClient.invalidateQueries({ queryKey: ['interventions'] });
      queryClient.invalidateQueries({ queryKey: ['pendingInterventions'] });
      setModal(null);
    },

    onError: (err: any, payload) => {
      showToast(
        err.response?.data?.error || `Failed to send email for ${payload.first_name} ${payload.last_name}`,
        'error'
      );
    },
  });

  // ── Open modal: fetch snapshot + suggestions in parallel ──────────────────

  const handleOpenModal = async (customer: PendingCustomer) => {
    setModal({
      customer,
      step: 'suggestions',
      suggestions: [],
      selectedSuggestion: null,
      officerComment: '',
      loadingSuggestions: true,
      suggestionError: null,
      snapshot: { profile: null, pulse: null, loans: null, transactions: null, loading: true, error: null },
    });

    const [suggestResult, snapshotResult] = await Promise.allSettled([
      sentinelApi.getReliefSuggestions({
        customer_id:   customer.customer_id,
        first_name:    customer.first_name,
        last_name:     customer.last_name,
        risk_tier:     customer.risk_label,
        risk_score:    customer.risk_score,
        anomaly_score: customer.anomaly_score,
        txn_severity:  customer.txn_severity,
      }),
      Promise.allSettled([
        sentinelApi.getCustomerProfile(customer.customer_id),
        sentinelApi.getCustomerPulse(customer.customer_id),
        sentinelApi.getCustomerLoans(customer.customer_id),
        sentinelApi.getCustomerTransactions(customer.customer_id, 8),
      ]),
    ]);

    const suggestions     = suggestResult.status === 'fulfilled' ? suggestResult.value.data.suggestions || [] : [];
    const suggestionError = suggestResult.status === 'rejected'
      ? (suggestResult.reason?.response?.data?.error || 'Failed to load suggestions.') : null;

    let profile = null, pulse = null, loans: any[] = [], transactions: any[] = [], snapshotError = null;
    if (snapshotResult.status === 'fulfilled') {
      const [pR, puR, lR, tR] = snapshotResult.value;
      if (pR.status  === 'fulfilled') profile      = pR.value.data;
      if (puR.status === 'fulfilled') pulse         = puR.value.data;
      if (lR.status  === 'fulfilled') loans         = lR.value.data?.loans || lR.value.data || [];
      if (tR.status  === 'fulfilled') transactions  = tR.value.data?.transactions || tR.value.data || [];
    } else {
      snapshotError = 'Could not load customer data.';
    }

    setModal(prev => prev ? {
      ...prev,
      suggestions,
      loadingSuggestions: false,
      suggestionError,
      snapshot: { profile, pulse, loans, transactions, loading: false, error: snapshotError },
    } : null);
  };

  const handleSelectSuggestion  = (s: Suggestion) => setModal(prev => prev ? { ...prev, selectedSuggestion: s } : null);
  const handleProceedToConfirm  = ()               => setModal(prev => prev ? { ...prev, step: 'confirm' } : null);
  const handleBackToSuggestions = ()               => setModal(prev => prev ? { ...prev, step: 'suggestions' } : null);

  const handleConfirmSend = () => {
    if (!modal) return;
    sendMutation.mutate({
      customer_id:     modal.customer.customer_id,
      first_name:      modal.customer.first_name,
      last_name:       modal.customer.last_name,
      risk_tier:       modal.customer.risk_label,
      selected_relief: modal.selectedSuggestion ?? undefined,
      officer_comment: modal.officerComment.trim() || undefined,
    });
  };

  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 5000);
  };

  // ── Derived ───────────────────────────────────────────────────────────────

  const pendingList       = pendingData?.pending            || [];
  const interventions     = interventionsData?.interventions || [];
  const acknowledgedCount = interventions.filter((i: any) => i.status === 'ACKNOWLEDGED').length;

  // ── Render ────────────────────────────────────────────────────────────────

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
          toast.type === 'success' ? 'bg-green-50 border-green-200 text-green-800' : 'bg-red-50 border-red-200 text-red-800'
        }`}>
          <span className="material-symbols-outlined">{toast.type === 'success' ? 'check_circle' : 'error'}</span>
          <div className="text-sm font-medium">{toast.message}</div>
          <button onClick={() => setToast(null)} className="ml-auto opacity-50 hover:opacity-100">
            <span className="material-symbols-outlined text-sm">close</span>
          </button>
        </div>
      )}

      {/* Stats Row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {[
          { icon: 'pending_actions', bg: 'bg-orange-100', color: 'text-orange-600', label: 'Awaiting Email',  value: isLoadingPending ? '...' : pendingList.length },
          { icon: 'outgoing_mail',   bg: 'bg-blue-100',   color: 'text-blue-600',   label: 'Total Sent',     value: isLoadingInterventions ? '...' : interventions.length },
          { icon: 'mark_email_read', bg: 'bg-green-100',  color: 'text-green-600',  label: 'Acknowledged',   value: isLoadingInterventions ? '...' : acknowledgedCount },
        ].map(s => (
          <div key={s.label} className="bg-white p-6 rounded-2xl border shadow-sm flex items-center gap-4">
            <div className={`w-12 h-12 rounded-xl ${s.bg} ${s.color} flex items-center justify-center`}>
              <span className="material-symbols-outlined text-2xl">{s.icon}</span>
            </div>
            <div>
              <div className="text-sm font-semibold text-slate-500">{s.label}</div>
              <div className="text-2xl font-black text-slate-900">{s.value}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Pending Interventions */}
      <div className="bg-white rounded-2xl border shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b bg-slate-50/50 flex items-center justify-between">
          <div>
            <h2 className="font-bold text-slate-800">Pending Outreach</h2>
            <p className="text-xs text-slate-500 mt-0.5">Customers in HIGH or CRITICAL tier who have not been contacted this week.</p>
          </div>
          {pendingList.length > 0 && (
            <span className="bg-orange-100 text-orange-700 text-xs font-bold px-3 py-1 rounded-full">{pendingList.length} pending</span>
          )}
        </div>

        {isLoadingPending ? (
          <div className="p-12 text-center text-slate-400">Loading...</div>
        ) : pendingList.length === 0 ? (
          <div className="p-12 text-center text-slate-400">
            <span className="material-symbols-outlined text-4xl mb-2 opacity-40 block">check_circle</span>
            <p className="font-medium">No pending outreach.</p>
            <p className="text-sm mt-1">All HIGH / CRITICAL customers have been contacted this week.</p>
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {pendingList.map((customer: PendingCustomer) => {
              const isCritical = customer.risk_tier === 1 || customer.risk_label === 'CRITICAL';
              return (
                <div key={customer.customer_id} className="flex items-center justify-between px-6 py-4 hover:bg-slate-50/60 transition-colors">
                  <div className="flex items-center gap-4">
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center text-white font-bold text-sm ${isCritical ? 'bg-red-500' : 'bg-amber-500'}`}>
                      {customer.first_name?.[0]}{customer.last_name?.[0]}
                    </div>
                    <div>
                      <div className="font-semibold text-slate-800">{customer.first_name} {customer.last_name}</div>
                      <div className="text-xs text-slate-500">ID: {customer.customer_id}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <RiskBadge tier={customer.risk_label} />
                    <button
                      onClick={() => handleOpenModal(customer)}
                      className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-blue-600 text-white hover:bg-blue-700 active:scale-95 shadow-sm transition-all"
                    >
                      <span className="material-symbols-outlined text-base">send</span>
                      Send Email
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Intervention History */}
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
                      <span className={`px-2 py-1 rounded-md text-[11px] font-bold uppercase tracking-wider ${row.risk_tier === 'CRITICAL' ? 'bg-red-100 text-red-700' : 'bg-orange-100 text-orange-700'}`}>
                        {row.risk_tier}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-slate-500">
                      {new Date(row.sent_at).toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${row.status === 'ACKNOWLEDGED' ? 'bg-green-500' : 'bg-slate-300'}`} />
                        <span className={`font-semibold ${row.status === 'ACKNOWLEDGED' ? 'text-green-700' : 'text-slate-600'}`}>{row.status}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-slate-500">
                      {row.acknowledged_at
                        ? new Date(row.acknowledged_at).toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
                        : '--'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ─── MODAL ──────────────────────────────────────────────────────────── */}
      {modal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ backgroundColor: 'rgba(15,23,42,0.65)', backdropFilter: 'blur(4px)' }}
        >
          <div className="bg-white rounded-2xl shadow-2xl w-full flex flex-col" style={{ maxWidth: '920px', maxHeight: '92vh' }}>

            {/* Modal Header */}
            <div className="px-6 py-4 border-b flex items-start justify-between flex-shrink-0">
              <div>
                <h2 className="font-extrabold text-slate-900 text-lg">
                  {modal.step === 'suggestions' ? '🤖 Review Profile & Select Relief' : '✅ Confirm & Send Email'}
                </h2>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-sm text-slate-500">{modal.customer.first_name} {modal.customer.last_name}</span>
                  <RiskBadge tier={modal.customer.risk_label} />
                  <span className="text-xs text-slate-400 font-mono">{modal.customer.customer_id.slice(0, 8)}…</span>
                </div>
              </div>
              <button onClick={() => setModal(null)} disabled={sendMutation.isPending} className="text-slate-400 hover:text-slate-600 transition-colors">
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>

            {/* ── STEP 1: Two-column layout ── */}
            {modal.step === 'suggestions' && (
              <div className="flex flex-1 min-h-0 overflow-hidden">

                {/* LEFT column — Customer history */}
                <div className="w-80 flex-shrink-0 border-r border-slate-100 overflow-y-auto bg-slate-50/60 p-5 space-y-5">
                  <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Customer History</p>

                  {modal.snapshot.loading && (
                    <div className="flex items-center gap-2 text-slate-400 text-sm py-6">
                      <span className="material-symbols-outlined text-base animate-spin">progress_activity</span>
                      Loading profile…
                    </div>
                  )}

                  {!modal.snapshot.loading && (
                    <>
                      {/* Identity */}
                      {modal.snapshot.profile && (
                        <div className="space-y-3">
                          <div className="flex items-center gap-3">
                            <div className={`w-10 h-10 rounded-full flex items-center justify-center text-white font-bold text-sm flex-shrink-0 ${modal.customer.risk_label === 'CRITICAL' ? 'bg-red-500' : 'bg-amber-500'}`}>
                              {modal.customer.first_name?.[0]}{modal.customer.last_name?.[0]}
                            </div>
                            <div>
                              <div className="font-semibold text-slate-800 text-sm">
                                {modal.snapshot.profile.full_name || `${modal.customer.first_name} ${modal.customer.last_name}`}
                              </div>
                              <div className="text-xs text-slate-500">{modal.snapshot.profile.email || '—'}</div>
                            </div>
                          </div>
                          <div className="grid grid-cols-2 gap-1.5">
                            <MiniStat label="Account Type" value={modal.snapshot.profile.account_type || '—'} />
                            <MiniStat label="Branch"       value={modal.snapshot.profile.branch || '—'} />
                            {modal.snapshot.profile.occupation && <MiniStat label="Occupation" value={modal.snapshot.profile.occupation} />}
                            {modal.snapshot.profile.monthly_income && (
                              <MiniStat label="Monthly Income" value={`₹${Number(modal.snapshot.profile.monthly_income).toLocaleString('en-IN')}`} />
                            )}
                            {modal.snapshot.profile.credit_score && (
                              <MiniStat label="Credit Score" value={modal.snapshot.profile.credit_score} highlight={modal.snapshot.profile.credit_score < 600} />
                            )}
                            {modal.snapshot.profile.age && <MiniStat label="Age" value={modal.snapshot.profile.age} />}
                          </div>
                        </div>
                      )}

                      {/* Risk Signals */}
                      {modal.snapshot.pulse && (
                        <div className="space-y-2">
                          <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Risk Signals</p>
                          <div className="grid grid-cols-2 gap-1.5">
                            <MiniStat label="Pulse Score"  value={(modal.snapshot.pulse.pulse_score ?? modal.snapshot.pulse.current_score ?? 0).toFixed(2)} highlight />
                            <MiniStat label="Risk Tier"    value={modal.snapshot.pulse.risk_tier || modal.customer.risk_label} highlight />
                            {modal.snapshot.pulse.anomaly_score !== undefined && (
                              <MiniStat label="Anomaly Score" value={Number(modal.snapshot.pulse.anomaly_score).toFixed(3)} highlight />
                            )}
                            {modal.snapshot.pulse.total_stress_events !== undefined && (
                              <MiniStat label="Stress Events" value={modal.snapshot.pulse.total_stress_events} highlight={modal.snapshot.pulse.total_stress_events > 3} />
                            )}
                          </div>
                        </div>
                      )}

                      {/* Loans */}
                      {modal.snapshot.loans && modal.snapshot.loans.length > 0 && (
                        <div className="space-y-2">
                          <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                            Active Loans ({modal.snapshot.loans.length})
                          </p>
                          <div className="space-y-2">
                            {modal.snapshot.loans.slice(0, 3).map((loan: any, i: number) => (
                              <div key={i} className="bg-white rounded-lg border border-slate-100 p-3 text-xs space-y-1.5">
                                <div className="flex items-center justify-between">
                                  <span className="font-semibold text-slate-700 capitalize">
                                    {loan.loan_type?.replace(/_/g, ' ') || 'Loan'}
                                  </span>
                                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${loan.loan_status === 'active' ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-600'}`}>
                                    {(loan.loan_status || 'ACTIVE').toUpperCase()}
                                  </span>
                                </div>
                                <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-slate-500">
                                  <span>Principal: <span className="text-slate-700 font-medium">₹{Number(loan.principal_amount || loan.loan_amount || 0).toLocaleString('en-IN')}</span></span>
                                  <span>EMI: <span className="text-slate-700 font-medium">₹{Number(loan.emi_amount || 0).toLocaleString('en-IN')}</span></span>
                                  {loan.remaining_tenure !== undefined && (
                                    <span>Remaining: <span className="text-slate-700 font-medium">{loan.remaining_tenure} mo.</span></span>
                                  )}
                                  {(loan.failed_auto_debit_count_30d > 0) && (
                                    <span className="text-red-600 font-semibold col-span-2">
                                      ⚠ {loan.failed_auto_debit_count_30d} failed debit(s)
                                    </span>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Recent Transactions */}
                      {modal.snapshot.transactions && modal.snapshot.transactions.length > 0 && (
                        <div className="space-y-2">
                          <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Recent Transactions</p>
                          <div className="space-y-1.5">
                            {modal.snapshot.transactions.slice(0, 7).map((txn: any, i: number) => {
                              const failed = txn.payment_status === 'failed';
                              return (
                                <div key={i} className={`flex items-center justify-between rounded-lg px-3 py-2 text-xs ${failed ? 'bg-red-50 border border-red-100' : 'bg-white border border-slate-100'}`}>
                                  <div className="min-w-0 flex-1 mr-2">
                                    <div className={`font-semibold truncate ${failed ? 'text-red-700' : 'text-slate-700'}`}>
                                      {txn.platform || txn.merchant_name || '—'}
                                    </div>
                                    <div className="text-slate-400 text-[10px] truncate">{txn.category_label || txn.inferred_category || ''}</div>
                                  </div>
                                  <div className="text-right flex-shrink-0">
                                    <div className={`font-bold ${failed ? 'text-red-600' : 'text-slate-800'}`}>
                                      ₹{Number(txn.amount || 0).toLocaleString('en-IN')}
                                    </div>
                                    <div className="text-[10px] text-slate-400">
                                      {(txn.txn_timestamp || txn.scored_at || '').slice(0, 10)}
                                    </div>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {modal.snapshot.error && (
                        <p className="text-xs text-slate-400 italic">{modal.snapshot.error}</p>
                      )}
                    </>
                  )}
                </div>

                {/* RIGHT column — AI Suggestions */}
                <div className="flex-1 overflow-y-auto p-5 space-y-4 flex flex-col">
                  <div>
                    <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">AI-Generated Relief Options</p>
                    <p className="text-xs text-slate-500 mt-1">
                      Powered by GROQ · Based on this customer's risk profile and transaction history
                    </p>
                  </div>

                  {modal.loadingSuggestions && (
                    <div className="flex flex-col items-center justify-center flex-1 gap-3 text-slate-400 py-10">
                      <span className="material-symbols-outlined text-4xl animate-spin text-blue-500">progress_activity</span>
                      <p className="text-sm font-medium">Analysing customer data with GROQ…</p>
                    </div>
                  )}

                  {modal.suggestionError && !modal.loadingSuggestions && (
                    <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
                      {modal.suggestionError}
                    </div>
                  )}

                  {!modal.loadingSuggestions && modal.suggestions.length > 0 && (
                    <div className="space-y-3 flex-1">
                      {modal.suggestions.map(s => {
                        const isSelected = modal.selectedSuggestion?.id === s.id;
                        return (
                          <button
                            key={s.id}
                            onClick={() => handleSelectSuggestion(s)}
                            className={`w-full text-left p-4 rounded-xl border-2 transition-all ${
                              isSelected ? 'border-blue-500 bg-blue-50' : 'border-slate-200 bg-white hover:border-blue-300 hover:bg-slate-50/80'
                            }`}
                          >
                            <div className="flex items-start gap-3">
                              <div className={`mt-0.5 w-5 h-5 rounded-full border-2 flex-shrink-0 flex items-center justify-center ${isSelected ? 'border-blue-500 bg-blue-500' : 'border-slate-300'}`}>
                                {isSelected && <span className="material-symbols-outlined text-white" style={{ fontSize: '12px' }}>check</span>}
                              </div>
                              <div className="flex-1">
                                <div className={`font-bold text-sm ${isSelected ? 'text-blue-800' : 'text-slate-800'}`}>
                                  Option {s.id}: {s.title}
                                </div>
                                <div className={`text-sm mt-1.5 leading-relaxed ${isSelected ? 'text-blue-700' : 'text-slate-500'}`}>
                                  {s.description}
                                </div>
                              </div>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  )}

                  {!modal.loadingSuggestions && modal.suggestions.length > 0 && (
                    <div className="flex gap-3 pt-3 border-t border-slate-100">
                      <button
                        onClick={() => setModal(null)}
                        className="flex-1 px-4 py-2.5 rounded-xl border border-slate-200 text-sm font-semibold text-slate-600 hover:bg-slate-50 transition-colors"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={handleProceedToConfirm}
                        disabled={!modal.selectedSuggestion}
                        className={`flex-1 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all ${
                          modal.selectedSuggestion
                            ? 'bg-blue-600 text-white hover:bg-blue-700 active:scale-95 shadow-sm'
                            : 'bg-slate-100 text-slate-400 cursor-not-allowed'
                        }`}
                      >
                        Continue →
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* ── STEP 2: Confirm ── */}
            {modal.step === 'confirm' && modal.selectedSuggestion && (
              <div className="overflow-y-auto flex-1 p-6 space-y-5">
                <div>
                  <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Selected Relief Measure</p>
                  <div className="bg-green-50 border border-green-200 rounded-xl p-4">
                    <p className="font-bold text-green-800 text-sm">{modal.selectedSuggestion.title}</p>
                    <p className="text-sm text-green-700 mt-1 leading-relaxed">{modal.selectedSuggestion.description}</p>
                  </div>
                </div>

                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-2">
                    Officer's Note <span className="font-normal normal-case text-slate-400">(optional)</span>
                  </label>
                  <textarea
                    rows={3}
                    value={modal.officerComment}
                    onChange={e => setModal(prev => prev ? { ...prev, officerComment: e.target.value } : null)}
                    placeholder="Add any specific instruction or personal note for this customer's situation…"
                    className="w-full px-4 py-3 rounded-xl border border-slate-200 text-sm text-slate-800 placeholder-slate-400 resize-none focus:outline-none focus:ring-2 focus:ring-blue-300 focus:border-blue-400 transition-all"
                  />
                </div>

                <div className="bg-slate-50 rounded-xl p-4 text-sm text-slate-600 space-y-1.5 border border-slate-100">
                  <p className="font-semibold text-slate-700 mb-1">What this email will contain</p>
                  <p><span className="text-slate-400">To:</span> {modal.customer.first_name} {modal.customer.last_name}</p>
                  <p><span className="text-slate-400">Relief:</span> {modal.selectedSuggestion.title}</p>
                  {modal.officerComment.trim() && (
                    <p><span className="text-slate-400">Note:</span> {modal.officerComment.trim()}</p>
                  )}
                  <p className="text-xs text-slate-400 pt-2 border-t border-slate-200 mt-2">
                    The customer's compliance report will include a full AI-elaborated section explaining this relief measure in plain language.
                  </p>
                </div>

                <div className="flex gap-3">
                  <button
                    onClick={handleBackToSuggestions}
                    disabled={sendMutation.isPending}
                    className="flex-1 px-4 py-2.5 rounded-xl border border-slate-200 text-sm font-semibold text-slate-600 hover:bg-slate-50 transition-colors disabled:opacity-50"
                  >
                    ← Back
                  </button>
                  <button
                    onClick={handleConfirmSend}
                    disabled={sendMutation.isPending}
                    className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold shadow-sm transition-all ${
                      sendMutation.isPending
                        ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                        : 'bg-blue-600 text-white hover:bg-blue-700 active:scale-95'
                    }`}
                  >
                    {sendMutation.isPending ? (
                      <><span className="material-symbols-outlined text-base animate-spin">progress_activity</span>Sending…</>
                    ) : (
                      <><span className="material-symbols-outlined text-base">send</span>Confirm & Send Email</>
                    )}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}