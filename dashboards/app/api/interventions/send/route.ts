import { NextResponse } from 'next/server';
import nodemailer from 'nodemailer';
import { sentinelApi } from '@/lib/api';
import { randomUUID } from 'crypto';

const SENDER_EMAIL = 'testuser1togethr@gmail.com';
const RECEIVER_EMAIL = 'tanmay.vishwakarma24@spit.ac.in';

let cachedTransporter: any = null;

export async function POST(req: Request) {
    // console.log('EMAIL_PASS loaded:', process.env.EMAIL_PASS ? `YES (length: ${process.env.EMAIL_PASS.length})` : 'NO - empty');
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
    const ackUrl = `${baseUrl}/api/interventions/acknowledge?id=${interventionId}`;

    const mailOptions = {
      from: `"Sentinel AI Security" <${SENDER_EMAIL}>`,
      to: RECEIVER_EMAIL,
      subject: `[URGENT] Risk Tier Alert: ${risk_tier} for ${first_name} ${last_name}`,
      html: `
        <!DOCTYPE html>
        <html>
          <head>
            <meta charset="utf-8">
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
              .btn { background-color: #2563eb; color: #ffffff !important; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; display: inline-block; font-size: 16px; }
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
                  <p>Your institutional risk profile has been classified under the <strong>${risk_tier}</strong> tier based on recent transaction patterns and behavioral signals.</p>
                </div>
                <p>As part of our regulatory protocol, we require all high-risk profile updates to be acknowledged by the account holder. Please click the button below to acknowledge this alert.</p>
                <div class="btn-container">
                  <a href="${ackUrl}" class="btn">Acknowledge Alert</a>
                </div>
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

    // Send the email
    if (cachedTransporter) {
      await cachedTransporter.sendMail(mailOptions);
    } else {
      console.log(`[SIMULATED EMAIL] Would send to ${RECEIVER_EMAIL} for ${first_name} ${last_name}`);
    }

    // Only record in DB after successful send
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