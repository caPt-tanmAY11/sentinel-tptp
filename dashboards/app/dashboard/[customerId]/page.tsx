'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { sentinelApi } from '@/lib/api';

// ── Helpers ───────────────────────────────────────────────────────────────────
const TIER_COLOR: Record<string, string> = {
  CRITICAL: '#DC2626', HIGH: '#EA580C', MODERATE: '#D97706',
  WATCH: '#CA8A04', STABLE: '#16A34A',
};
const TIER_BG: Record<string, string> = {
  CRITICAL: '#FEF2F2', HIGH: '#FFF7ED', MODERATE: '#FFFBEB',
  WATCH: '#FEFCE8', STABLE: '#F0FDF4',
};

function TierBadge({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-bold"
      style={{ color: TIER_COLOR[label] || '#16A34A', background: TIER_BG[label] || '#F0FDF4' }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: TIER_COLOR[label] || '#16A34A' }} />
      {label}
    </span>
  );
}

const fmtInr = (v: number) =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v);

const fmtTime = (iso: string) =>
  new Date(iso).toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: true });

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });

function severityColor(s: number): string {
  if (s >= 0.75) return '#DC2626';
  if (s >= 0.55) return '#EA580C';
  if (s >= 0.40) return '#D97706';
  if (s >= 0.10) return '#CA8A04';
  return '#16A34A';
}

// ── Section header ─────────────────────────────────────────────────────────────
function SectionHeader({ icon, title, sub }: { icon: string; title: string; sub?: string }) {
  return (
    <div className="flex items-center gap-3 mb-5">
      <div className="w-9 h-9 rounded-xl flex items-center justify-center"
        style={{ background: 'linear-gradient(135deg,#2b4bb918,#4865d318)' }}>
        <span className="material-symbols-outlined text-lg text-blue-700"
          style={{ fontVariationSettings: "'FILL' 1" }}>{icon}</span>
      </div>
      <div>
        <h3 className="font-headline font-bold text-base text-on-surface leading-tight">{title}</h3>
        {sub && <p className="text-[10px] font-label font-bold uppercase tracking-widest text-slate-400">{sub}</p>}
      </div>
    </div>
  );
}

// ── Info row ──────────────────────────────────────────────────────────────────
function InfoRow({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex justify-between items-center py-2.5"
      style={{ borderBottom: '1px solid rgba(195,198,215,0.15)' }}>
      <span className="text-xs text-slate-400 font-medium">{label}</span>
      <span className={`text-sm font-semibold text-on-surface ${mono ? 'font-mono' : ''}`}>{value ?? '—'}</span>
    </div>
  );
}

// ── Loan status badge ──────────────────────────────────────────────────────────
function LoanStatusBadge({ status }: { status: string }) {
  const cfg: Record<string, { c: string; bg: string }> = {
    ACTIVE:       { c: '#16A34A', bg: '#F0FDF4' },
    CLOSED:       { c: '#64748B', bg: '#F1F5F9' },
    NPA:          { c: '#DC2626', bg: '#FEF2F2' },
    RESTRUCTURED: { c: '#D97706', bg: '#FFFBEB' },
  };
  const s = cfg[status] || cfg.CLOSED;
  return (
    <span className="px-2.5 py-0.5 rounded-full text-xs font-bold"
      style={{ color: s.c, background: s.bg }}>{status}</span>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function CustomerDetailPage() {
  const { customerId } = useParams<{ customerId: string }>();
  const router = useRouter();

  const { data: pulse, isLoading: pulseLoading } = useQuery({
    queryKey: ['pulse', customerId],
    queryFn:  () => sentinelApi.getCustomerPulse(customerId).then(r => r.data),
    refetchInterval: 15_000,
  });

  const { data: histData, isLoading: histLoading } = useQuery({
    queryKey: ['pulse-history', customerId],
    queryFn:  () => sentinelApi.getCustomerPulseHistory(customerId, 60).then(r => r.data),
    refetchInterval: 15_000,
  });

  const { data: baseline } = useQuery({
    queryKey: ['baseline', customerId],
    queryFn:  () => sentinelApi.getCustomerBaseline(customerId).then(r => r.data),
  });

  const { data: profile } = useQuery({
    queryKey: ['profile', customerId],
    queryFn:  () => sentinelApi.getCustomerProfile(customerId).then(r => r.data),
  });

  const { data: loansData } = useQuery({
    queryKey: ['loans', customerId],
    queryFn:  () => sentinelApi.getCustomerLoans(customerId).then(r => r.data),
  });

  const { data: cardsData } = useQuery({
    queryKey: ['cards', customerId],
    queryFn:  () => sentinelApi.getCustomerCreditCards(customerId).then(r => r.data),
  });

  const { data: txnData } = useQuery({
    queryKey: ['transactions', customerId],
    queryFn:  () => sentinelApi.getCustomerTransactions(customerId, 50).then(r => r.data),
    refetchInterval: 15_000,
  });

  const { data: fraudData } = useQuery({
    queryKey: ['fraud-alerts', customerId],
    queryFn:  () => sentinelApi.getCustomerFraudAlerts(customerId).then(r => r.data),
    refetchInterval: 15_000,
  });

  const events: any[]  = histData?.events || [];
  const loans: any[]   = loansData?.loans || [];
  const cards: any[]   = cardsData?.credit_cards || [];
  const rawTxns: any[] = txnData?.transactions || [];
  const fraudAlerts: any[] = fraudData?.fraud_alerts || [];
  const openAlerts = fraudAlerts.filter((a: any) => a.status === 'OPEN' || a.status === 'REVIEWED');

  const [selectedAlert, setSelectedAlert] = useState<any>(null);
  const [isReviewModalOpen, setIsReviewModalOpen] = useState(false);
  const [isActioning, setIsActioning] = useState(false);
  const queryClient = useQueryClient();

  const chartData = [...events].reverse().map((e, i) => ({
    idx:   i + 1,
    score: parseFloat((e.pulse_score_after * 100).toFixed(1)),
    sev:   parseFloat((e.txn_severity * 100).toFixed(1)),
    time:  fmtTime(e.event_ts),
  }));

  const topFeatures: any[] = events[0]?.top_features || [];
  const riskLabel    = pulse?.risk_label ?? 'STABLE';
  const currentScore = pulse?.pulse_score ?? 0;

  const baselineScore = chartData.length > 0
    ? chartData.reduce((acc, d) => acc + d.score, 0) / chartData.length
    : undefined;

  if (pulseLoading || histLoading) return (
    <div className="flex items-center justify-center py-20">
      <div className="flex flex-col items-center gap-4">
        <div className="animate-spin h-10 w-10 rounded-full border-2 border-blue-500 border-t-transparent" />
        <p className="text-slate-400 text-sm font-label">Loading customer data…</p>
      </div>
    </div>
  );

  return (
    <div>

      {/* ── Header ── */}
      <header className="sticky top-0 z-30"
        style={{ background: 'rgba(247,249,251,0.85)', backdropFilter: 'blur(20px)', borderBottom: '1px solid rgba(195,198,215,0.2)' }}>
        <div className="max-w-[1400px] mx-auto px-6 py-4 flex items-center gap-4">
          <button onClick={() => router.back()}
            className="p-2 rounded-xl hover:bg-white/70 transition text-slate-400 hover:text-slate-700">
            <span className="material-symbols-outlined">arrow_back</span>
          </button>
          <div className="flex-1 min-w-0">
            <h1 className="font-headline font-bold text-lg text-on-surface leading-tight truncate">
              {profile?.full_name ?? 'Customer Detail'}
            </h1>
            <p className="text-xs text-slate-400 font-mono">{customerId}</p>
          </div>
          {openAlerts.length > 0 && (
            <button
               onClick={() => { setSelectedAlert(openAlerts[0]); setIsReviewModalOpen(true); }}
               className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-bold bg-red-100 text-red-700 hover:bg-red-200 transition"
            >
              <span className="material-symbols-outlined text-[16px]">warning</span>
              Fraud Alert Detected ({openAlerts.length})
            </button>
          )}
          <TierBadge label={riskLabel} />
        </div>
      </header>

      <div className="max-w-[1400px] mx-auto px-6 py-6 space-y-5">

        {/* ── Row 1: Pulse hero + Customer Profile ── */}
        <div className="grid grid-cols-12 gap-5">

          {/* Pulse Score Hero */}
          <div className="col-span-12 lg:col-span-4 glass-card rounded-2xl p-6 ambient-shadow-sm">
            <SectionHeader icon="monitoring" title="Pulse Score" sub="Real-time risk signal" />

            {/* Gauge */}
            <div className="flex justify-center mb-5">
              <div className="relative w-40 h-40">
                <svg viewBox="0 0 120 120" className="w-full h-full -rotate-90">
                  <circle cx="60" cy="60" r="52" fill="none" stroke="rgba(0,0,0,0.06)" strokeWidth="12" />
                  <circle cx="60" cy="60" r="52" fill="none"
                    stroke={TIER_COLOR[riskLabel] || '#16A34A'} strokeWidth="12"
                    strokeDasharray={`${currentScore * 326.7} 326.7`}
                    strokeLinecap="round" className="transition-all duration-700" />
                  <defs>
                    <linearGradient id="scoreGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                      <stop offset="0%" stopColor="#2b4bb9" />
                      <stop offset="100%" stopColor="#4865d3" />
                    </linearGradient>
                  </defs>
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <span className="text-4xl font-headline font-extrabold text-on-surface">
                    {(currentScore * 100).toFixed(0)}
                  </span>
                  <span className="text-[10px] text-slate-400 font-label font-bold uppercase tracking-widest -mt-1">/ 100</span>
                </div>
              </div>
            </div>

            {/* Score grid */}
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: 'Risk Tier',      value: <TierBadge label={riskLabel} /> },
                { label: 'Raw Score',      value: currentScore.toFixed(5), mono: true },
                { label: 'Events Scored',  value: (pulse?.score_count ?? 0).toLocaleString('en-IN') },
                { label: 'Last Updated',   value: pulse?.last_updated ? fmtTime(pulse.last_updated) : '—' },
                { label: 'Baseline Txns',  value: baseline?.transaction_count?.toLocaleString?.() ?? '—' },
                { label: 'Confidence',     value: baseline?.low_confidence ? '⚠ Low' : '✓ High' },
              ].map(s => (
                <div key={s.label} className="rounded-xl p-3"
                  style={{ background: 'rgba(242,244,246,0.7)' }}>
                  <p className="text-[10px] text-slate-400 mb-1 font-label font-bold uppercase tracking-wide">{s.label}</p>
                  <div className={`text-sm font-semibold text-on-surface ${(s as any).mono ? 'font-mono' : ''}`}>{s.value}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Customer Profile */}
          <div className="col-span-12 lg:col-span-8 glass-card rounded-2xl p-6 ambient-shadow-sm">
            <SectionHeader icon="person" title="Customer Profile" sub="Identity & demographics" />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8">
              <div>
                <InfoRow label="Full Name"          value={profile?.full_name} />
                <InfoRow label="Date of Birth"      value={profile?.date_of_birth ? fmtDate(profile.date_of_birth) : '—'} />
                <InfoRow label="Gender"             value={profile?.gender} />
                <InfoRow label="PAN Number"         value={profile?.pan_number} mono />
                <InfoRow label="Email"              value={profile?.email} />
                <InfoRow label="Phone"              value={profile?.phone} mono />
                <InfoRow label="City"               value={profile?.city} />
                <InfoRow label="State"              value={profile?.state} />
                <InfoRow label="Pincode"            value={profile?.pincode} mono />
              </div>
              <div>
                <InfoRow label="Employment Type"    value={profile?.employment_type} />
                <InfoRow label="Employer"           value={profile?.employer_name} />
                <InfoRow label="Monthly Income"     value={profile?.monthly_income ? fmtInr(profile.monthly_income) : '—'} />
                <InfoRow label="Salary Day"         value={profile?.expected_salary_day ? `Day ${profile.expected_salary_day}` : '—'} />
                <InfoRow label="Segment"            value={profile?.customer_segment} />
                <InfoRow label="Account ID"         value={profile?.account_id} mono />
                <InfoRow label="Account Number"     value={profile?.account_number} mono />
                <InfoRow label="Account Type"       value={profile?.account_type} />
                <InfoRow label="IFSC Code"          value={profile?.ifsc_code} mono />
                <InfoRow label="UPI VPA"            value={profile?.upi_vpa} mono />
                <InfoRow label="Credit Bureau Score" value={profile?.credit_bureau_score} />
                <InfoRow label="Delinquency Count"  value={profile?.historical_delinquency_count} />
                <InfoRow label="Customer Since"     value={profile?.account_open_date ? fmtDate(profile.account_open_date) : '—'} />
                <InfoRow label="Vintage (months)"   value={profile?.customer_vintage_months} />
                <InfoRow label="Geography Risk"     value={profile?.geography_risk_tier ? `Tier ${profile.geography_risk_tier}` : '—'} />
              </div>
            </div>
          </div>
        </div>

        {/* ── Row 2: Pulse Timeline ── */}
        <div className="glass-card rounded-2xl p-6 ambient-shadow-sm">
          <SectionHeader icon="timeline" title="Pulse Score Timeline" sub={`Last ${chartData.length} transactions`} />
          {chartData.length === 0 ? (
            <div className="h-48 flex items-center justify-center text-slate-400 text-sm">
              No transaction events yet.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.04)" />
                <XAxis dataKey="idx" tick={{ fontSize: 10, fill: '#94A3B8' }}
                  label={{ value: 'Transaction #', position: 'insideBottom', offset: -2, fontSize: 10, fill: '#94A3B8' }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#94A3B8' }} width={32} />
                <Tooltip
                  contentStyle={{ borderRadius: 12, border: 'none', background: 'rgba(255,255,255,0.95)', boxShadow: '0 4px 24px rgba(0,0,0,0.08)', fontSize: 11 }}
                  formatter={(v: any, n: string) => [n === 'score' ? `${v}/100` : `${v}%`, n === 'score' ? 'Pulse' : 'Severity']}
                  labelFormatter={(_: any, payload: any[]) => payload?.[0]?.payload?.time || ''} />
                {[
                  { y: 75, color: '#DC2626', label: 'CRITICAL' },
                  { y: 55, color: '#EA580C', label: 'HIGH' },
                  { y: 40, color: '#D97706', label: 'MODERATE' },
                  { y: 25, color: '#CA8A04', label: 'WATCH' },
                ].map(t => (
                  <ReferenceLine key={t.label} y={t.y} stroke={t.color}
                    strokeDasharray="4 3" strokeOpacity={0.4}
                    label={{ value: t.label, position: 'right', fontSize: 9, fill: t.color }} />
                ))}
                
                {baselineScore !== undefined && (
                  <ReferenceLine y={baselineScore} stroke="#475569" strokeWidth={2} strokeDasharray="3 3"
                    label={{ value: 'BASELINE AVG', position: 'insideTopLeft', fontSize: 10, fill: '#475569', fontWeight: 'bold' }} />
                )}

                <Line type="monotone" dataKey="score" stroke="#2b4bb9" strokeWidth={2.5}
                  dot={false} activeDot={{ r: 5, fill: '#2b4bb9' }} name="score" />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* ── Row 3: Loans + Credit Cards ── */}
        <div className="grid grid-cols-12 gap-5">

          {/* Loans */}
          <div className="col-span-12 lg:col-span-7 glass-card rounded-2xl p-6 ambient-shadow-sm">
            <SectionHeader icon="account_balance" title="Loan Accounts" sub={`${loans.length} active loan(s)`} />
            {loans.length === 0 ? (
              <p className="text-slate-400 text-sm text-center py-8">No loans found for this customer.</p>
            ) : (
              <div className="space-y-4">
                {loans.map((loan: any) => (
                  <div key={loan.loan_id} className="rounded-2xl p-4"
                    style={{ background: 'rgba(242,244,246,0.6)' }}>
                    <div className="flex items-center justify-between mb-3">
                      <div>
                        <span className="text-sm font-headline font-bold text-on-surface">{loan.loan_type} Loan</span>
                        <p className="text-xs font-mono text-slate-400 mt-0.5">{loan.loan_account_number}</p>
                      </div>
                      <LoanStatusBadge status={loan.status} />
                    </div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                      {[
                        { label: 'Sanctioned',         value: fmtInr(loan.sanctioned_amount) },
                        { label: 'Outstanding',        value: fmtInr(loan.outstanding_principal) },
                        { label: 'EMI Amount',         value: fmtInr(loan.emi_amount) },
                        { label: 'EMI Due Date',       value: loan.emi_due_date ? `Day ${loan.emi_due_date}` : '—' },
                        { label: 'Interest Rate',      value: `${loan.interest_rate}% p.a.` },
                        { label: 'Tenure',             value: `${loan.tenure_months} months` },
                        { label: 'Remaining Tenure',   value: `${loan.remaining_tenure} months` },
                        { label: 'Disbursement Date',  value: loan.disbursement_date ? fmtDate(loan.disbursement_date) : '—' },
                        { label: 'Days Past Due',      value: loan.days_past_due ?? 0,       warn: loan.days_past_due > 0 },
                        { label: 'Failed Debits (30d)',value: loan.failed_auto_debit_count_30d ?? 0, warn: loan.failed_auto_debit_count_30d > 0 },
                      ].map(f => (
                        <div key={f.label} className="bg-white/60 rounded-xl p-2.5">
                          <p className="text-[10px] text-slate-400 font-bold uppercase tracking-wide mb-1">{f.label}</p>
                          <p className={`text-sm font-semibold ${(f as any).warn ? 'text-red-500' : 'text-on-surface'}`}>{f.value}</p>
                        </div>
                      ))}
                    </div>
                    {/* Repayment progress */}
                    <div className="mt-3">
                      <div className="flex justify-between text-[10px] text-slate-400 mb-1">
                        <span>Repayment Progress</span>
                        <span>{Math.round(((loan.tenure_months - loan.remaining_tenure) / loan.tenure_months) * 100)}%</span>
                      </div>
                      <div className="h-1.5 rounded-full" style={{ background: 'rgba(0,0,0,0.07)' }}>
                        <div className="h-full rounded-full transition-all"
                          style={{
                            width: `${Math.round(((loan.tenure_months - loan.remaining_tenure) / loan.tenure_months) * 100)}%`,
                            background: loan.days_past_due > 0 ? '#DC2626' : '#2b4bb9',
                          }} />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Credit Cards */}
          <div className="col-span-12 lg:col-span-5 glass-card rounded-2xl p-6 ambient-shadow-sm">
            <SectionHeader icon="credit_card" title="Credit Cards" sub={`${cards.length} card(s)`} />
            {cards.length === 0 ? (
              <p className="text-slate-400 text-sm text-center py-8">No credit cards found.</p>
            ) : (
              <div className="space-y-4">
                {cards.map((card: any) => {
                  const utilPct = Math.min(100, card.credit_utilization_pct ?? 0);
                  const utilColor = utilPct >= 90 ? '#DC2626' : utilPct >= 70 ? '#EA580C' : utilPct >= 50 ? '#D97706' : '#16A34A';
                  return (
                    <div key={card.card_id} className="rounded-2xl p-4 overflow-hidden relative"
                      style={{ background: 'linear-gradient(135deg, #2b4bb9, #4865d3)' }}>
                      {/* Card shine */}
                      <div className="absolute -right-8 -top-8 w-32 h-32 rounded-full"
                        style={{ background: 'rgba(255,255,255,0.08)' }} />
                      <div className="relative">
                        <div className="flex items-center justify-between mb-4">
                          <span className="material-symbols-outlined text-white/80 text-2xl"
                            style={{ fontVariationSettings: "'FILL' 1" }}>credit_card</span>
                          <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                            card.status === 'ACTIVE' ? 'bg-white/20 text-white' : 'bg-white/10 text-white/60'
                          }`}>{card.status}</span>
                        </div>
                        <p className="text-white/60 text-[10px] font-mono mb-0.5">{card.card_account_number}</p>
                        <p className="text-white text-lg font-headline font-bold">{fmtInr(card.credit_limit)}</p>
                        <p className="text-white/60 text-[10px] font-bold uppercase tracking-widest mb-4">Credit Limit</p>
                        <div className="grid grid-cols-2 gap-3 mb-3">
                          <div>
                            <p className="text-white/50 text-[10px] uppercase tracking-wide mb-0.5">Balance</p>
                            <p className="text-white font-bold text-sm">{fmtInr(card.current_balance ?? 0)}</p>
                          </div>
                          <div>
                            <p className="text-white/50 text-[10px] uppercase tracking-wide mb-0.5">Min Due</p>
                            <p className={`font-bold text-sm ${!card.min_payment_made ? 'text-red-300' : 'text-white'}`}>
                              {fmtInr(card.min_payment_due ?? 0)}
                            </p>
                          </div>
                          <div>
                            <p className="text-white/50 text-[10px] uppercase tracking-wide mb-0.5">Due Date</p>
                            <p className="text-white font-bold text-sm">{card.payment_due_date ? `Day ${card.payment_due_date}` : '—'}</p>
                          </div>
                          <div>
                            <p className="text-white/50 text-[10px] uppercase tracking-wide mb-0.5">Bureau Enquiries (90d)</p>
                            <p className={`font-bold text-sm ${(card.bureau_enquiry_count_90d ?? 0) > 3 ? 'text-red-300' : 'text-white'}`}>
                              {card.bureau_enquiry_count_90d ?? 0}
                            </p>
                          </div>
                        </div>
                        {/* Utilization bar */}
                        <div>
                          <div className="flex justify-between text-[10px] text-white/60 mb-1">
                            <span>Utilization</span>
                            <span style={{ color: utilPct > 70 ? '#FCA5A5' : 'rgba(255,255,255,0.7)' }}>{utilPct.toFixed(1)}%</span>
                          </div>
                          <div className="h-1.5 rounded-full bg-white/20">
                            <div className="h-full rounded-full transition-all"
                              style={{ width: `${utilPct}%`, background: utilColor }} />
                          </div>
                        </div>
                        {!card.min_payment_made && (
                          <div className="mt-3 flex items-center gap-2 text-red-300 text-xs font-bold">
                            <span className="material-symbols-outlined text-sm"
                              style={{ fontVariationSettings: "'FILL' 1" }}>warning</span>
                            Minimum payment not made
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* ── Row 4: SHAP + Pulse Events ── */}
        <div className="grid grid-cols-12 gap-5">
          {/* SHAP Features */}
          <div className="col-span-12 lg:col-span-4 glass-card rounded-2xl p-6 ambient-shadow-sm">
            <SectionHeader icon="psychology" title="Top Score Drivers" sub="SHAP feature attribution" />
            {topFeatures.length === 0 ? (
              <p className="text-xs text-slate-400 py-8 text-center">No SHAP data yet.</p>
            ) : (
              <div className="space-y-3">
                {topFeatures.map((f: any, i: number) => {
                  const isStress = f.direction === 'stress';
                  const barColor = isStress ? '#DC2626' : '#16A34A';
                  const maxAbs   = Math.max(...topFeatures.map((x: any) => Math.abs(x.shap)));
                  const pct      = maxAbs > 0 ? (Math.abs(f.shap) / maxAbs) * 100 : 0;
                  return (
                    <div key={i}>
                      <div className="flex justify-between items-center mb-1">
                        <span className="text-xs text-on-surface-variant truncate pr-2" title={f.feature}>
                          {f.feature.replace(/_/g, ' ')}
                        </span>
                        <span className="text-xs font-mono font-bold flex-shrink-0"
                          style={{ color: barColor }}>
                          {isStress ? '+' : ''}{f.shap.toFixed(3)}
                        </span>
                      </div>
                      <div className="h-1.5 rounded-full" style={{ background: 'rgba(0,0,0,0.06)' }}>
                        <div className="h-full rounded-full transition-all"
                          style={{ width: `${pct}%`, background: barColor }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Pulse Events */}
          <div className="col-span-12 lg:col-span-8 glass-card rounded-2xl ambient-shadow-sm flex flex-col">
            <div className="px-5 py-4" style={{ borderBottom: '1px solid rgba(195,198,215,0.15)' }}>
              <h3 className="font-headline font-bold text-base text-on-surface">Transaction Pulse Events</h3>
              <p className="text-[10px] font-label font-bold uppercase tracking-widest text-slate-400 mt-0.5">Most recent first</p>
            </div>
            <div className="overflow-y-auto flex-1" style={{ maxHeight: 380 }}>
              {events.length === 0 ? (
                <div className="p-8 text-center text-sm text-slate-400">No pulse events yet.</div>
              ) : events.map((e: any, i: number) => {
                const isStress = e.severity_direction === 'positive';
                const isRelief = e.severity_direction === 'negative';
                return (
                  <div key={i} className="px-5 py-3.5 flex items-start gap-3 hover:bg-white/40 transition-colors"
                    style={{ borderBottom: '1px solid rgba(195,198,215,0.1)' }}>
                    <div className={`mt-0.5 w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 ${
                      isStress ? 'bg-red-50' : isRelief ? 'bg-green-50' : 'bg-slate-100'
                    }`}>
                      <span className="material-symbols-outlined text-sm"
                        style={{
                          color: isStress ? '#DC2626' : isRelief ? '#16A34A' : '#94A3B8',
                          fontVariationSettings: "'FILL' 1",
                        }}>
                        {isStress ? 'trending_up' : isRelief ? 'trending_down' : 'remove'}
                      </span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-semibold text-on-surface">
                          {e.inferred_category.replace(/_/g, ' ')}
                        </span>
                        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded font-bold"
                          style={{ background: `${severityColor(e.txn_severity)}15`, color: severityColor(e.txn_severity) }}>
                          sev {e.txn_severity.toFixed(3)}
                        </span>
                        <span className={`text-[10px] font-mono font-bold ${
                          e.delta_applied > 0 ? 'text-red-500' : e.delta_applied < 0 ? 'text-green-600' : 'text-slate-400'
                        }`}>
                          {e.delta_applied > 0 ? '+' : ''}{e.delta_applied.toFixed(4)}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 mt-0.5 text-xs text-slate-400">
                        <span>{fmtInr(e.amount)} · {e.platform}</span>
                        <span>{fmtTime(e.event_ts)}</span>
                      </div>
                      <div className="flex items-center gap-1 mt-1 text-xs">
                        <span className="text-slate-400 font-mono">{e.pulse_score_before.toFixed(3)}</span>
                        <span className="material-symbols-outlined text-sm text-slate-300">
                          {isStress ? 'trending_up' : isRelief ? 'trending_down' : 'remove'}
                        </span>
                        <span className="font-mono font-bold"
                          style={{ color: severityColor(e.pulse_score_after) }}>
                          {e.pulse_score_after.toFixed(3)}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* ── Row 5: Raw Transactions ── */}
        <div className="glass-card rounded-2xl ambient-shadow-sm">
          <div className="px-6 py-5" style={{ borderBottom: '1px solid rgba(195,198,215,0.15)' }}>
            <SectionHeader icon="receipt_long" title="Transaction History" sub={`Last ${rawTxns.length} transactions (raw)`} />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm tonal-table">
              <thead>
                <tr style={{ background: 'rgba(242,244,246,0.6)' }}>
                  {['Date & Time', 'Amount', 'Platform', 'Status', 'Sender', 'Receiver', 'Bal Before', 'Bal After', 'Reference'].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-[10px] font-label font-bold text-slate-400 uppercase tracking-widest whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rawTxns.length === 0 ? (
                  <tr><td colSpan={9} className="text-center py-12 text-slate-400 text-sm">No transactions found.</td></tr>
                ) : rawTxns.map((t: any) => (
                  <tr key={t.transaction_id} className="hover:bg-white/40 transition-colors">
                    <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">{fmtTime(t.txn_timestamp)}</td>
                    <td className="px-4 py-3 font-semibold text-on-surface whitespace-nowrap">{fmtInr(t.amount)}</td>
                    <td className="px-4 py-3">
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-blue-50 text-blue-700">{t.platform}</span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                        t.payment_status === 'success'  ? 'bg-green-50 text-green-700' :
                        t.payment_status === 'failed'   ? 'bg-red-50 text-red-700' :
                        t.payment_status === 'pending'  ? 'bg-yellow-50 text-yellow-700' :
                        'bg-slate-100 text-slate-500'
                      }`}>{t.payment_status}</span>
                    </td>
                    <td className="px-4 py-3 max-w-[160px]">
                      <p className="text-xs text-on-surface truncate">{t.sender_name || '—'}</p>
                      <p className="text-[10px] font-mono text-slate-400 truncate">{t.sender_id || ''}</p>
                    </td>
                    <td className="px-4 py-3 max-w-[160px]">
                      <p className="text-xs text-on-surface truncate">{t.receiver_name || '—'}</p>
                      <p className="text-[10px] font-mono text-slate-400 truncate">{t.receiver_id || ''}</p>
                    </td>
                    <td className="px-4 py-3 text-xs font-mono text-slate-500 whitespace-nowrap">
                      {t.balance_before != null ? fmtInr(t.balance_before) : '—'}
                    </td>
                    <td className="px-4 py-3 text-xs font-mono text-slate-500 whitespace-nowrap">
                      {t.balance_after != null ? fmtInr(t.balance_after) : '—'}
                    </td>
                    <td className="px-4 py-3 text-[10px] font-mono text-slate-400 max-w-[120px] truncate">
                      {t.reference_number || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

      </div>

      {/* ── Review Modal ── */}
      {isReviewModalOpen && selectedAlert && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm" style={{ margin: 0 }}>
          <div className="bg-white rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden flex flex-col">
            <div className="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-red-50">
              <div className="flex items-center gap-3">
                <span className="material-symbols-outlined text-red-600">gavel</span>
                <h2 className="font-headline font-bold text-lg text-red-900">Review Fraud Alert</h2>
              </div>
              <button onClick={() => !isActioning && setIsReviewModalOpen(false)} className="text-slate-400 hover:text-slate-700">
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>
            <div className="p-6 space-y-4 flex-1 overflow-y-auto">
              <div className="bg-slate-50 p-4 rounded-xl space-y-2">
                <InfoRow label="Alert ID" value={selectedAlert.alert_id} mono />
                <InfoRow label="Transaction Amount" value={fmtInr(selectedAlert.txn_amount)} />
                <InfoRow label="Platform" value={selectedAlert.platform} />
                <InfoRow label="Receiver Country" value={selectedAlert.receiver_country || 'IN'} />
                <InfoRow label="Currency" value={selectedAlert.currency || 'INR'} />
                <InfoRow label="Fraud Score" value={selectedAlert.fraud_score?.toFixed(3)} />
                <div className="pt-3 border-t border-slate-200 mt-2">
                  <span className="text-xs text-slate-500 font-medium block mb-2">Triggered Signals:</span>
                  <div className="flex gap-2 flex-wrap">
                    {selectedAlert.signal_international && <span className="text-[10px] px-2 py-1 bg-red-100 text-red-700 rounded font-bold border border-red-200">International Txn</span>}
                    {selectedAlert.signal_amount_spike && <span className="text-[10px] px-2 py-1 bg-red-100 text-red-700 rounded font-bold border border-red-200">Amount Spike</span>}
                    {selectedAlert.signal_freq_spike && <span className="text-[10px] px-2 py-1 bg-red-100 text-red-700 rounded font-bold border border-red-200">Frequency Spike</span>}
                  </div>
                </div>
                <div className="pt-3 mt-2">
                   <p className="text-sm text-slate-700 font-medium">
                     <strong className="text-slate-900">Reason:</strong> {selectedAlert.fraud_reason}
                   </p>
                </div>
              </div>
              {selectedAlert.payment_holiday_suggested && loans.length > 0 && loans[0].emi_due_date && (
                <div className="bg-amber-50 p-4 rounded-xl text-amber-900 text-sm border border-amber-200">
                  <span className="material-symbols-outlined text-amber-600 text-[18px] align-middle mr-1.5">event</span>
                  <strong>Payment Holiday Recommended:</strong> Customer has an EMI of {fmtInr(loans[0].emi_amount)} due on Day {loans[0].emi_due_date}. This alert will suggest a payment holiday in the notification email.
                </div>
              )}
            </div>
            <div className="px-6 py-4 border-t border-slate-100 bg-slate-50 flex justify-end gap-3">
              <button 
                onClick={() => setIsReviewModalOpen(false)} 
                disabled={isActioning}
                className="px-4 py-2 text-sm font-bold text-slate-600 hover:bg-slate-200 rounded-xl transition disabled:opacity-50">
                Cancel
              </button>
              <button 
                onClick={async () => {
                  setIsActioning(true);
                  try {
                    await sentinelApi.reviewFraudAlert(selectedAlert.alert_id, 'DISMISSED', 'Dashboard User', 'False alarm');
                    setIsReviewModalOpen(false);
                    queryClient.invalidateQueries({ queryKey: ['fraud-alerts', customerId] });
                  } catch(e) { console.error(e); }
                  setIsActioning(false);
                }}
                disabled={isActioning}
                className="px-4 py-2 text-sm font-bold text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 rounded-xl transition disabled:opacity-50">
                Dismiss Alert
              </button>
              <button 
                onClick={async () => {
                  setIsActioning(true);
                  try {
                    // 1. Send email
                    await sentinelApi.sendFraudAlertEmail({
                      alert_id: selectedAlert.alert_id,
                      customer_id: selectedAlert.customer_id,
                      first_name: profile?.first_name || 'Customer',
                      last_name: profile?.last_name || '',
                      txn_amount: selectedAlert.txn_amount,
                      platform: selectedAlert.platform,
                      receiver_vpa: selectedAlert.receiver_vpa,
                      receiver_country: selectedAlert.receiver_country,
                      currency: selectedAlert.currency,
                      fraud_score: selectedAlert.fraud_score,
                      fraud_reason: selectedAlert.fraud_reason,
                      signal_international: selectedAlert.signal_international,
                      signal_amount_spike: selectedAlert.signal_amount_spike,
                      signal_freq_spike: selectedAlert.signal_freq_spike,
                      payment_holiday_suggested: selectedAlert.payment_holiday_suggested,
                      next_emi_due_date: loans?.[0]?.emi_due_date ? `Day ${loans[0].emi_due_date}` : null,
                      emi_amount: loans?.[0]?.emi_amount,
                    });
                    // 2. Mark confirmed in DB (which updates status to CONFIRMED)
                    await sentinelApi.reviewFraudAlert(selectedAlert.alert_id, 'CONFIRMED', 'Dashboard User');
                    setIsReviewModalOpen(false);
                    queryClient.invalidateQueries({ queryKey: ['fraud-alerts', customerId] });
                  } catch(e) { console.error(e); }
                  setIsActioning(false);
                }}
                disabled={isActioning}
                className="px-4 py-2 text-sm font-bold text-white bg-red-600 hover:bg-red-700 rounded-xl transition flex items-center gap-2 disabled:opacity-70">
                {isActioning ? (
                  <><span className="animate-spin material-symbols-outlined text-[16px]">refresh</span> Processing...</>
                ) : (
                  <><span className="material-symbols-outlined text-[16px]">mail</span> Confirm & Notify Customer</>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}