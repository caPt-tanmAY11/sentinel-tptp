'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';

// ─── Types ────────────────────────────────────────────────────────────────────
interface TriggerTransaction {
  event_id: string;
  transaction_id: string;
  event_ts: string;
  amount: number;
  platform: string | null;
  receiver_id: string | null;
  inferred_category: string | null;
  txn_severity: number;
  pulse_score_before: number;
  pulse_score_after: number;
}

interface TransactionDispute {
  event_id: string;
  transaction_id: string;
  amount: number;
  inferred_category: string | null;
  event_ts: string;
  agreed: boolean | null;   // null = not yet chosen
  dispute_reason: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function formatCurrency(amount: number) {
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

function severityLabel(s: number) {
  if (s >= 0.8) return { label: 'Very High', color: '#b91c1c', bg: '#fee2e2' };
  if (s >= 0.6) return { label: 'High',      color: '#c2410c', bg: '#ffedd5' };
  if (s >= 0.4) return { label: 'Moderate',  color: '#b45309', bg: '#fef3c7' };
  return                { label: 'Low',       color: '#15803d', bg: '#dcfce7' };
}

// ─── Sub-components ───────────────────────────────────────────────────────────
function PageShell({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontFamily: 'Helvetica, Arial, sans-serif',
      backgroundColor: '#f1f5f9',
      minHeight: '100vh',
      padding: '32px 16px',
    }}>
      <div style={{ maxWidth: '680px', margin: '0 auto' }}>
        {/* Brand bar */}
        <div style={{ textAlign: 'center', marginBottom: '24px' }}>
          <div style={{ fontSize: '13px', color: '#64748b', fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
            Sentinel AI Security Operations
          </div>
        </div>
        {children}
        <div style={{ textAlign: 'center', fontSize: '12px', color: '#94a3b8', marginTop: '32px', paddingBottom: '24px' }}>
          &copy; {new Date().getFullYear()} Sentinel AI Security Operations. All rights reserved.
        </div>
      </div>
    </div>
  );
}

// ─── Transaction Card ─────────────────────────────────────────────────────────
function TransactionCard({
  txn,
  dispute,
  onAgree,
  onDisagree,
  onReasonChange,
}: {
  txn: TriggerTransaction;
  dispute: TransactionDispute;
  onAgree: () => void;
  onDisagree: () => void;
  onReasonChange: (val: string) => void;
}) {
  const sev = severityLabel(txn.txn_severity);

  return (
    <div style={{
      background: 'white',
      border: '1.5px solid',
      borderColor: dispute.agreed === false ? '#fca5a5' : dispute.agreed === true ? '#86efac' : '#e2e8f0',
      borderRadius: '12px',
      overflow: 'hidden',
      marginBottom: '16px',
      transition: 'border-color 0.2s',
    }}>
      {/* Transaction info row */}
      <div style={{ padding: '20px 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px', flexWrap: 'wrap' }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: '15px', fontWeight: 700, color: '#0f172a', marginBottom: '6px' }}>
            {formatCurrency(txn.amount)}
            {txn.platform && (
              <span style={{ fontSize: '12px', fontWeight: 500, color: '#64748b', marginLeft: '8px' }}>
                via {txn.platform}
              </span>
            )}
          </div>
          <div style={{ fontSize: '13px', color: '#475569', marginBottom: '4px' }}>
            <strong>Category:</strong> {formatCategory(txn.inferred_category)}
          </div>
          {txn.receiver_id && (
            <div style={{ fontSize: '13px', color: '#475569', marginBottom: '4px' }}>
              <strong>To:</strong> {txn.receiver_id}
            </div>
          )}
          <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>
            {formatDate(txn.event_ts)}
          </div>
        </div>
        {/* Severity badge */}
        <div style={{
          flexShrink: 0,
          background: sev.bg,
          color: sev.color,
          fontSize: '11px',
          fontWeight: 700,
          padding: '4px 10px',
          borderRadius: '6px',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
        }}>
          {sev.label} Stress Signal
        </div>
      </div>

      {/* Score delta bar */}
      <div style={{ padding: '0 24px 16px 24px' }}>
        <div style={{ fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>
          Risk score impact
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '13px' }}>
          <span style={{ color: '#475569' }}>{(txn.pulse_score_before * 100).toFixed(1)}%</span>
          <div style={{ flex: 1, height: '6px', background: '#f1f5f9', borderRadius: '3px', overflow: 'hidden' }}>
            <div style={{
              height: '100%',
              width: `${Math.min(txn.pulse_score_after * 100, 100)}%`,
              background: `linear-gradient(90deg, #f59e0b, #ef4444)`,
              borderRadius: '3px',
              transition: 'width 0.3s',
            }} />
          </div>
          <span style={{ color: '#dc2626', fontWeight: 700 }}>{(txn.pulse_score_after * 100).toFixed(1)}%</span>
        </div>
      </div>

      {/* Accept / Dispute buttons */}
      <div style={{
        padding: '14px 24px',
        background: '#f8fafc',
        borderTop: '1px solid #e2e8f0',
        display: 'flex',
        gap: '10px',
        alignItems: 'center',
        flexWrap: 'wrap',
      }}>
        <div style={{ fontSize: '13px', fontWeight: 600, color: '#374151', marginRight: '4px', flexShrink: 0 }}>
          Is this transaction accurate?
        </div>

        <button
          onClick={onAgree}
          style={{
            padding: '7px 16px',
            borderRadius: '7px',
            border: '1.5px solid',
            borderColor: dispute.agreed === true ? '#16a34a' : '#d1d5db',
            background: dispute.agreed === true ? '#dcfce7' : 'white',
            color: dispute.agreed === true ? '#15803d' : '#374151',
            fontSize: '13px',
            fontWeight: 600,
            cursor: 'pointer',
            transition: 'all 0.15s',
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
          }}
        >
          ✓ Yes, accurate
        </button>

        <button
          onClick={onDisagree}
          style={{
            padding: '7px 16px',
            borderRadius: '7px',
            border: '1.5px solid',
            borderColor: dispute.agreed === false ? '#dc2626' : '#d1d5db',
            background: dispute.agreed === false ? '#fee2e2' : 'white',
            color: dispute.agreed === false ? '#b91c1c' : '#374151',
            fontSize: '13px',
            fontWeight: 600,
            cursor: 'pointer',
            transition: 'all 0.15s',
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
          }}
        >
          ✗ I disagree
        </button>
      </div>

      {/* Dispute reason — only shown when disagreed */}
      {dispute.agreed === false && (
        <div style={{ padding: '16px 24px', borderTop: '1px solid #fca5a5', background: '#fff8f8' }}>
          <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, color: '#374151', marginBottom: '8px' }}>
            Please explain your concern with this transaction <span style={{ color: '#ef4444' }}>*</span>
          </label>
          <textarea
            value={dispute.dispute_reason}
            onChange={e => onReasonChange(e.target.value)}
            placeholder="e.g. This was a transfer to my family member, not a lending app..."
            rows={3}
            style={{
              width: '100%',
              padding: '10px 12px',
              borderRadius: '8px',
              border: '1.5px solid #fca5a5',
              fontSize: '14px',
              color: '#0f172a',
              outline: 'none',
              resize: 'vertical',
              fontFamily: 'inherit',
              lineHeight: 1.6,
              boxSizing: 'border-box',
              background: 'white',
            }}
            onFocus={e => { e.target.style.borderColor = '#dc2626'; }}
            onBlur={e => { e.target.style.borderColor = '#fca5a5'; }}
          />
        </div>
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────
export default function GrievancePage() {
  const params = useParams();
  const interventionId = params.interventionId as string;

  const [loading, setLoading]         = useState(true);
  const [fetchError, setFetchError]   = useState('');
  const [riskTier, setRiskTier]       = useState('');
  const [transactions, setTransactions] = useState<TriggerTransaction[]>([]);
  const [disputes, setDisputes]       = useState<TransactionDispute[]>([]);
  const [additionalNotes, setAdditionalNotes] = useState('');
  const [submitting, setSubmitting]   = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [submitted, setSubmitted]     = useState(false);

  const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';

  // ── Fetch trigger transactions on mount ───────────────────────────────────
  useEffect(() => {
    if (!interventionId) return;
    (async () => {
      try {
        const res = await fetch(`${apiBase}/interventions/${interventionId}/trigger-transactions`);
        if (!res.ok) throw new Error('Could not load transaction data.');
        const data = await res.json();
        setRiskTier(data.risk_tier || '');
        setTransactions(data.transactions || []);
        setDisputes((data.transactions || []).map((t: TriggerTransaction) => ({
          event_id:        t.event_id,
          transaction_id:  t.transaction_id,
          amount:          t.amount,
          inferred_category: t.inferred_category,
          event_ts:        t.event_ts,
          agreed:          null,
          dispute_reason:  '',
        })));
      } catch (e: any) {
        setFetchError(e.message || 'Failed to load transactions.');
      } finally {
        setLoading(false);
      }
    })();
  }, [interventionId]);

  // ── Dispute handlers ──────────────────────────────────────────────────────
  const setAgreed = (idx: number, agreed: boolean) => {
    setDisputes(prev => prev.map((d, i) =>
      i === idx ? { ...d, agreed, dispute_reason: agreed ? '' : d.dispute_reason } : d
    ));
  };

  const setReason = (idx: number, val: string) => {
    setDisputes(prev => prev.map((d, i) => i === idx ? { ...d, dispute_reason: val } : d));
  };

  // ── Validation ────────────────────────────────────────────────────────────
  const validate = (): string => {
    for (const d of disputes) {
      if (d.agreed === null) return 'Please respond (accurate / disagree) for every transaction listed.';
      if (d.agreed === false && !d.dispute_reason.trim()) return 'Please provide a reason for each transaction you disagree with.';
    }
    return '';
  };

  // ── Submit ────────────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    const validationErr = validate();
    if (validationErr) { setSubmitError(validationErr); return; }

    setSubmitting(true);
    setSubmitError('');

    try {
      const res = await fetch('/api/grievances/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          intervention_id:      interventionId,
          message:              additionalNotes.trim() || 'Transaction dispute submitted.',
          transaction_disputes: disputes.map(d => ({
            event_id:         d.event_id,
            transaction_id:   d.transaction_id,
            amount:           d.amount,
            inferred_category: d.inferred_category,
            event_ts:         d.event_ts,
            agreed:           d.agreed,
            dispute_reason:   d.agreed === false ? d.dispute_reason.trim() : null,
          })),
          additional_notes: additionalNotes.trim() || null,
        }),
      });

      const data = await res.json();
      if (!res.ok) { setSubmitError(data.error || 'Something went wrong. Please try again.'); return; }
      setSubmitted(true);
    } catch {
      setSubmitError('Network error. Please check your connection and try again.');
    } finally {
      setSubmitting(false);
    }
  };

  // ─── Success screen ───────────────────────────────────────────────────────
  if (submitted) {
    return (
      <PageShell>
        <div style={{
          background: 'white', padding: '48px', borderRadius: '16px',
          boxShadow: '0 10px 15px -3px rgba(0,0,0,0.1)',
          textAlign: 'center', borderTop: '6px solid #16a34a',
        }}>
          <div style={{
            width: '72px', height: '72px', background: '#dcfce7', borderRadius: '50%',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 24px auto',
          }}>
            <svg viewBox="0 0 24 24" width="36" height="36" fill="#16a34a">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
            </svg>
          </div>
          <h1 style={{ color: '#16a34a', fontSize: '26px', margin: '0 0 12px 0', fontWeight: 700 }}>
            Grievance Submitted
          </h1>
          <p style={{ color: '#475569', fontSize: '16px', lineHeight: 1.6, margin: '0 0 16px 0' }}>
            Thank you. Your dispute has been submitted to our credit officer team. We will review each transaction flagged and get back to you shortly.
          </p>
          <p style={{
            fontSize: '13px', background: '#f8fafc', padding: '14px',
            borderRadius: '8px', border: '1px solid #e2e8f0', color: '#64748b',
          }}>
            You may now safely close this window.
          </p>
        </div>
      </PageShell>
    );
  }

  // ─── Loading state ────────────────────────────────────────────────────────
  if (loading) {
    return (
      <PageShell>
        <div style={{ background: 'white', borderRadius: '16px', padding: '60px', textAlign: 'center', color: '#64748b' }}>
          <div style={{ fontSize: '16px' }}>Loading your transaction data...</div>
        </div>
      </PageShell>
    );
  }

  // ─── Fetch error ──────────────────────────────────────────────────────────
  if (fetchError) {
    return (
      <PageShell>
        <div style={{ background: 'white', borderRadius: '16px', padding: '60px', textAlign: 'center' }}>
          <p style={{ color: '#dc2626', fontSize: '15px' }}>{fetchError}</p>
          <p style={{ color: '#64748b', fontSize: '13px', marginTop: '8px' }}>
            Please contact your bank officer directly if this issue persists.
          </p>
        </div>
      </PageShell>
    );
  }

  // ─── Main form ────────────────────────────────────────────────────────────
  const disputedCount = disputes.filter(d => d.agreed === false).length;

  return (
    <PageShell>
      {/* Header card */}
      <div style={{
        background: 'white', borderRadius: '16px', borderTop: '6px solid #2563eb',
        boxShadow: '0 4px 6px -1px rgba(0,0,0,0.07)', padding: '32px 36px', marginBottom: '24px',
      }}>
        <h1 style={{ fontSize: '22px', fontWeight: 800, color: '#0f172a', margin: '0 0 8px 0' }}>
          Submit a Grievance
        </h1>
        <p style={{ color: '#64748b', fontSize: '14px', margin: 0, lineHeight: 1.6 }}>
          Below are the transactions our system flagged as stress signals contributing to your{' '}
          <strong style={{ color: riskTier === 'CRITICAL' ? '#b91c1c' : '#b45309' }}>{riskTier}</strong> risk tier.
          For each transaction, please confirm whether it is accurate or raise a dispute.
        </p>
      </div>

      {/* Transactions section */}
      <div style={{
        background: 'white', borderRadius: '16px', boxShadow: '0 4px 6px -1px rgba(0,0,0,0.07)',
        padding: '28px 32px', marginBottom: '20px',
      }}>
        <h2 style={{ fontSize: '15px', fontWeight: 700, color: '#374151', margin: '0 0 6px 0' }}>
          Flagged Transactions
        </h2>
        <p style={{ fontSize: '13px', color: '#64748b', margin: '0 0 20px 0' }}>
          {transactions.length > 0
            ? `${transactions.length} transaction${transactions.length > 1 ? 's' : ''} flagged. Please review each one.`
            : 'No individual transactions were flagged for this intervention.'}
        </p>

        {transactions.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#94a3b8', padding: '24px 0', fontSize: '14px' }}>
            No transaction details available to dispute.
          </div>
        ) : (
          disputes.map((d, idx) => (
            <TransactionCard
              key={d.event_id}
              txn={transactions[idx]}
              dispute={d}
              onAgree={() => setAgreed(idx, true)}
              onDisagree={() => setAgreed(idx, false)}
              onReasonChange={val => setReason(idx, val)}
            />
          ))
        )}
      </div>

      {/* Additional notes section */}
      <div style={{
        background: 'white', borderRadius: '16px', boxShadow: '0 4px 6px -1px rgba(0,0,0,0.07)',
        padding: '28px 32px', marginBottom: '20px',
      }}>
        <h2 style={{ fontSize: '15px', fontWeight: 700, color: '#374151', margin: '0 0 6px 0' }}>
          Any Other Queries or Comments?
        </h2>
        <p style={{ fontSize: '13px', color: '#64748b', margin: '0 0 14px 0' }}>
          Use this space to share anything else you'd like our credit officer team to know — financial context, upcoming repayments, or any other concerns.
        </p>
        <textarea
          value={additionalNotes}
          onChange={e => setAdditionalNotes(e.target.value)}
          rows={5}
          placeholder="e.g. I am expecting a salary credit by 5th of next month and will be able to clear my EMI then..."
          style={{
            width: '100%',
            padding: '12px 14px',
            borderRadius: '8px',
            border: '1.5px solid #e2e8f0',
            fontSize: '14px',
            color: '#0f172a',
            outline: 'none',
            resize: 'vertical',
            fontFamily: 'inherit',
            lineHeight: 1.6,
            boxSizing: 'border-box',
          }}
          onFocus={e => { e.target.style.borderColor = '#2563eb'; }}
          onBlur={e => { e.target.style.borderColor = '#e2e8f0'; }}
        />
      </div>

      {/* Submit */}
      <div style={{
        background: 'white', borderRadius: '16px', boxShadow: '0 4px 6px -1px rgba(0,0,0,0.07)',
        padding: '24px 32px',
      }}>
        {disputedCount > 0 && (
          <div style={{
            background: '#fff7ed', border: '1px solid #fed7aa', borderRadius: '8px',
            padding: '12px 16px', marginBottom: '16px', fontSize: '13px', color: '#c2410c',
          }}>
            ⚠ You have disputed {disputedCount} transaction{disputedCount > 1 ? 's' : ''}. Make sure you've provided a reason for each one before submitting.
          </div>
        )}

        {submitError && (
          <p style={{ color: '#dc2626', fontSize: '13px', marginBottom: '12px' }}>{submitError}</p>
        )}

        <button
          onClick={handleSubmit}
          disabled={submitting}
          style={{
            width: '100%',
            padding: '14px',
            backgroundColor: submitting ? '#93c5fd' : '#2563eb',
            color: 'white',
            border: 'none',
            borderRadius: '8px',
            fontSize: '16px',
            fontWeight: 600,
            cursor: submitting ? 'not-allowed' : 'pointer',
            transition: 'background-color 0.2s',
          }}
        >
          {submitting ? 'Submitting...' : 'Submit Grievance'}
        </button>
        <p style={{ textAlign: 'center', fontSize: '13px', color: '#94a3b8', marginTop: '12px' }}>
          Your response will be reviewed by our credit officer team.
        </p>
      </div>
    </PageShell>
  );
}