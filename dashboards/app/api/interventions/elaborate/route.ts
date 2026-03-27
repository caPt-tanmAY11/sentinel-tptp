// dashboards/app/api/interventions/elaborate/route.ts
// NEW FILE — create folder: dashboards/app/api/interventions/elaborate/

import { NextResponse } from 'next/server';

const GROQ_BASE_URL = 'https://api.groq.com/openai/v1';
const MODEL_ID      = 'llama-3.3-70b-versatile';

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const {
      relief_title,
      relief_description,
      officer_note,
      customer_name,
      risk_tier,
      risk_score,
      anomaly_score,
    } = body;

    const GROQ_API_KEY = process.env.GROQ_API_KEY || '';

    if (!GROQ_API_KEY) {
      // Fallback when key is not configured
      return NextResponse.json({
        elaboration: `
RECOMMENDED RELIEF MEASURE: ${relief_title}

${relief_description}

This relief measure has been specifically selected for your account by your designated Credit Officer after a thorough review of your recent transaction history and financial standing. The purpose of this measure is to provide you with a structured pathway to stabilise your financial obligations and reduce further risk to your account standing.

You are encouraged to engage proactively with your Credit Officer to understand the full scope of this arrangement and to ensure you meet all requirements associated with this relief option.

${officer_note ? `OFFICER'S NOTE:\n"${officer_note}"\n\nPlease treat the above note as a direct communication from your reviewing officer and act accordingly.` : ''}

If you have any questions or concerns about this recommendation, please contact your branch at the earliest opportunity.
        `.trim(),
      });
    }

    const prompt = `You are a senior banking compliance officer at an Indian financial institution writing directly to a customer.

Context about this customer:
- Name: ${customer_name}
- Risk Tier: ${risk_tier}
- Risk Score: ${risk_score ?? 'N/A'} (0–100, higher is riskier)
- Anomaly Score: ${anomaly_score ?? 'N/A'} (0–1)

The reviewing officer has selected the following relief measure for this customer:
- Relief Title: ${relief_title}
- Relief Summary: ${relief_description}
${officer_note ? `- Officer's Personal Note: "${officer_note}"` : ''}

Write a detailed, empathetic, and professional section for the customer's compliance report explaining:
1. What this relief measure is and exactly what it means for their account
2. Why it was chosen specifically for their situation (based on the risk tier and scores)
3. What practical steps the customer needs to take to benefit from it
4. What happens if they do not respond or take action
5. Their rights under this arrangement (in line with RBI guidelines and Indian banking regulations)
6. How to contact their Credit Officer for questions
${officer_note ? `7. A formal acknowledgement of the officer's personal note, rephrased for the customer` : ''}

Write in plain, respectful English that a regular bank customer in India can easily understand. Do not use jargon. 
Do not use markdown, bullet points, or headers — write in flowing prose paragraphs only.
Write approximately 300–400 words. Be warm, clear, and reassuring in tone while remaining professional.
Start directly with the content — do not say "Here is the section" or similar preamble.`;

    const groqRes = await fetch(`${GROQ_BASE_URL}/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${GROQ_API_KEY}`,
      },
      body: JSON.stringify({
        model: MODEL_ID,
        max_tokens: 700,
        temperature: 0.5,
        messages: [{ role: 'user', content: prompt }],
      }),
    });

    if (!groqRes.ok) {
      const errText = await groqRes.text();
      throw new Error(`GROQ API error: ${groqRes.status} — ${errText}`);
    }

    const groqData   = await groqRes.json();
    const elaboration = groqData.choices?.[0]?.message?.content?.trim() || '';

    return NextResponse.json({ elaboration });

  } catch (err: any) {
    console.error('Elaborate route error:', err);
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}