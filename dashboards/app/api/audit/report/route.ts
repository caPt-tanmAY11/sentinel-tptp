// dashboards/app/api/audit/report/route.ts
// NEW FILE — create folder: dashboards/app/api/audit/

import { NextResponse } from 'next/server';

const GROQ_BASE_URL = 'https://api.groq.com/openai/v1';
const MODEL_ID      = 'llama-3.3-70b-versatile';

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const {
      total_customers = 0,
      critical_count  = 0,
      high_count      = 0,
      moderate_count  = 0,
      watch_count     = 0,
      stable_count    = 0,
      avg_pulse_score = 0,
      scored_customers = 0,
      high_severity_24h = 0,
      total_interventions = 0,
      system_pulse    = 84,
      generated_at,
    } = body;

    const GROQ_API_KEY = process.env.GROQ_API_KEY || '';

    if (!GROQ_API_KEY) {
      return NextResponse.json({ error: 'GROQ_API_KEY not configured' }, { status: 500 });
    }

    const prompt = `You are a senior legal and compliance officer at Barclays India, writing a formal internal audit report on the bank's use of its Sentinel AI V2 pre-delinquency detection system.

Current system statistics as of ${generated_at || new Date().toISOString().slice(0, 10)}:
- Total customers monitored: ${total_customers.toLocaleString('en-IN')}
- Customers scored by AI: ${scored_customers.toLocaleString('en-IN')} (${total_customers > 0 ? ((scored_customers / total_customers) * 100).toFixed(1) : 0}%)
- Risk breakdown: CRITICAL: ${critical_count}, HIGH: ${high_count}, MODERATE: ${moderate_count}, WATCH: ${watch_count}, STABLE: ${stable_count}
- Average pulse risk score: ${(avg_pulse_score * 100).toFixed(2)} / 100
- High-severity events in last 24h: ${high_severity_24h}
- Total interventions triggered: ${total_interventions}
- System health index: ${system_pulse} / 100

Write a comprehensive formal audit report with the following 8 sections. Use professional legal and banking language. Be specific, cite actual RBI circulars, GOI acts, and DPDP Act 2023 provisions. Do not make up circular numbers — only reference ones that genuinely exist or are well-known. Each section must be substantial (at least 3–4 paragraphs).

SECTION 1: EXECUTIVE SUMMARY
Overview of the audit, its purpose, scope, and principal findings. Include the date of report generation and system version (Sentinel V2).

SECTION 2: SYSTEM DESCRIPTION & AI METHODOLOGY
Explain what Sentinel AI V2 does: real-time transaction scoring using a pulse engine, anomaly detection, behavioral drift analysis, risk tier classification (CRITICAL/HIGH/MODERATE/WATCH/STABLE), and pre-delinquency intervention workflows. Explain how the scoring model works at a high level.

SECTION 3: RBI REGULATORY COMPLIANCE
Map the system's operations to RBI guidelines. Cover:
- RBI Master Direction on KYC (2016, updated 2023)
- RBI Circular on Fair Practices Code for Lenders
- RBI Guidelines on Digital Lending (2022)
- RBI Framework for Outsourcing of Financial Services
- IBA Pre-Delinquency Management Guidelines
- Basel III risk management standards as adopted by RBI
Assess whether Sentinel V2 complies with each, and note the specific system feature that achieves compliance.

SECTION 4: GOVERNMENT OF INDIA LEGAL COMPLIANCE
Cover compliance with:
- Digital Personal Data Protection Act, 2023 (DPDPA) — data minimisation, purpose limitation, consent architecture
- Information Technology Act, 2000 and IT (Amendment) Act, 2008 — data security and breach obligations
- Prevention of Money Laundering Act, 2002 (PMLA) — transaction monitoring obligations
- Consumer Protection Act, 2019 — fair treatment of bank customers
- Credit Information Companies (Regulation) Act, 2005 — credit data handling

SECTION 5: AI ETHICS, FAIRNESS & EXPLAINABILITY
Assess the system against responsible AI principles:
- Algorithmic fairness — whether risk scores can discriminate on protected characteristics
- Explainability obligations — does the system provide reasons for tier classification?
- Human oversight — is there mandatory human review before adverse action?
- Model drift monitoring — how is the AI kept accurate over time?
- Right to contest automated decisions (Article 21 of the Constitution of India)

SECTION 6: DATA GOVERNANCE & PRIVACY
- Data retention policies for transaction records and risk scores
- Access controls and role-based permissions for officer dashboard
- Encryption standards for data in transit and at rest
- Audit trails and immutable logs of all AI decisions
- Data localisation compliance (RBI mandate for payment data)
- Third-party integrations and data sharing boundaries

SECTION 7: INTERVENTION PROCESS COMPLIANCE
Evaluate the customer intervention workflow:
- Legal validity of automated risk-tier emails
- Officer review requirement before email dispatch (manual send button)
- Customer grievance mechanism via the grievance portal
- Acknowledgement workflow and legal enforceability
- Anti-spam compliance and TRAI regulations
- Record keeping of all intervention communications

SECTION 8: FINDINGS, RISK RATINGS & RECOMMENDATIONS
Provide:
- An overall compliance rating (COMPLIANT / PARTIALLY COMPLIANT / NON-COMPLIANT) with brief justification
- 3–5 specific recommendations to further strengthen compliance
- A forward-looking note on upcoming regulatory changes (e.g., RBI's AI/ML governance framework, DPDPA implementation rules)
- Sign-off statement

Write the full report now. Use clear section headers in ALL CAPS followed by a colon. Write in formal prose — no bullet points, no numbered lists, no markdown. Paragraphs only.`;

    const groqRes = await fetch(`${GROQ_BASE_URL}/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${GROQ_API_KEY}`,
      },
      body: JSON.stringify({
        model: MODEL_ID,
        max_tokens: 4000,
        temperature: 0.3,
        messages: [{ role: 'user', content: prompt }],
      }),
    });

    if (!groqRes.ok) {
      const errText = await groqRes.text();
      throw new Error(`GROQ API error: ${groqRes.status} — ${errText}`);
    }

    const groqData = await groqRes.json();
    const report   = groqData.choices?.[0]?.message?.content?.trim() || '';

    return NextResponse.json({
      report,
      generated_at: new Date().toISOString(),
      model:        MODEL_ID,
      stats: { total_customers, critical_count, high_count, moderate_count, watch_count, stable_count, avg_pulse_score, scored_customers, high_severity_24h, total_interventions },
    });

  } catch (err: any) {
    console.error('Audit report route error:', err);
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}