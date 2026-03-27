// dashboards/app/report/[customerId]/page.tsx
"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useSearchParams } from "next/navigation";

// ── Types ──────────────────────────────────────────────────────────────────

interface FlaggedTransaction {
  event_id: string;
  scored_at: string;
  amount: number;
  platform: string;
  category_label: string;
  inferred_category: string;
  severity: number;
  pulse_delta: number;
  new_pulse_score: number;
}

interface Report {
  report_id: string;
  reference_number: string;
  generated_at: string;
  customer: {
    customer_id: string;
    name: string;
    account_type: string;
    branch: string;
    credit_limit: number;
  };
  pulse_summary: {
    current_score: number;
    risk_tier: string;
    tier_number: number;
    intervention_window: string;
    total_stress_events: number;
  };
  flagged_transactions: FlaggedTransaction[];
  narrative_sections: {
    section_1: { title: string; content: string };
    section_2: { title: string; content: string };
    section_3_and_4: string;
    section_5: string;
    section_6: { title: string; content: string };
    section_7: { title: string; content: string };
    section_8: string;
    section_9: { title: string; content: string };
  };
  legal_checklist: Record<string, boolean>;
  ai_model_metadata: {
    model_name: string;
    llm_used: string;
    is_ai_assisted: boolean;
    human_review_required: boolean;
  };
  form_link: string;
}

// ── Constants ──────────────────────────────────────────────────────────────

const TIER_CONFIG: Record<string, { bg: string; text: string; icon: string }> = {
  CRITICAL: { bg: "bg-red-600",    text: "text-white",    icon: "🔴" },
  HIGH:     { bg: "bg-orange-500", text: "text-white",    icon: "🟠" },
  MODERATE: { bg: "bg-yellow-500", text: "text-gray-900", icon: "🟡" },
  WATCH:    { bg: "bg-blue-200",   text: "text-blue-900", icon: "🔵" },
  STABLE:   { bg: "bg-green-600",  text: "text-white",    icon: "🟢" },
};

const BARCLAYS_DARK = "#002C77";
const BARCLAYS_BLUE = "#00AEEF";
const API_BASE = process.env.NEXT_PUBLIC_SCORING_API_URL || "http://localhost:8001";

// ── API helpers ────────────────────────────────────────────────────────────

async function fetchReport(customerId: string): Promise<Report> {
  const res = await fetch(`${API_BASE}/report/generate/${customerId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      form_link: `${window.location.origin}/report/${customerId}/form`,
      stress_lookback_days: 30,
    }),
  });
  if (!res.ok) throw new Error(`Report generation failed: ${res.statusText}`);
  return res.json();
}

async function acknowledgeIntervention(interventionId: string): Promise<void> {
  const res = await fetch("/api/interventions/acknowledge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ interventionId }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.error || "Acknowledgement failed");
  }
}

// ── Satisfaction Modal ─────────────────────────────────────────────────────

function SatisfactionModal({
  onYes,
  onNo,
  loading,
}: {
  onYes: () => void;
  onNo: () => void;
  loading: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(0,0,0,0.55)", backdropFilter: "blur(3px)" }}>
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full overflow-hidden"
        style={{ borderTop: `5px solid ${BARCLAYS_DARK}` }}>

        {/* Header */}
        <div className="px-8 pt-8 pb-4 text-center">
          <div className="w-16 h-16 rounded-full bg-blue-50 flex items-center justify-center mx-auto mb-4">
            <svg viewBox="0 0 24 24" width="32" height="32" fill={BARCLAYS_DARK}>
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
            </svg>
          </div>
          <h2 className="text-xl font-bold text-gray-900 mb-2">
            Report Acknowledgement
          </h2>
          <p className="text-gray-500 text-sm leading-relaxed">
            You are about to formally acknowledge this compliance report.
            Before we proceed, please confirm the following:
          </p>
        </div>

        {/* Confirmation question */}
        <div className="mx-8 mb-6 bg-slate-50 border border-slate-200 rounded-xl p-5">
          <p className="text-gray-800 font-semibold text-sm text-center leading-relaxed">
            Are you satisfied with the contents of this report and do you
            agree that the information presented is accurate to your knowledge?
          </p>
        </div>

        {/* Buttons */}
        <div className="px-8 pb-8 flex flex-col gap-3">
          <button
            onClick={onYes}
            disabled={loading}
            className="w-full py-3.5 px-6 rounded-xl font-bold text-white text-sm transition-all
              hover:opacity-90 active:scale-[0.98] disabled:opacity-60 disabled:cursor-not-allowed
              flex items-center justify-center gap-2"
            style={{ backgroundColor: BARCLAYS_DARK }}
          >
            {loading ? (
              <>
                <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="white" strokeWidth="4"/>
                  <path className="opacity-75" fill="white" d="M4 12a8 8 0 018-8v8H4z"/>
                </svg>
                Processing…
              </>
            ) : (
              <>✅ Yes, I acknowledge this report</>
            )}
          </button>

          <button
            onClick={onNo}
            disabled={loading}
            className="w-full py-3.5 px-6 rounded-xl font-bold text-sm border-2 transition-all
              hover:bg-slate-50 active:scale-[0.98] disabled:opacity-60 disabled:cursor-not-allowed"
            style={{ borderColor: BARCLAYS_DARK, color: BARCLAYS_DARK }}
          >
            ❌ No, I have concerns — raise a grievance
          </button>
        </div>

        <div className="px-8 pb-6 text-center text-xs text-gray-400">
          This acknowledgement is legally binding under DPDPA 2023 and RBI guidelines.
        </div>
      </div>
    </div>
  );
}

// ── Success Screen ─────────────────────────────────────────────────────────

function AcknowledgedScreen() {
  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
      <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-10 text-center"
        style={{ borderTop: `5px solid #16a34a` }}>
        <div className="w-20 h-20 bg-green-50 rounded-full flex items-center justify-center mx-auto mb-6">
          <svg viewBox="0 0 24 24" width="44" height="44" fill="#16a34a">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
          </svg>
        </div>
        <h1 className="text-2xl font-bold text-green-700 mb-3">
          Report Acknowledged
        </h1>
        <p className="text-gray-500 text-sm leading-relaxed mb-6">
          Thank you. Your compliance report has been formally acknowledged and
          the record has been securely updated in the Sentinel AI system.
        </p>
        <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 text-xs text-gray-500">
          You may now safely close this window. A confirmation will be
          reflected on your officer's dashboard shortly.
        </div>
        <div className="mt-6 text-xs text-gray-400 border-t border-slate-100 pt-4">
          &copy; {new Date().getFullYear()} Sentinel AI Security Operations
        </div>
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function ReportPage() {
  const params         = useParams();
  const searchParams   = useSearchParams();
  const customerId     = params.customerId as string;
  const interventionId = searchParams.get("interventionId") || "";

  const [report,       setReport]       = useState<Report | null>(null);
  const [loading,      setLoading]      = useState(true);
  const [error,        setError]        = useState<string | null>(null);
  const [activeTab,    setActiveTab]    = useState<"report" | "transactions" | "audit">("report");

  // Scroll-lock state
  const [hasScrolled,  setHasScrolled]  = useState(false);
  const bottomRef                       = useRef<HTMLDivElement>(null);

  // Modal + acknowledgement state
  const [showModal,    setShowModal]    = useState(false);
  const [ackLoading,   setAckLoading]   = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);

  // ── Load report ──────────────────────────────────────────────────────

  useEffect(() => {
    if (!customerId) return;
    setLoading(true);
    fetchReport(customerId)
      .then(setReport)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [customerId]);

  // ── Scroll detection — unlock button when user reaches bottom ────────

  const handleScroll = useCallback(() => {
    if (hasScrolled) return;
    const scrollTop    = window.scrollY || document.documentElement.scrollTop;
    const windowHeight = window.innerHeight;
    const docHeight    = document.documentElement.scrollHeight;
    // Unlock when within 120px of the bottom
    if (scrollTop + windowHeight >= docHeight - 120) {
      setHasScrolled(true);
    }
  }, [hasScrolled]);

  useEffect(() => {
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, [handleScroll]);

  // ── Modal handlers ────────────────────────────────────────────────────

  const handleAcknowledgeClick = () => {
    setShowModal(true);
  };

  const handleYes = async () => {
    if (!interventionId) {
      alert("No intervention ID found. Please use the link from your email.");
      return;
    }
    setAckLoading(true);
    try {
      await acknowledgeIntervention(interventionId);
      setShowModal(false);
      setAcknowledged(true);
    } catch (err: any) {
      alert(`Acknowledgement failed: ${err.message}`);
    } finally {
      setAckLoading(false);
    }
  };

  const handleNo = () => {
    setShowModal(false);
    // Redirect to grievance page
    window.location.href = `/grievance/${interventionId}`;
  };

  // ── Render: acknowledged ─────────────────────────────────────────────

  if (acknowledged) return <AcknowledgedScreen />;

  // ── Render: loading ──────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-50">
        <div className="w-16 h-16 border-4 border-blue-600 border-t-transparent rounded-full animate-spin mb-4" />
        <p className="text-gray-600 font-medium">Generating compliance report…</p>
        <p className="text-gray-400 text-sm mt-1">
          Sentinel V2 AI is analysing transaction patterns
        </p>
      </div>
    );
  }

  // ── Render: error ────────────────────────────────────────────────────

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-50 p-8">
        <div className="bg-white rounded-xl shadow-lg p-8 max-w-lg w-full border border-red-200">
          <div className="text-4xl mb-4 text-center">⚠️</div>
          <h2 className="text-xl font-bold text-red-700 text-center mb-2">
            Report Generation Failed
          </h2>
          <p className="text-gray-600 text-center text-sm">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="mt-6 w-full bg-blue-600 text-white py-2 px-4 rounded-lg font-medium hover:bg-blue-700 transition"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!report) return null;

  const tier       = report.pulse_summary.risk_tier;
  const tierConfig = TIER_CONFIG[tier] || TIER_CONFIG.WATCH;

  // ── Main render ──────────────────────────────────────────────────────

  return (
    <>
      {/* Satisfaction modal (renders on top of everything) */}
      {showModal && (
        <SatisfactionModal
          onYes={handleYes}
          onNo={handleNo}
          loading={ackLoading}
        />
      )}

      <div className="min-h-screen bg-gray-50">

        {/* ── Barclays Header ──────────────────────────────────────── */}
        <header style={{ backgroundColor: BARCLAYS_DARK }} className="text-white shadow-lg sticky top-0 z-40">
          <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
            <div>
              <div className="text-xl font-bold tracking-wide">BARCLAYS</div>
              <div className="text-xs text-blue-200 mt-0.5">
                Sentinel V2 — Pre-Delinquency Intelligence Platform
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-xs text-blue-200 hidden md:block">
                {report.reference_number}
              </span>
              <button
                onClick={() => window.open(`${API_BASE}/report/pdf/${customerId}`, "_blank")}
                className="flex items-center gap-2 bg-white text-blue-900 px-4 py-2 rounded-lg text-sm font-bold hover:bg-blue-50 transition shadow"
              >
                📄 Download PDF
              </button>
            </div>
          </div>
          <div style={{ backgroundColor: BARCLAYS_BLUE }} className="h-1 w-full" />
        </header>

        {/* ── Regulatory notice banner ─────────────────────────────── */}
        <div className="bg-amber-50 border-b border-amber-200 px-4 py-2">
          <p className="max-w-7xl mx-auto text-xs text-amber-800 text-center font-medium">
            ⚠ THIS IS NOT A DEFAULT NOTICE OR DEMAND. This is a proactive
            customer-protection communication mandated by RBI/2023-24/18 and
            the IBA Pre-Delinquency Management Guidelines.
          </p>
        </div>

        {/* ── Scroll-lock notice bar ───────────────────────────────── */}
        {!hasScrolled && (
          <div className="bg-blue-600 text-white px-4 py-2.5 text-center text-sm font-medium">
            📖 Please scroll through the entire report to unlock the Acknowledge button ↓
          </div>
        )}

        {/* ── Risk Tier Banner ─────────────────────────────────────── */}
        <div className={`${tierConfig.bg} ${tierConfig.text} shadow`}>
          <div className="max-w-7xl mx-auto px-4 py-4">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-4">
                <span className="text-3xl">{tierConfig.icon}</span>
                <div>
                  <div className="text-lg font-bold">
                    Risk Tier: {tier} (Tier {report.pulse_summary.tier_number} of 5)
                  </div>
                  <div className="text-sm opacity-90">
                    Pulse Score: {report.pulse_summary.current_score.toFixed(4)} |{" "}
                    {report.pulse_summary.total_stress_events} stress event(s) detected
                  </div>
                </div>
              </div>
              <div className="text-right">
                <div className="text-xs opacity-80 font-medium uppercase tracking-wide">
                  Intervention Window
                </div>
                <div className="text-sm font-bold mt-0.5">
                  {report.pulse_summary.intervention_window}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ── Customer Summary ─────────────────────────────────────── */}
        <div className="max-w-7xl mx-auto px-4 pt-6">
          <div className="bg-white rounded-xl shadow border border-gray-200 p-6 mb-6">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                { label: "Customer Name",  value: report.customer.name },
                { label: "Account Type",   value: report.customer.account_type },
                { label: "Customer ID",    value: report.customer.customer_id.slice(0, 8) + "…" },
                { label: "Branch",         value: report.customer.branch },
              ].map(({ label, value }) => (
                <div key={label} className="bg-blue-50 rounded-lg p-3">
                  <div className="text-xs text-blue-700 font-semibold uppercase tracking-wider">
                    {label}
                  </div>
                  <div className="text-sm font-bold text-gray-800 mt-1">{value}</div>
                </div>
              ))}
            </div>
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-gray-500">
              <span>Reference:</span>
              <span className="font-mono text-gray-700">{report.reference_number}</span>
              <span className="text-gray-400">|</span>
              <span>Generated:</span>
              <span className="text-gray-700">
                {report.generated_at.slice(0, 19).replace("T", " ")} UTC
              </span>
            </div>
          </div>

          {/* ── Tab Navigation ───────────────────────────────────── */}
          <div className="flex border-b border-gray-200 mb-6 overflow-x-auto">
            {(["report", "transactions", "audit"] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-5 py-3 text-sm font-semibold capitalize transition whitespace-nowrap border-b-2 -mb-px ${
                  activeTab === tab
                    ? "border-blue-600 text-blue-700"
                    : "border-transparent text-gray-500 hover:text-gray-700"
                }`}
              >
                {tab === "report"       && "📋 Compliance Report"}
                {tab === "transactions" && "💳 Flagged Transactions"}
                {tab === "audit"        && "🔍 AI Model Audit"}
              </button>
            ))}
          </div>

          {/* ── Tab: Compliance Report ───────────────────────────── */}
          {activeTab === "report" && (
            <div className="space-y-6 pb-6">
              {/* Sections 1 & 2 */}
              {[
                { key: "section_1", label: "Section 1: Report Identification" },
                { key: "section_2", label: "Section 2: Scope & Purpose" },
              ].map(({ key, label }) => {
                const sec = (report.narrative_sections as any)[key];
                return (
                  <div key={key} className="bg-white rounded-xl shadow border border-gray-200 overflow-hidden">
                    <div style={{ backgroundColor: BARCLAYS_DARK }} className="px-5 py-3">
                      <h3 className="text-white font-bold text-sm uppercase tracking-wider">{label}</h3>
                    </div>
                    <div className="p-5">
                      <pre className="text-xs text-gray-700 whitespace-pre-wrap font-sans leading-relaxed">
                        {sec?.content || ""}
                      </pre>
                    </div>
                  </div>
                );
              })}

              {/* AI-assisted sections */}
              {[
                { key: "section_3_and_4", label: "Sections 3 & 4: Basis of Assessment & Regulatory Rationale" },
                { key: "section_5",       label: "Section 5: Proposed Intervention Methodology" },
              ].map(({ key, label }) => (
                <div key={key} className="bg-white rounded-xl shadow border border-blue-100 overflow-hidden">
                  <div style={{ backgroundColor: BARCLAYS_DARK }} className="px-5 py-3 flex items-center justify-between">
                    <h3 className="text-white font-bold text-sm uppercase tracking-wider">{label}</h3>
                    <span className="text-xs bg-blue-400 text-white px-2 py-0.5 rounded-full">AI-Assisted</span>
                  </div>
                  <div className="p-5">
                    <p className="text-[10px] text-blue-600 mb-3 italic">
                      AI-ASSISTED CONTENT — Generated by Sentinel V2 / Anthropic Claude |
                      Grounded in structured transaction data | No hallucinated facts
                    </p>
                    <pre className="text-xs text-gray-700 whitespace-pre-wrap font-sans leading-relaxed">
                      {(report.narrative_sections as any)[key]}
                    </pre>
                  </div>
                </div>
              ))}

              {/* Section 7: Regulatory Disclosures */}
              <div className="bg-white rounded-xl shadow border border-gray-200 overflow-hidden">
                <div style={{ backgroundColor: BARCLAYS_DARK }} className="px-5 py-3">
                  <h3 className="text-white font-bold text-sm uppercase tracking-wider">
                    Section 7: Regulatory Disclosures & Customer Rights
                  </h3>
                </div>
                <div className="p-5">
                  <pre className="text-xs text-gray-700 whitespace-pre-wrap font-sans leading-relaxed">
                    {report.narrative_sections.section_7?.content || ""}
                  </pre>
                </div>
              </div>

              {/* Legal Checklist */}
              <div className="bg-white rounded-xl shadow border border-gray-200 overflow-hidden">
                <div style={{ backgroundColor: BARCLAYS_DARK }} className="px-5 py-3">
                  <h3 className="text-white font-bold text-sm uppercase tracking-wider">
                    Legal Compliance Checklist
                  </h3>
                </div>
                <div className="p-5">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {Object.entries(report.legal_checklist).map(([key, val]) => (
                      <div key={key} className="flex items-center gap-2 text-xs">
                        <span className={val ? "text-green-600" : "text-red-600"}>
                          {val ? "✓" : "✗"}
                        </span>
                        <span className={val ? "text-gray-700" : "text-red-700"}>
                          {key.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase())}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ── Tab: Flagged Transactions ────────────────────────── */}
          {activeTab === "transactions" && (
            <div className="pb-6">
              {report.flagged_transactions.length === 0 ? (
                <div className="bg-white rounded-xl shadow border border-gray-200 p-10 text-center">
                  <div className="text-3xl mb-2">✅</div>
                  <p className="text-gray-500">No stress-contributing transactions identified.</p>
                </div>
              ) : (
                <div className="bg-white rounded-xl shadow border border-gray-200 overflow-hidden">
                  <div style={{ backgroundColor: BARCLAYS_DARK }} className="px-5 py-3">
                    <h3 className="text-white font-bold text-sm uppercase tracking-wider">
                      Flagged Transaction Log ({report.flagged_transactions.length} transactions)
                    </h3>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-blue-50 border-b border-gray-200">
                          {["#", "Transaction ID", "Date", "Amount", "Platform", "Category / Signal", "Severity", "Pulse Δ"].map((h) => (
                            <th key={h} className="px-4 py-3 text-left font-semibold text-gray-700">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {report.flagged_transactions.map((txn, i) => (
                          <tr key={txn.event_id}
                            className={`border-b border-gray-100 hover:bg-red-50 transition ${i % 2 === 0 ? "bg-white" : "bg-red-50/30"}`}>
                            <td className="px-4 py-3 text-gray-500">{i + 1}</td>
                            <td className="px-4 py-3 font-mono text-gray-600">{txn.event_id.slice(0, 12)}…</td>
                            <td className="px-4 py-3">{txn.scored_at?.slice(0, 10)}</td>
                            <td className="px-4 py-3 font-medium">₹{txn.amount?.toLocaleString("en-IN")}</td>
                            <td className="px-4 py-3">
                              <span className="bg-gray-100 px-2 py-0.5 rounded text-gray-600">{txn.platform}</span>
                            </td>
                            <td className="px-4 py-3 text-red-700 font-medium">
                              {txn.category_label || txn.inferred_category}
                            </td>
                            <td className="px-4 py-3">
                              <span className={`px-2 py-0.5 rounded font-mono ${
                                txn.severity > 0.7 ? "bg-red-100 text-red-800"
                                : txn.severity > 0.4 ? "bg-orange-100 text-orange-800"
                                : "bg-yellow-100 text-yellow-800"
                              }`}>
                                {txn.severity?.toFixed(3)}
                              </span>
                            </td>
                            <td className="px-4 py-3 font-mono text-red-700">+{txn.pulse_delta?.toFixed(4)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── Tab: AI Audit ────────────────────────────────────── */}
          {activeTab === "audit" && (
            <div className="pb-6 space-y-6">
              <div className="bg-white rounded-xl shadow border border-gray-200 overflow-hidden">
                <div style={{ backgroundColor: BARCLAYS_DARK }} className="px-5 py-3">
                  <h3 className="text-white font-bold text-sm uppercase tracking-wider">AI Model Metadata</h3>
                </div>
                <div className="p-5 grid grid-cols-2 md:grid-cols-3 gap-4">
                  {[
                    { label: "Model Name",       value: report.ai_model_metadata.model_name },
                    { label: "LLM Engine",        value: report.ai_model_metadata.llm_used },
                    { label: "AI-Assisted",       value: "Yes" },
                    { label: "Human Review Req.", value: report.ai_model_metadata.human_review_required ? "YES" : "No" },
                    { label: "Report ID",         value: report.report_id.slice(0, 8) + "…" },
                  ].map(({ label, value }) => (
                    <div key={label} className="bg-gray-50 rounded-lg p-3">
                      <div className="text-xs text-gray-500 font-semibold uppercase tracking-wider">{label}</div>
                      <div className="text-sm font-bold text-gray-800 mt-0.5">{value}</div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="bg-white rounded-xl shadow border border-blue-100 overflow-hidden">
                <div style={{ backgroundColor: BARCLAYS_DARK }} className="px-5 py-3 flex items-center justify-between">
                  <h3 className="text-white font-bold text-sm uppercase tracking-wider">Section 8: AI Model Audit Statement</h3>
                  <span className="text-xs bg-blue-400 text-white px-2 py-0.5 rounded-full">AI-Assisted</span>
                </div>
                <div className="p-5">
                  <p className="text-[10px] text-blue-600 mb-3 italic">
                    AI-ASSISTED CONTENT — Anthropic Claude | Legally compliant transparency declaration
                  </p>
                  <pre className="text-xs text-gray-700 whitespace-pre-wrap font-sans leading-relaxed">
                    {report.narrative_sections.section_8}
                  </pre>
                </div>
              </div>

              <div className="bg-white rounded-xl shadow border border-gray-200 overflow-hidden">
                <div style={{ backgroundColor: BARCLAYS_DARK }} className="px-5 py-3">
                  <h3 className="text-white font-bold text-sm uppercase tracking-wider">Section 9: Authorisation & Certification</h3>
                </div>
                <div className="p-5">
                  <pre className="text-xs text-gray-700 whitespace-pre-wrap font-sans leading-relaxed">
                    {report.narrative_sections.section_9?.content || ""}
                  </pre>
                </div>
              </div>
            </div>
          )}

          {/* ── Bottom sentinel div (invisible) ─────────────────── */}
          <div ref={bottomRef} />

          {/* ── Sticky Acknowledge Footer ────────────────────────── */}
          <div className="sticky bottom-0 left-0 right-0 z-30 bg-white border-t-2 border-slate-200 shadow-lg px-4 py-4">
            <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
              <div className="text-sm text-gray-500">
                {hasScrolled ? (
                  <span className="text-green-600 font-semibold flex items-center gap-1.5">
                    <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
                      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd"/>
                    </svg>
                    Report fully reviewed — you may now acknowledge
                  </span>
                ) : (
                  <span className="text-amber-600 font-medium flex items-center gap-1.5">
                    <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
                      <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd"/>
                    </svg>
                    Please scroll through the full report to enable acknowledgement
                  </span>
                )}
              </div>

              <button
                onClick={handleAcknowledgeClick}
                disabled={!hasScrolled || !interventionId}
                className="px-8 py-3 rounded-xl font-bold text-white text-sm transition-all
                  disabled:opacity-40 disabled:cursor-not-allowed
                  enabled:hover:opacity-90 enabled:active:scale-[0.98]
                  whitespace-nowrap"
                style={{ backgroundColor: hasScrolled ? BARCLAYS_DARK : "#94a3b8" }}
              >
                {!interventionId
                  ? "⚠ No Intervention ID"
                  : hasScrolled
                  ? "✅ Acknowledge Report"
                  : "🔒 Scroll to Unlock"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}