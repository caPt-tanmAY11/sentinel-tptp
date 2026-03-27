// dashboards/app/api/interventions/suggest/route.ts

import { NextResponse } from 'next/server';

const GROQ_BASE_URL = 'https://api.groq.com/openai/v1';
const MODEL_ID      = 'llama-3.3-70b-versatile';

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const {
      first_name,
      last_name,
      risk_tier,
      risk_score,
      anomaly_score,
      txn_severity,
    } = body;

    const GROQ_API_KEY = process.env.GROQ_API_KEY || '';


    const prompt = `You are a senior credit risk officer at an Indian financial institution.

A customer has been flagged with the following risk profile:
- Name: ${first_name} ${last_name}
- Risk Tier: ${risk_tier}
- Risk Score: ${risk_score ?? 'N/A'} (0–100, higher = riskier)
- Anomaly Score: ${anomaly_score ?? 'N/A'} (0–1, higher = more anomalous)
- Transaction Severity: ${txn_severity ?? 'N/A'} (0–1)

Generate exactly 3 distinct relief/intervention options that an officer could offer this customer.
Each option must be realistic, specific to Indian banking, and proportionate to the risk tier.

Respond ONLY with a valid JSON array with exactly 3 objects. No markdown, no explanation, no extra text.
Each object must have exactly these keys:
- "id": number (1, 2, or 3)
- "title": short name of the relief measure (max 5 words)
- "description": one clear sentence explaining what this measure involves and what it achieves for the customer

Example format:
[{"id":1,"title":"...","description":"..."},{"id":2,"title":"...","description":"..."},{"id":3,"title":"...","description":"..."}]`;

    const groqRes = await fetch(`${GROQ_BASE_URL}/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${GROQ_API_KEY}`,
      },
      body: JSON.stringify({
        model: MODEL_ID,
        max_tokens: 500,
        temperature: 0.7,
        messages: [{ role: 'user', content: prompt }],
      }),
    });

    if (!groqRes.ok) {
      const errText = await groqRes.text();
      throw new Error(`GROQ API error: ${groqRes.status} — ${errText}`);
    }

    const groqData = await groqRes.json();
    const rawText = groqData.choices?.[0]?.message?.content || '[]';

    // Strip any accidental markdown fences
    const cleaned = rawText.replace(/```json|```/g, '').trim();
    const suggestions = JSON.parse(cleaned);

    return NextResponse.json({ suggestions });
  } catch (err: any) {
    console.error('Suggest route error:', err);
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}