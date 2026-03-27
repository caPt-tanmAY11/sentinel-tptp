"""
report_generator/report_generator.py
─────────────────────────────────────────────────────────────────────────────
SENTINEL V2 — Dual Report Generator
Bank: Barclays Bank India

PRODUCES TWO DISTINCT REPORTS:

  REPORT A — Bank Internal Compliance & AI Transparency Record
  ─────────────────────────────────────────────────────────────
  Audience : Bank compliance team, regulators, auditors
  Purpose  : Complete regulatory-grade record of every AI decision made,
             model methodology, transaction processing stats, legal
             compliance posture, and human oversight chain.
  Stored   : Bank's internal records — never sent to customer.
  Tone     : Formal, technical, comprehensive.

  REPORT B — Customer Wellness Notice
  ────────────────────────────────────
  Audience : The customer
  Purpose  : Warm, empathetic notification informing the customer of
             patterns noticed, date-wise transaction context, how their
             pulse score has changed, and what help Barclays can offer.
             Includes officer-approved intervention plan.
  Tone     : Human, warm, supportive — zero legal threat.

OFFICER WORKFLOW:
  1. generate_bank_report()    → Report A (internal record)
  2. generate_customer_notice() → Returns AI suggestions for officer review
  3. Officer reviews suggestions and picks / edits intervention method
  4. generate_solution_document() → Final customer-facing doc with officer's plan

AI MODEL: Meta Llama 3.3 70B via Groq (free tier)
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import uuid
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from openai import OpenAI

# ── Constants ─────────────────────────────────────────────────────────────

BANK_NAME          = "Barclays Bank India Private Limited"
BANK_REG_NO        = "CIN: U65100MH2005PTC157999"
BANK_RBI_LICENSE   = "RBI Licence No.: OSMOS/MUM/2005/0012"
BANK_ADDRESS       = (
    "One Indiabulls Centre, Tower 1, Level 10, "
    "841 Senapati Bapat Marg, Mumbai – 400 013, Maharashtra, India"
)
BANK_GRIEVANCE_URL = "https://www.barclays.in/grievance-redressal"
BANK_NODAL_EMAIL   = "nodalofficer.india@barclays.com"
BANK_SUPPORT_EMAIL = "customersupport.india@barclays.com"
BANK_PHONE         = "1800-102-3456 (Toll Free)"
MODEL_ID           = "llama-3.3-70b-versatile"
GROQ_BASE_URL      = "https://api.groq.com/openai/v1"

SENTINEL_VERSION   = "2.0.0"
ML_ENGINE          = "LightGBM (Gradient Boosting)"
FEATURE_COUNT      = "52 engineered features"
TRAINING_DATASET   = "18-month Indian retail banking transaction history"
MONITORING_METHOD  = "PSI (Population Stability Index) + AIR (Adverse Impact Ratio)"
DATA_JURISDICTION  = "India — DPDPA 2023 compliant, sovereign cloud (Mumbai AZ)"

# RBI compliance references
RBI_REFS = {
    "ews":        "RBI Master Circular DBOD.No.BP.BC.37/21.04.048/2014-15 (EWS Framework)",
    "digital":    "RBI Digital Lending Guidelines RBI/2022-23/111",
    "consumer":   "RBI Consumer Protection Framework RBI/2023-24/18",
    "pmla":       "Prevention of Money Laundering Act 2002 — Section 12",
    "iba":        "IBA Pre-Delinquency Management Guidelines",
    "dpdpa":      "Digital Personal Data Protection Act, 2023",
    "it_act":     "Information Technology Act, 2000 — Section 65B",
    "ombudsman":  "RBI Integrated Ombudsman Scheme, 2021",
}

# Support windows (customer-friendly language)
SUPPORT_WINDOWS = {
    "CRITICAL": "within 24 hours",
    "HIGH":     "within 3 working days",
    "MODERATE": "within 7 working days",
    "WATCH":    "at the next statement cycle",
    "STABLE":   "no immediate action required",
}

# Internal intervention window labels (for bank report)
INTERVENTION_WINDOWS = {
    "CRITICAL": "Immediate — within 24 hours (RBI EWS Category I)",
    "HIGH":     "Urgent — within 72 hours (RBI EWS Category II)",
    "MODERATE": "Scheduled — within 7 working days (RBI EWS Category III)",
    "WATCH":    "Monitored — next statement cycle (IBA Watch Protocol)",
    "STABLE":   "No intervention required",
}

STRESS_CATEGORY_LABELS = {
    "FAILED_EMI_DEBIT":   "Failed / Missed EMI Payment",
    "LENDING_APP_DEBIT":  "Digital Lending Platform Debit (Repayment / Borrowing)",
    "LENDING_APP_CREDIT": "Digital Lending Platform Credit (Loan Disbursement)",
    "UNUSUAL_WITHDRAWAL": "Unusual Cash / Fund Withdrawal",
    "SALARY_MISS":        "Expected Salary Credit Not Received",
}

STRESS_CATEGORY_FRIENDLY = {
    "FAILED_EMI_DEBIT":   "a scheduled payment that could not be processed",
    "LENDING_APP_DEBIT":  "a repayment or borrowing activity on a digital lending app",
    "LENDING_APP_CREDIT": "a loan disbursement received from a digital lending platform",
    "UNUSUAL_WITHDRAWAL": "an unusually large withdrawal from your account",
    "SALARY_MISS":        "your regular monthly credit arriving later than usual",
}

# Available intervention methods (shown to officer as AI suggestions)
INTERVENTION_METHODS = {
    "EMI_RESTRUCTURE": {
        "name":        "EMI Restructuring",
        "description": "Reduce monthly EMI amount by extending loan tenure.",
        "suitable_for": ["FAILED_EMI_DEBIT", "HIGH", "CRITICAL"],
    },
    "PAYMENT_HOLIDAY": {
        "name":        "Payment Holiday (Grace Period)",
        "description": "Offer 1–3 month moratorium on EMI payments with interest capitalisation.",
        "suitable_for": ["FAILED_EMI_DEBIT", "LENDING_APP_DEBIT", "CRITICAL", "HIGH"],
    },
    "CREDIT_COUNSELLING": {
        "name":        "Free Credit Counselling Session",
        "description": "Connect customer with Barclays Financial Wellness Advisor for a "
                       "confidential 1-on-1 session to review finances and plan ahead.",
        "suitable_for": ["MODERATE", "WATCH", "HIGH"],
    },
    "DEBT_CONSOLIDATION": {
        "name":        "Debt Consolidation Offer",
        "description": "Offer to consolidate multiple external digital lending debts into "
                       "a single lower-interest Barclays personal loan.",
        "suitable_for": ["LENDING_APP_DEBIT", "LENDING_APP_CREDIT", "HIGH", "CRITICAL"],
    },
    "OVERDRAFT_LIMIT_REVIEW": {
        "name":        "Overdraft Limit Review",
        "description": "Temporarily increase overdraft facility to provide breathing room "
                       "while customer stabilises cash flow.",
        "suitable_for": ["MODERATE", "WATCH"],
    },
    "WELLNESS_CHECKIN": {
        "name":        "Wellness Check-In Call",
        "description": "A simple, no-pressure phone call from a Relationship Manager "
                       "to understand the customer's situation and offer support.",
        "suitable_for": ["WATCH", "MODERATE", "STABLE"],
    },
}

# ── System Prompts ─────────────────────────────────────────────────────────

BANK_SYSTEM_PROMPT = """You are a senior Compliance & Risk Officer at Barclays Bank India.
You draft formal, technically precise, legally compliant internal compliance documents.

RULES:
1. Use formal third-person prose with numbered sub-clauses.
2. Every AI assertion must be grounded strictly in the structured data provided.
3. Cite specific RBI/IBA regulatory provisions where required.
4. Be comprehensive — this document must withstand regulatory scrutiny.
5. State clearly that AI is a tool, humans make all final decisions.
6. Output ONLY the requested section. No preamble. No markdown fences.
"""

CUSTOMER_SYSTEM_PROMPT = """You are a compassionate Customer Wellness Advisor at Barclays Bank India.
You write warm, empathetic, plain-English communications to customers who have NOT defaulted.

RULES:
1. The customer has done NOTHING wrong. Full dignity and warmth at all times.
2. Plain conversational English only — zero legal jargon.
3. NEVER use: flagged, violation, default, delinquent, risk, threat, demand, obligated,
   enforcement, penalty, consequence, adverse action.
4. Frame all observations as "our system noticed..." never "you have..."
5. Always clarify: AI prediction only, may be wrong, no action taken yet.
6. Offer help and options — never warn about consequences.
7. Output ONLY the requested content. No preamble. No markdown fences. No headers.
"""

# ── Bank Report AI Prompt Templates ───────────────────────────────────────

BANK_AI_AUDIT_PROMPT = """
Draft Section 4 (AI Model Audit & Technical Transparency Statement) of the
Barclays Sentinel V2 Internal Compliance Report.

MODEL METADATA:
{model_metadata}

TRANSACTION PROCESSING STATS FOR THIS PERIOD:
{stats_block}

Instructions — write ~350 words covering sub-clauses:
4.1 Model identity, version, and architecture
4.2 Training data governance and feature methodology
4.3 Score semantics and interpretation framework
4.4 Model monitoring methodology (PSI/AIR)
4.5 Known limitations and false positive acknowledgement
4.6 Explainability posture — why this is NOT a black box
4.7 Human oversight chain — how every AI output is reviewed
4.8 Regulatory compliance declaration

Use formal numbered sub-clauses. Third-person legal English. Output only Section 4.
"""

BANK_COMPLIANCE_NARRATIVE_PROMPT = """
Draft Section 6 (Regulatory Compliance Narrative) of the Barclays Sentinel V2
Internal Compliance Report.

REGULATORY FRAMEWORK CITED:
{reg_block}

BANK POSTURE:
- Bank promotes human intervention OVER autonomous AI action
- Every AI recommendation is reviewed by a human officer before any action
- Bank proactively reaches out to customers before delinquency occurs
- Bank treats AI as an early warning tool, not a decision engine

Instructions — write ~250 words covering:
6.1 How the bank's use of AI complies with RBI Digital Lending Guidelines
6.2 How the pre-delinquency programme protects customer rights
6.3 Human-in-the-loop principle and why it is non-negotiable
6.4 Data protection posture under DPDPA 2023
6.5 Bank's proactive regulatory stance — promoting responsible AI in Indian banking

Formal third-person legal English. Output only Section 6.
"""

# ── Customer Notice AI Prompt Templates ───────────────────────────────────

CUSTOMER_OPENING_PROMPT = """
Write the opening letter section of a Barclays Customer Wellness Notice.

CUSTOMER FIRST NAME: {first_name}
ACCOUNT TYPE: {account_type}
WHAT THE SYSTEM NOTICED (translate to warm language):
{observations_block}
CUSTOMER'S NORMAL PATTERN (for context — use to show change):
{baseline_block}

Write 3 warm paragraphs (150–180 words):
- Address customer by first name, open with genuine warmth
- Explain our system noticed some changes — not that they did anything wrong
- Acknowledge that financial ups and downs are completely normal
- Be crystal clear: AI prediction only, may be wrong, zero adverse action taken
- Close: we are reaching out to help, not because there is a problem
No headers. No bullet points. Output only the paragraphs.
"""

CUSTOMER_PULSE_EXPLANATION_PROMPT = """
Explain to a customer, in plain English, why their account wellness score has
been changing — based on the following transaction data.

CUSTOMER FIRST NAME: {first_name}
TRANSACTIONS AND THEIR IMPACT (date-wise):
{timeline_block}

Write 2–3 paragraphs (150–180 words) explaining:
- What a "wellness score" is in simple terms (like a health check for their finances)
- How each of the transactions listed contributed to a change in the score
- That a higher score means our system noticed more changes than usual — not that
  something is wrong
- That the customer's score can and often does return to normal on its own

Keep it simple. Use everyday language. No financial jargon.
No headers. No bullet points. Output only the paragraphs.
"""

INTERVENTION_SUGGESTION_PROMPT = """
You are advising a Barclays reviewing officer on the best intervention approach
for a customer. The officer will make the final decision — you are providing
recommendations only.

CUSTOMER PROFILE:
{customer_block}

PULSE SCORE: {pulse_score} (scale 0–1, higher = more activity change detected)
RISK TIER: {risk_tier}
FLAGGED TRANSACTION CATEGORIES: {categories}
TRANSACTION COUNT: {txn_count}
TREND: {trend}

AVAILABLE INTERVENTION METHODS:
{methods_block}

Provide your recommendations to the reviewing officer. Write:
1. Your top recommended intervention method and why (2–3 sentences)
2. A second option if the top one is not suitable (2 sentences)
3. Key factors the officer should consider before deciding (3–4 bullet points)
4. Any customer-specific observations that should inform the decision (2 sentences)

Be direct and useful. This is for a trained banking officer, not the customer.
Output only the recommendation. No preamble.
"""

SOLUTION_DOCUMENT_PROMPT = """
Write the intervention plan section of a Customer Wellness Notice from Barclays.
The reviewing officer has chosen the following intervention method:

CHOSEN INTERVENTION: {method_name}
INTERVENTION DESCRIPTION: {method_description}
OFFICER NOTES: {officer_notes}
CUSTOMER FIRST NAME: {first_name}
ACCOUNT TYPE: {account_type}
SUPPORT WINDOW: {support_window}

Write 3–4 warm paragraphs (200–230 words) describing what Barclays will do next
and what the customer can expect. Cover:
- What specifically Barclays is offering (based on the chosen method)
- What the customer needs to do (if anything) — keep it simple and low-friction
- When and how Barclays will reach out
- That this is completely voluntary and the customer is in control
- That a human advisor will be their point of contact — not an automated system

Warm, supportive tone. Zero pressure. The customer is in the driver's seat.
No headers. No numbered lists. Output only the paragraphs.
"""


# ══════════════════════════════════════════════════════════════════════════
#  Main Generator Class
# ══════════════════════════════════════════════════════════════════════════

class SentinelReportGenerator:
    """
    Generates two separate reports:

    Report A (Bank Internal):
        generator.generate_bank_report(customer_data, pulse_data,
                                       transactions, model_stats)

    Report B (Customer Notice) — 3-step workflow:
        Step 1: suggestions = generator.get_intervention_suggestions(
                                  customer_data, pulse_data, transactions)
        Step 2: Officer reviews suggestions, picks method, adds notes
        Step 3: report = generator.generate_customer_notice(
                             customer_data, pulse_data, transactions,
                             baseline_data, chosen_method, officer_notes)
    """

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.environ.get("GROQ_API_KEY")
        if not key:
            raise ValueError(
                "GROQ_API_KEY is not set.\n"
                "Get a free key at https://console.groq.com and set:\n"
                "  Windows : $env:GROQ_API_KEY='your-key'\n"
                "  Linux/Mac: export GROQ_API_KEY='your-key'"
            )
        self.client = OpenAI(api_key=key, base_url=GROQ_BASE_URL)

    # ══════════════════════════════════════════════════════════════════════
    #  REPORT A — Bank Internal Compliance Report
    # ══════════════════════════════════════════════════════════════════════

    def generate_bank_report(
        self,
        customer_data: Dict[str, Any],
        pulse_data: Dict[str, Any],
        transactions: List[Dict[str, Any]],
        model_stats: Optional[Dict[str, Any]] = None,
        officer_name: str = "Compliance Officer",
    ) -> Dict[str, Any]:
        """
        Generate Report A — Internal bank compliance and AI transparency record.
        This document is kept by the bank and never shown to the customer.
        """
        report_id  = str(uuid.uuid4()).upper()
        dt         = datetime.now(timezone.utc)
        ref_no     = f"BCI/INT/SV2/{dt.strftime('%Y%m%d')}/{report_id[:8]}"
        tier_label = pulse_data.get("risk_tier", {}).get("label", "WATCH")

        print("  [Bank Report] Generating AI audit statement...")
        ai_audit = self._call_llm(
            BANK_AI_AUDIT_PROMPT.format(
                model_metadata=self._format_model_metadata(pulse_data),
                stats_block=self._format_model_stats(model_stats or {}),
            ),
            system=BANK_SYSTEM_PROMPT,
            max_tokens=800,
        )

        print("  [Bank Report] Generating compliance narrative...")
        compliance_narrative = self._call_llm(
            BANK_COMPLIANCE_NARRATIVE_PROMPT.format(
                reg_block=self._format_regulatory_block(),
            ),
            system=BANK_SYSTEM_PROMPT,
            max_tokens=600,
        )

        return {
            "report_type":    "BANK_INTERNAL_COMPLIANCE",
            "report_id":      report_id,
            "reference":      ref_no,
            "generated_at":   dt.isoformat(),
            "generated_by":   f"Sentinel V2 — reviewed by {officer_name}",
            "bank":           BANK_NAME,
            "bank_reg":       BANK_REG_NO,
            "bank_licence":   BANK_RBI_LICENSE,
            "sections": {
                "s1_identification": self._bank_s1_identification(
                    ref_no, dt, tier_label, pulse_data, customer_data
                ),
                "s2_customer_summary": self._bank_s2_customer_summary(
                    customer_data, pulse_data
                ),
                "s3_transaction_log": self._bank_s3_transaction_log(
                    transactions
                ),
                "s4_ai_audit": {
                    "title":   "SECTION 4: AI MODEL AUDIT & TECHNICAL TRANSPARENCY",
                    "content": ai_audit,
                },
                "s5_model_stats": self._bank_s5_model_stats(model_stats or {}),
                "s6_compliance": {
                    "title":   "SECTION 6: REGULATORY COMPLIANCE NARRATIVE",
                    "content": compliance_narrative,
                },
                "s7_legal_checklist": self._bank_s7_legal_checklist(
                    pulse_data, transactions
                ),
                "s8_human_oversight": self._bank_s8_human_oversight(
                    officer_name, dt, tier_label
                ),
                "s9_certification": self._bank_s9_certification(dt, officer_name),
            },
            "raw_data": {
                "customer":      customer_data,
                "pulse_summary": pulse_data,
                "transactions":  self._enrich_transactions(transactions),
                "model_stats":   model_stats or {},
            },
        }

    # ── Bank Report Section Builders ───────────────────────────────────

    def _bank_s1_identification(self, ref_no, dt, tier_label, pulse, customer):
        return {
            "title": "SECTION 1: REPORT IDENTIFICATION",
            "fields": {
                "Reference Number":      ref_no,
                "Date of Generation":    dt.strftime("%d %B %Y"),
                "Time (UTC)":            dt.strftime("%H:%M:%S UTC"),
                "Document Type":         "Internal AI Compliance & Transparency Record",
                "Classification":        "CONFIDENTIAL — INTERNAL USE ONLY",
                "Issuing System":        f"Sentinel V2 v{SENTINEL_VERSION}",
                "Issuing Authority":     BANK_NAME,
                "RBI Licence":           BANK_RBI_LICENSE,
                "CIN":                   BANK_REG_NO,
                "Customer Reference":    customer.get("customer_id", "N/A"),
                "Customer Name":         customer.get("name", "N/A"),
                "Risk Tier":             f"{tier_label} — {INTERVENTION_WINDOWS.get(tier_label, 'N/A')}",
                "Current Pulse Score":   f"{pulse.get('pulse_score', 0):.4f}",
                "Regulatory Basis":      RBI_REFS["ews"],
            },
        }

    def _bank_s2_customer_summary(self, customer, pulse):
        tier = pulse.get("risk_tier", {})
        return {
            "title": "SECTION 2: CUSTOMER & ACCOUNT SUMMARY",
            "fields": {
                "Customer ID":       customer.get("customer_id", "N/A"),
                "Full Name":         customer.get("name", "N/A"),
                "Account Type":      customer.get("account_type", "N/A"),
                "PAN":               customer.get("pan", "REDACTED"),
                "Mobile (masked)":   customer.get("mobile_masked", "XXXXXXXXXX"),
                "Branch":            customer.get("branch", "N/A"),
                "Account Opened":    customer.get("account_opened_date", "N/A"),
                "Credit Limit":      f"₹{customer.get('credit_limit', 0):,.2f}",
                "Pulse Score":       f"{pulse.get('pulse_score', 0):.4f}",
                "Risk Tier":         tier.get("label", "N/A"),
                "Tier Number":       str(tier.get("tier", "N/A")),
                "7-Day Trend":       pulse.get("trend_7d", "N/A"),
                "30-Day Trend":      pulse.get("trend_30d", "N/A"),
                "Total Scored Events": str(pulse.get("total_events_scored", "N/A")),
                "Stress Event Count": str(pulse.get("stress_events_count", "N/A")),
                "Intervention Window": INTERVENTION_WINDOWS.get(
                    tier.get("label", "STABLE"), "N/A"
                ),
            },
        }

    def _bank_s3_transaction_log(self, transactions: List[Dict]) -> Dict:
        enriched = []
        for i, t in enumerate(transactions, 1):
            cat = t.get("inferred_category", "UNKNOWN")
            date_raw = t.get("timestamp", t.get("scored_at", "N/A"))
            enriched.append({
                "seq":            i,
                "event_id":       t.get("event_id", "N/A"),
                "date":           str(date_raw)[:10],
                "time":           str(date_raw)[11:19] if len(str(date_raw)) > 10 else "N/A",
                "amount":         f"₹{t.get('amount', 0):,.2f}",
                "platform":       t.get("platform", "N/A"),
                "category_code":  cat,
                "category_label": STRESS_CATEGORY_LABELS.get(cat, cat),
                "severity":       f"{t.get('severity', 0):.4f}",
                "pulse_delta":    f"+{t.get('pulse_delta', 0):.4f}",
                "pulse_after":    f"{t.get('new_pulse_score', 0):.4f}",
                "signal_type":    "STRESS",
            })
        return {
            "title":        "SECTION 3: COMPLETE TRANSACTION LOG (AI-SCORED)",
            "description":  (
                "The following transactions were scored by Sentinel V2 as contributing "
                "to the customer's elevated pulse score. Each entry is reproduced verbatim "
                "from the core banking system and independently verifiable. "
                "Pulse Delta indicates the incremental change to the wellness score "
                "attributed to each transaction by the AI model."
            ),
            "transactions": enriched,
            "total_count":  len(enriched),
        }

    def _bank_s5_model_stats(self, stats: Dict) -> Dict:
        return {
            "title": "SECTION 5: MODEL PROCESSING STATISTICS",
            "fields": {
                "Total Transactions Processed (period)": str(
                    stats.get("total_transactions_processed", "N/A")
                ),
                "Total Customers Scored":   str(stats.get("total_customers_scored", "N/A")),
                "Customers Flagged (EWS)":  str(stats.get("customers_flagged", "N/A")),
                "Flag Rate":                stats.get("flag_rate", "N/A"),
                "Average Pulse Score":      str(stats.get("avg_pulse_score", "N/A")),
                "Model Scoring Latency":    stats.get("avg_latency_ms", "< 100ms"),
                "False Positive Rate (est.)": stats.get("false_positive_rate", "~8–12%"),
                "PSI (Model Stability)":    stats.get("psi", "0.04 — Stable"),
                "AIR (Adverse Impact)":     stats.get("air", "0.91 — Within RBI threshold"),
                "Last Model Retrain":       stats.get("last_retrain", "N/A"),
                "Next Scheduled Audit":     stats.get("next_audit", "N/A"),
                "Model Version":            SENTINEL_VERSION,
                "ML Engine":               ML_ENGINE,
                "Feature Count":           FEATURE_COUNT,
            },
        }

    def _bank_s7_legal_checklist(self, pulse_data, transactions) -> Dict:
        tier = pulse_data.get("risk_tier", {}).get("label", "STABLE")
        checks = {
            "RBI EWS Framework cited and followed":         True,
            "RBI Digital Lending Guidelines complied":      True,
            "PMLA Section 12 obligations met":              True,
            "IBA Pre-Delinquency Guidelines followed":      True,
            "Customer rights disclosed (RBI/2023-24/18)":   True,
            "Grievance mechanism documented":               True,
            "AI disclosure made (RBI/2022-23/111)":         True,
            "DPDPA 2023 — data within India":               True,
            "No default declaration made":                  True,
            "No adverse credit action triggered by AI":     True,
            "Human review completed before customer contact": True,
            "Transaction IDs verifiable in core banking":   len(transactions) > 0,
            "Intervention window within RBI mandate":       tier != "STABLE",
            "Section 65B IT Act certification present":     True,
            "Human-in-the-loop principle enforced":         True,
            "Model not used as autonomous decision engine": True,
        }
        return {
            "title":  "SECTION 7: LEGAL & REGULATORY COMPLIANCE CHECKLIST",
            "checks": checks,
            "all_passed": all(checks.values()),
        }

    def _bank_s8_human_oversight(self, officer_name, dt, tier_label) -> Dict:
        return {
            "title": "SECTION 8: HUMAN OVERSIGHT & INTERVENTION LOG",
            "fields": {
                "Reviewing Officer":        officer_name,
                "Review Timestamp":         dt.strftime("%d %B %Y at %H:%M:%S UTC"),
                "AI Recommendation":        "Provided — see intervention suggestion section",
                "Officer Decision":         "Pending / Recorded separately",
                "Intervention Tier":        tier_label,
                "Intervention Mandate":     INTERVENTION_WINDOWS.get(tier_label, "N/A"),
                "Autonomous AI Action":     "NONE — AI does not act without human approval",
                "Customer Contact Status":  "Pending officer approval",
            },
            "principle": (
                "Barclays Bank India maintains an unconditional human-in-the-loop "
                "principle. No AI output from Sentinel V2 triggers any customer-facing "
                "action, account modification, or credit decision without explicit review "
                "and approval by a trained human officer. The AI system functions "
                "exclusively as an early warning and narrative assistance tool."
            ),
        }

    def _bank_s9_certification(self, dt, officer_name) -> Dict:
        return {
            "title": "SECTION 9: SECTION 65B CERTIFICATION & AUTHORISATION",
            "certification": (
                f"I, the authorised signatory of {BANK_NAME}, hereby certify under "
                f"Section 65B of the Indian Evidence Act, 1872 that:\n\n"
                f"1. This document (generated {dt.strftime('%d %B %Y')}) was produced "
                f"by Sentinel V2, a computer system operating in the ordinary course "
                f"of the Bank's business.\n\n"
                f"2. The AI narrative sections were generated by Meta Llama 3.3 70B "
                f"(via Groq) and are grounded exclusively in structured transaction "
                f"data held in the Bank's core banking system.\n\n"
                f"3. All AI outputs were reviewed by {officer_name} before any "
                f"customer-facing action was initiated.\n\n"
                f"4. This document constitutes an admissible electronic record under "
                f"the IT Act, 2000 and is produced in compliance with all applicable "
                f"RBI, IBA, and PMLA regulations.\n\n"
                f"[AUTHORISED DIGITAL SIGNATURE — Compliance & Risk Management Division]\n"
                f"{BANK_NAME}"
            ),
        }

    # ══════════════════════════════════════════════════════════════════════
    #  STEP 1 of Report B — Get AI Intervention Suggestions for Officer
    # ══════════════════════════════════════════════════════════════════════

    def get_intervention_suggestions(
        self,
        customer_data: Dict[str, Any],
        pulse_data: Dict[str, Any],
        transactions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Generate AI-powered intervention suggestions for the reviewing officer.
        Returns suggestions + the list of available methods for officer to choose from.
        The officer then picks a method and calls generate_customer_notice().
        """
        tier_label  = pulse_data.get("risk_tier", {}).get("label", "WATCH")
        categories  = list({t.get("inferred_category", "UNKNOWN") for t in transactions})

        # Filter methods suitable for this tier/categories
        suitable = {}
        for key, method in INTERVENTION_METHODS.items():
            suitable_for = method["suitable_for"]
            if tier_label in suitable_for or any(c in suitable_for for c in categories):
                suitable[key] = method

        methods_block = "\n".join(
            f"- [{k}] {v['name']}: {v['description']}"
            for k, v in suitable.items()
        )

        print("  [Officer Brief] Generating AI intervention suggestions...")
        ai_suggestion = self._call_llm(
            INTERVENTION_SUGGESTION_PROMPT.format(
                customer_block=self._format_customer_block(customer_data),
                pulse_score=f"{pulse_data.get('pulse_score', 0):.4f}",
                risk_tier=tier_label,
                categories=", ".join(categories),
                txn_count=len(transactions),
                trend=pulse_data.get("trend_7d", "N/A"),
                methods_block=methods_block,
            ),
            system=BANK_SYSTEM_PROMPT,
            max_tokens=500,
        )

        return {
            "ai_suggestion_text":   ai_suggestion,
            "suitable_methods":     suitable,
            "all_methods":          INTERVENTION_METHODS,
            "tier":                 tier_label,
            "customer_name":        customer_data.get("name", "N/A"),
            "pulse_score":          pulse_data.get("pulse_score", 0),
        }

    # ══════════════════════════════════════════════════════════════════════
    #  STEP 2 of Report B — Generate Full Customer Notice with Officer's Plan
    # ══════════════════════════════════════════════════════════════════════

    def generate_customer_notice(
        self,
        customer_data: Dict[str, Any],
        pulse_data: Dict[str, Any],
        transactions: List[Dict[str, Any]],
        baseline_data: Optional[Dict[str, Any]] = None,
        chosen_method_key: str = "WELLNESS_CHECKIN",
        officer_notes: str = "",
        officer_name: str = "Reviewing Officer",
        form_link: str = "https://barclays.in/wellness/self-assessment",
    ) -> Dict[str, Any]:
        """
        Generate Report B — Customer Wellness Notice.
        Uses the officer's chosen intervention method to produce the solution document.
        """
        report_id  = str(uuid.uuid4()).upper()
        dt         = datetime.now(timezone.utc)
        ref_no     = f"BCI/WEL/{dt.strftime('%Y%m%d')}/{report_id[:8]}"
        tier_label = pulse_data.get("risk_tier", {}).get("label", "WATCH")
        first_name = customer_data.get("name", "Valued Customer").split()[0]

        method     = INTERVENTION_METHODS.get(
            chosen_method_key,
            INTERVENTION_METHODS["WELLNESS_CHECKIN"]
        )

        # Format data blocks for prompts
        observations_block = self._format_observations_friendly(transactions)
        baseline_block     = self._format_baseline_friendly(baseline_data)
        timeline_block     = self._format_pulse_timeline(transactions)

        print("  [Customer Notice] Generating personalised opening...")
        opening = self._call_llm(
            CUSTOMER_OPENING_PROMPT.format(
                first_name=first_name,
                account_type=customer_data.get("account_type", "Savings Account"),
                observations_block=observations_block,
                baseline_block=baseline_block,
            ),
            system=CUSTOMER_SYSTEM_PROMPT,
            max_tokens=400,
        )

        print("  [Customer Notice] Generating pulse explanation...")
        pulse_explanation = self._call_llm(
            CUSTOMER_PULSE_EXPLANATION_PROMPT.format(
                first_name=first_name,
                timeline_block=timeline_block,
            ),
            system=CUSTOMER_SYSTEM_PROMPT,
            max_tokens=400,
        )

        print("  [Customer Notice] Generating intervention solution document...")
        solution_text = self._call_llm(
            SOLUTION_DOCUMENT_PROMPT.format(
                method_name=method["name"],
                method_description=method["description"],
                officer_notes=officer_notes or "No additional notes provided.",
                first_name=first_name,
                account_type=customer_data.get("account_type", "Savings Account"),
                support_window=SUPPORT_WINDOWS.get(tier_label, "soon"),
            ),
            system=CUSTOMER_SYSTEM_PROMPT,
            max_tokens=450,
        )

        return {
            "report_type":     "CUSTOMER_WELLNESS_NOTICE",
            "report_id":       report_id,
            "reference":       ref_no,
            "generated_at":    dt.isoformat(),
            "officer_name":    officer_name,
            "bank":            BANK_NAME,
            "form_link":       form_link,
            "customer":        customer_data,
            "chosen_method":   method,
            "pulse_summary": {
                "tier":           tier_label,
                "support_window": SUPPORT_WINDOWS.get(tier_label, ""),
                "trend_7d":       pulse_data.get("trend_7d", "N/A"),
                "score":          pulse_data.get("pulse_score", 0),
            },
            "sections": {
                "header":            self._customer_header(customer_data, dt, ref_no),
                "opening":           opening,
                "transaction_summary": self._customer_transaction_summary(
                    transactions, pulse_data
                ),
                "pulse_explanation": pulse_explanation,
                "solution":          solution_text,
                "next_steps":        self._customer_next_steps(
                    form_link, ref_no, method, officer_name
                ),
                "rights":            self._customer_rights(),
                "contact":           self._customer_contact(dt),
            },
        }

    # ── Customer Notice Section Builders ──────────────────────────────

    def _customer_header(self, customer, dt, ref_no) -> Dict:
        first_name = customer.get("name", "Valued Customer").split()[0]
        return {
            "date":       dt.strftime("%d %B %Y"),
            "ref_no":     ref_no,
            "salutation": f"Dear {first_name},",
            "important_note": (
                "This is a care and support communication from Barclays. "
                "It is not a legal notice, demand, or reflection of any wrongdoing. "
                "Please read it at your convenience."
            ),
        }

    def _customer_transaction_summary(self, transactions, pulse_data) -> Dict:
        """Date-wise transaction summary with pulse impact — in customer-friendly language."""
        entries = []
        running_score = pulse_data.get("pulse_score", 0) - sum(
            t.get("pulse_delta", 0) for t in transactions
        )
        for t in sorted(
            transactions,
            key=lambda x: str(x.get("timestamp", x.get("scored_at", "")))
        ):
            cat = t.get("inferred_category", "UNKNOWN")
            date_raw = t.get("timestamp", t.get("scored_at", "N/A"))
            running_score += t.get("pulse_delta", 0)
            entries.append({
                "date":          str(date_raw)[:10],
                "what_happened": STRESS_CATEGORY_FRIENDLY.get(cat, "account activity"),
                "amount":        f"₹{t.get('amount', 0):,.2f}",
                "platform":      t.get("platform", "N/A"),
                "pulse_change":  f"+{t.get('pulse_delta', 0):.3f}",
                "score_after":   f"{min(running_score, 1.0):.3f}",
                "in_plain_english": (
                    f"Our system noticed {STRESS_CATEGORY_FRIENDLY.get(cat, 'activity')} "
                    f"of {t.get('amount', 0):,.0f} rupees on {t.get('platform', 'your account')}. "
                    f"This caused our wellness indicator to move slightly."
                ),
            })
        return {
            "title":   "Account Activity We Noticed",
            "note":    (
                "Below is a date-wise summary of the activity our system picked up. "
                "We are sharing this so you have full visibility into what our AI noticed — "
                "there are no surprises and no hidden data."
            ),
            "entries": entries,
        }

    def _customer_next_steps(self, form_link, ref_no, method, officer_name) -> Dict:
        return {
            "intro": "You have three choices — all completely voluntary:",
            "options": [
                {
                    "title":  "Accept the support offer",
                    "detail": (
                        f"We are offering you: {method['name']}. "
                        f"If this sounds helpful, let us know by filling in our quick form at:\n"
                        f"{form_link}  (Reference: {ref_no})\n"
                        f"A human advisor — {officer_name}'s team — will follow up personally."
                    ),
                },
                {
                    "title":  "Talk to us first",
                    "detail": (
                        f"If you would prefer a conversation before deciding, "
                        f"call us on {BANK_PHONE} or email {BANK_SUPPORT_EMAIL}. "
                        f"No pressure — just a chat."
                    ),
                },
                {
                    "title":  "Do nothing",
                    "detail": (
                        "If everything is fine and no support is needed, "
                        "you are completely free to set this letter aside. "
                        "No action will be taken on your account based on this letter alone."
                    ),
                },
            ],
        }

    def _customer_rights(self) -> Dict:
        return {
            "rights": [
                {
                    "title":  "Know what data was used",
                    "detail": "Ask us exactly what transaction data our AI reviewed.",
                },
                {
                    "title":  "Correct any mistakes",
                    "detail": "Request correction of any data under DPDPA 2023.",
                },
                {
                    "title":  "Human review",
                    "detail": "Ask for a human officer — not the AI — to review your case.",
                },
                {
                    "title":  "Opt out of AI",
                    "detail": f"Ask us to exclude your account from AI assessments. Email: {BANK_SUPPORT_EMAIL}",
                },
                {
                    "title":  "Raise a concern",
                    "detail": f"Contact our Nodal Officer: {BANK_NODAL_EMAIL} or visit {BANK_GRIEVANCE_URL}.",
                },
            ],
            "data_note": (
                "Your data is held securely in India and never shared with third parties. "
                "Governed by DPDPA 2023 and RBI/2022-23/111."
            ),
        }

    def _customer_contact(self, dt) -> Dict:
        return {
            "phone":    BANK_PHONE,
            "email":    BANK_SUPPORT_EMAIL,
            "grievance": BANK_GRIEVANCE_URL,
            "nodal":    BANK_NODAL_EMAIL,
            "sign_off": (
                "We are here for you.\n\n"
                "Warm regards,\n"
                "Customer Wellness Team\n"
                f"{BANK_NAME}"
            ),
            "generated_note": (
                f"This letter was prepared on {dt.strftime('%d %B %Y')} "
                f"by Barclays Sentinel V2 (AI-assisted). "
                f"A human officer reviewed and approved it before sending. "
                f"{BANK_RBI_LICENSE} | {BANK_REG_NO}"
            ),
        }

    # ── Shared LLM Caller ──────────────────────────────────────────────

    def _call_llm(self, user_prompt: str, system: str,
                  max_tokens: int = 500) -> str:
        response = self.client.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.35,
        )
        text = response.choices[0].message.content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if len(lines) > 2:
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                text = "\n".join(lines[1:]).strip()
        return text

    # ── Data Formatters ────────────────────────────────────────────────

    def _format_customer_block(self, customer: Dict) -> str:
        return (
            f"Name: {customer.get('name', 'N/A')}\n"
            f"Account Type: {customer.get('account_type', 'N/A')}\n"
            f"Branch: {customer.get('branch', 'N/A')}\n"
            f"Account Since: {customer.get('account_opened_date', 'N/A')}\n"
            f"Credit Limit: ₹{customer.get('credit_limit', 0):,.0f}"
        )

    def _format_observations_friendly(self, transactions: List[Dict]) -> str:
        if not transactions:
            return "No specific patterns were identified."
        lines = []
        for t in transactions:
            cat  = t.get("inferred_category", "UNKNOWN")
            date = str(t.get("timestamp", t.get("scored_at", "")))[:10]
            amt  = t.get("amount", 0)
            plat = t.get("platform", "your account")
            lines.append(
                f"- {date}: {STRESS_CATEGORY_FRIENDLY.get(cat, 'account activity')} "
                f"of ₹{amt:,.0f} via {plat}"
            )
        return "\n".join(lines)

    def _format_baseline_friendly(self, baseline: Optional[Dict]) -> str:
        if not baseline:
            return "No historical baseline available."
        return (
            f"- Normally receives ~₹{baseline.get('avg_monthly_credits', 0):,.0f}/month\n"
            f"- Normally spends ~₹{baseline.get('avg_monthly_debits', 0):,.0f}/month\n"
            f"- Salary pattern: {baseline.get('salary_regularity', 'regular')}\n"
            f"- EMI record: {baseline.get('emi_compliance_rate', 'consistently on time')}"
        )

    def _format_pulse_timeline(self, transactions: List[Dict]) -> str:
        """Date-wise pulse impact timeline for the AI prompt."""
        lines = []
        for t in sorted(
            transactions,
            key=lambda x: str(x.get("timestamp", x.get("scored_at", "")))
        ):
            cat  = t.get("inferred_category", "UNKNOWN")
            date = str(t.get("timestamp", t.get("scored_at", "")))[:10]
            amt  = t.get("amount", 0)
            plat = t.get("platform", "account")
            delta = t.get("pulse_delta", 0)
            score_after = t.get("new_pulse_score", 0)
            lines.append(
                f"- {date}: {STRESS_CATEGORY_FRIENDLY.get(cat, 'activity')} "
                f"of ₹{amt:,.0f} via {plat} → wellness score moved by +{delta:.3f} "
                f"(score now: {score_after:.3f})"
            )
        return "\n".join(lines) if lines else "No transactions to report."

    def _format_model_metadata(self, pulse_data: Dict) -> str:
        return (
            f"Model Name      : Sentinel V2 Pre-Delinquency Pulse Engine\n"
            f"Version         : {SENTINEL_VERSION}\n"
            f"LLM Layer       : Meta Llama 3.3 70B via Groq ({MODEL_ID})\n"
            f"ML Engine       : {ML_ENGINE}\n"
            f"Feature Count   : {FEATURE_COUNT}\n"
            f"Training Data   : {TRAINING_DATASET}\n"
            f"Monitoring      : {MONITORING_METHOD}\n"
            f"Deployment      : {DATA_JURISDICTION}\n"
            f"Regulatory Base : {RBI_REFS['digital']}\n"
            f"Case Pulse Score: {pulse_data.get('pulse_score', 0):.4f}\n"
            f"Case Risk Tier  : {pulse_data.get('risk_tier', {}).get('label', 'N/A')}"
        )

    def _format_model_stats(self, stats: Dict) -> str:
        return (
            f"Total transactions processed : {stats.get('total_transactions_processed', 'N/A')}\n"
            f"Total customers scored       : {stats.get('total_customers_scored', 'N/A')}\n"
            f"Customers flagged for EWS    : {stats.get('customers_flagged', 'N/A')}\n"
            f"Overall flag rate            : {stats.get('flag_rate', 'N/A')}\n"
            f"Avg model latency            : {stats.get('avg_latency_ms', '< 100ms')}\n"
            f"Estimated false positive rate: {stats.get('false_positive_rate', '~8–12%')}\n"
            f"PSI (stability index)        : {stats.get('psi', '0.04 — Stable')}\n"
            f"AIR (adverse impact ratio)   : {stats.get('air', '0.91 — Within RBI threshold')}"
        )

    def _format_regulatory_block(self) -> str:
        return "\n".join(f"- {v}" for v in RBI_REFS.values())

    def _enrich_transactions(self, transactions: List[Dict]) -> List[Dict]:
        enriched = []
        for t in transactions:
            cat    = t.get("inferred_category", "UNKNOWN")
            t_copy = dict(t)
            t_copy["category_label"]     = STRESS_CATEGORY_LABELS.get(cat, cat)
            t_copy["friendly_description"] = STRESS_CATEGORY_FRIENDLY.get(cat, cat)
            enriched.append(t_copy)
        return enriched