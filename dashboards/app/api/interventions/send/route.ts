// dashboards/app/api/interventions/send/route.ts

import { NextResponse } from 'next/server';
import nodemailer from 'nodemailer';
import { sentinelApi } from '@/lib/api';
import { randomUUID } from 'crypto';

const SENDER_EMAIL = 'testuser1togethr@gmail.com';
const RECEIVER_EMAIL = 'tanmay.vishwakarma24@spit.ac.in';

let cachedTransporter: any = null;

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const { customer_id, first_name, last_name, risk_tier } = body;

    if (!customer_id || !first_name || !last_name || !risk_tier) {
      return NextResponse.json(
        { error: 'Missing required fields: customer_id, first_name, last_name, risk_tier' },
        { status: 400 }
      );
    }

    const PASS = process.env.EMAIL_PASS || '';

    if (PASS && !cachedTransporter) {
      cachedTransporter = nodemailer.createTransport({
        service: 'gmail',
        auth: { user: SENDER_EMAIL, pass: PASS },
        pool: true,
      });
    }

    const baseUrl = process.env.NEXT_PUBLIC_BASE_URL || 'http://localhost:3000';
    const interventionId = randomUUID();

    // ✅ NEW: Single button URL — points to the report page WITH interventionId in query
    const reportUrl = `${baseUrl}/report/${customer_id}?interventionId=${interventionId}`;

    const mailOptions = {
      from: `"Sentinel AI Security" <${SENDER_EMAIL}>`,
      to: RECEIVER_EMAIL,
      subject: `[URGENT] Risk Tier Alert: ${risk_tier} — Action Required`,
      html: `
        <!DOCTYPE html>
        <html>
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
              body { font-family: Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 0; }
              .email-wrapper { max-width: 600px; margin: 40px auto; background: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; }
              .header { background-color: ${risk_tier === 'CRITICAL' ? '#ef4444' : '#f59e0b'}; padding: 32px 40px; text-align: center; color: #fff; }
              .header h2 { margin: 0; font-size: 24px; font-weight: 700; }
              .header-subtitle { margin-top: 8px; font-size: 15px; opacity: 0.9; }
              .body-content { padding: 40px; color: #334155; line-height: 1.6; }
              .body-content p { margin: 0 0 16px 0; font-size: 16px; }
              .highlight-box { background-color: #f1f5f9; border-left: 4px solid ${risk_tier === 'CRITICAL' ? '#ef4444' : '#f59e0b'}; padding: 20px; border-radius: 0 8px 8px 0; margin: 24px 0; }
              .highlight-box p { margin: 0; font-size: 15px; font-weight: 500; color: #0f172a; }
              .btn-container { text-align: center; margin: 40px 0 20px 0; }
              /* ✅ ONE button only */
              .btn-primary { background-color: #002C77; color: #ffffff !important; padding: 16px 36px; text-decoration: none; border-radius: 8px; font-weight: 700; display: inline-block; font-size: 16px; letter-spacing: 0.3px; }
              .steps-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px 24px; margin: 24px 0; }
              .steps-box p { margin: 0 0 8px 0; font-size: 14px; color: #475569; }
              .steps-box p:last-child { margin: 0; }
              .footer { background-color: #f8fafc; padding: 32px 40px; border-top: 1px solid #e2e8f0; text-align: center; }
              .footer p { margin: 0 0 8px 0; font-size: 13px; color: #64748b; }
            </style>
          </head>
          <body>
            <div class="email-wrapper">
              <div class="header">
                <h2>Mandatory Risk Alert</h2>
                <div class="header-subtitle">Account Status Update — ${risk_tier}</div>
              </div>
              <div class="body-content">
                <p>Dear <strong>${first_name} ${last_name}</strong>,</p>
                <p>This is a notification from the Sentinel AI compliance and monitoring system.</p>

                <div class="highlight-box">
                  <p>Your institutional risk profile has been classified under the <strong>${risk_tier}</strong> tier based on recent transaction patterns and behavioural signals.</p>
                </div>

                <p>As part of our regulatory protocol, you are required to review your compliance report and formally acknowledge it. Please use the button below:</p>

                <div class="steps-box">
                  <p>📋 <strong>Step 1:</strong> Click the button to open your full compliance report</p>
                  <p>📖 <strong>Step 2:</strong> Read through the complete report</p>
                  <p>✅ <strong>Step 3:</strong> Acknowledge once you have reviewed it</p>
                </div>

                <div class="btn-container">
                  <a href="${reportUrl}" class="btn-primary">View &amp; Acknowledge Report</a>
                </div>

                <p style="font-size: 13px; color: #94a3b8; text-align: center; margin-top: 8px;">
                  This link is unique to your account. Do not share it with others.
                </p>
              </div>
              <div class="footer">
                <p><strong>Sentinel AI Security</strong></p>
                <p>If you need assistance, please contact your designated Credit Officer.</p>
                <p>&copy; ${new Date().getFullYear()} Sentinel AI Security Operations.</p>
              </div>
            </div>
          </body>
        </html>
      `,
    };

    // Send email
    if (cachedTransporter) {
      await cachedTransporter.sendMail(mailOptions);
    } else {
      console.log(`[SIMULATED EMAIL] Would send to ${RECEIVER_EMAIL} for ${first_name} ${last_name}`);
      console.log(`[SIMULATED] Report URL: ${reportUrl}`);
    }

    // Record in DB only after successful send
    await sentinelApi.createIntervention(customer_id, risk_tier, interventionId);

    return NextResponse.json({
      success: true,
      message: `Email sent for ${first_name} ${last_name}`,
      intervention_id: interventionId,
    });

  } catch (err: any) {
    console.error('Failed to send intervention email:', err);
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}