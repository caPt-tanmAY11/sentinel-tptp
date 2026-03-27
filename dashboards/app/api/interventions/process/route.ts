import { NextResponse } from 'next/server';
import nodemailer from 'nodemailer';
import { sentinelApi } from '@/lib/api';
import { randomUUID } from 'crypto';

const SENDER_EMAIL = process.env.SENDER_EMAIL || 'default@example.com';
const RECEIVER_EMAIL = process.env.RECEIVER_EMAIL || 'default@example.com';

let cachedTransporter: any = null;

export async function POST() {
  try {
    const PASS = process.env.EMAIL_PASS || '';
    
    const pendingRes = await sentinelApi.getPendingInterventions();
    const pending = pendingRes.data.pending || [];

    if (pending.length === 0) {
      return NextResponse.json({ message: 'No pending interventions to process.', count: 0 });
    }

    if (PASS && !cachedTransporter) {
      cachedTransporter = nodemailer.createTransport({
        service: 'gmail',
        auth: {
          user: SENDER_EMAIL,
          pass: PASS,
        },
        pool: true, // Use pooled connections for better performance
      });
    }

    let sentCount = 0;

    for (const customer of pending) {
      try {
        const baseUrl = process.env.NEXT_PUBLIC_BASE_URL || 'http://localhost:3000';
        const interventionId = randomUUID();
        const ackUrl = `${baseUrl}/api/interventions/acknowledge?id=${interventionId}`;
        
        const mailOptions = {
          from: `"Sentinel AI Security" <${SENDER_EMAIL}>`,
          to: RECEIVER_EMAIL,
          subject: `[URGENT] Risk Tier Alert: ${customer.risk_tier} for ${customer.first_name} ${customer.last_name}`,
          html: `
            <!DOCTYPE html>
            <html>
              <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Sentinel AI Alert</title>
                <style>
                  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
                  body { font-family: 'Inter', Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 0; -webkit-font-smoothing: antialiased; }
                  .email-wrapper { max-width: 600px; margin: 40px auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06); border: 1px solid #e2e8f0; }
                  .header { background-color: ${customer.risk_tier === 'CRITICAL' ? '#ef4444' : '#f59e0b'}; padding: 32px 40px; text-align: center; color: #ffffff; }
                  .header h2 { margin: 0; font-size: 24px; font-weight: 700; letter-spacing: -0.5px; }
                  .header-subtitle { margin-top: 8px; font-size: 15px; opacity: 0.9; font-weight: 500; }
                  .body-content { padding: 40px; color: #334155; line-height: 1.6; }
                  .body-content p { margin: 0 0 16px 0; font-size: 16px; }
                  .highlight-box { background-color: #f1f5f9; border-left: 4px solid ${customer.risk_tier === 'CRITICAL' ? '#ef4444' : '#f59e0b'}; padding: 20px; border-radius: 0 8px 8px 0; margin: 24px 0; }
                  .highlight-box p { margin: 0; font-size: 15px; font-weight: 500; color: #0f172a; }
                  .btn-container { text-align: center; margin: 40px 0 20px 0; }
                  .btn { background-color: #2563eb; color: #ffffff !important; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; display: inline-block; font-size: 16px; box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.2); }
                  .footer { background-color: #f8fafc; padding: 32px 40px; border-top: 1px solid #e2e8f0; text-align: center; }
                  .footer p { margin: 0 0 8px 0; font-size: 13px; color: #64748b; }
                  .logo-text { font-weight: 700; color: #1e293b; font-size: 18px; margin-bottom: 16px; display: block; }
                </style>
              </head>
              <body>
                <div class="email-wrapper">
                  <div class="header">
                    <h2>Mandatory Risk Alert</h2>
                    <div class="header-subtitle">Account Status Update</div>
                  </div>
                  <div class="body-content">
                    <p>Dear <strong>${customer.first_name} ${customer.last_name}</strong>,</p>
                    <p>This is an automated notification from the Sentinel AI compliance and monitoring system.</p>
                    
                    <div class="highlight-box">
                      <p>Your institutional risk profile has recently met the threshold for the <strong>${customer.risk_tier}</strong> tier based on recent platform activity and transaction patterns.</p>
                    </div>

                    <p>As part of our regulatory protocol, we require all high-risk profile updates to be acknowledged by the account holder. Failure to acknowledge this alert may result in temporary account restrictions.</p>
                    
                    <div class="btn-container">
                      <a href="${ackUrl}" class="btn">Acknowledge Alert</a>
                    </div>
                  </div>
                  <div class="footer">
                    <span class="logo-text">Sentinel AI Security</span>
                    <p>If you believe this alert was sent in error or need assistance, please contact your designated Credit Officer.</p>
                    <p>&copy; ${new Date().getFullYear()} Sentinel AI Security Operations. All rights reserved.</p>
                  </div>
                </div>
              </body>
            </html>
          `
        };

        // Attempt to send email first
        if (cachedTransporter) {
          await cachedTransporter.sendMail(mailOptions);
        } else {
          console.log(`[SIMULATED EMAIL] Sent to ${RECEIVER_EMAIL} for ${customer.first_name}`);
        }
        
        // Only if email succeeds (no error thrown), record it in the DB
        await sentinelApi.createIntervention(customer.customer_id, customer.risk_tier, interventionId);
        
        sentCount++;
      } catch (innerErr) {
        console.error(`Failed to process customer ${customer.customer_id}. Email may not have been sent. Error:`, innerErr);
        // The intervention is NOT saved to the DB if the email fails, 
        // allowing it to be safely retried in the next batch.
      }
    }

    return NextResponse.json({ message: `Successfully processed ${sentCount} out of ${pending.length} pending interventions.`, count: sentCount });
  } catch (err: any) {
    console.error('Error processing interventions:', err);
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
