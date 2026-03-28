// dashboards/app/api/fraud/alert/route.ts

import { NextResponse } from 'next/server';
import nodemailer from 'nodemailer';
import { sentinelApi } from '@/lib/api';

const SENDER_EMAIL   = process.env.SENDER_EMAIL   || 'default@example.com';
const RECEIVER_EMAIL = process.env.RECEIVER_EMAIL || 'default@example.com';

let cachedTransporter: any = null;

// ── Helper: badge row for each signal that fired ────────────────────────────
function signalBadges(
  international: boolean,
  amountSpike:   boolean,
  freqSpike:     boolean,
): string {
  const badges: string[] = [];
  if (international) badges.push(`
    <span style="display:inline-block;background:#fef3c7;color:#92400e;
                 border:1px solid #fcd34d;border-radius:20px;
                 padding:4px 12px;font-size:12px;font-weight:700;margin:4px;">
      🌐 International Transaction
    </span>`);
  if (amountSpike) badges.push(`
    <span style="display:inline-block;background:#fee2e2;color:#991b1b;
                 border:1px solid #fca5a5;border-radius:20px;
                 padding:4px 12px;font-size:12px;font-weight:700;margin:4px;">
      💸 Unusual Amount
    </span>`);
  if (freqSpike) badges.push(`
    <span style="display:inline-block;background:#ede9fe;color:#5b21b6;
                 border:1px solid #c4b5fd;border-radius:20px;
                 padding:4px 12px;font-size:12px;font-weight:700;margin:4px;">
      ⚡ Abnormal Frequency
    </span>`);
  return badges.join('');
}

// ── Helper: EMI warning block (only shown when holiday is suggested) ─────────
function emiWarningBlock(
  paymentHolidaySuggested: boolean,
  nextEmiDueDate:          string | null,
  emiAmount:               number | null,
): string {
  if (!paymentHolidaySuggested || !nextEmiDueDate) return '';

  const formatted = new Date(nextEmiDueDate).toLocaleDateString('en-IN', {
    day: 'numeric', month: 'long', year: 'numeric',
  });
  const amountStr = emiAmount
    ? `₹${emiAmount.toLocaleString('en-IN')}`
    : 'your upcoming EMI';

  return `
    <div style="margin:24px 0;background:#f0fdf4;border-left:4px solid #22c55e;
                border-radius:0 8px 8px 0;padding:20px;">
      <p style="margin:0 0 6px 0;font-size:14px;font-weight:700;color:#15803d;">
        💡 Payment Holiday Available
      </p>
      <p style="margin:0;font-size:14px;color:#166534;line-height:1.6;">
        Your next EMI of <strong>${amountStr}</strong> is due on
        <strong>${formatted}</strong>. Given the suspicious activity on your
        account, you may be eligible for a <strong>payment holiday</strong>.
        Please contact your Credit Officer immediately to discuss this option
        before the due date.
      </p>
    </div>`;
}

// ── Main handler ─────────────────────────────────────────────────────────────
export async function POST(req: Request) {
  try {
    const body = await req.json();
    const {
      alert_id,
      customer_id,
      first_name,
      last_name,
      txn_amount,
      platform,
      receiver_vpa,
      receiver_country,
      currency,
      fraud_score,
      fraud_reason,
      signal_international,
      signal_amount_spike,
      signal_freq_spike,
      payment_holiday_suggested,
      next_emi_due_date,
      emi_amount,
    } = body;

    // ── Validate required fields ───────────────────────────────────────────
    if (!alert_id || !customer_id || !first_name || !last_name) {
      return NextResponse.json(
        { error: 'Missing required fields: alert_id, customer_id, first_name, last_name' },
        { status: 400 },
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

    // ── Build email content ────────────────────────────────────────────────
    const fraudScorePct  = Math.round((fraud_score ?? 0) * 100);
    const amountFormatted = `₹${Number(txn_amount ?? 0).toLocaleString('en-IN')}`;
    const isInternational = currency !== 'INR' || receiver_country !== 'IN';

    // Receiver line — show VPA if present, else country
    const receiverLine = receiver_vpa
      ? `<strong>${receiver_vpa}</strong>${isInternational ? ` (${receiver_country})` : ''}`
      : isInternational
        ? `International receiver (${receiver_country})`
        : 'Unknown receiver';

    const mailOptions = {
      from:    `"Sentinel AI Security" <${SENDER_EMAIL}>`,
      to:      RECEIVER_EMAIL,
      subject: `[SECURITY ALERT] Suspicious Transaction Detected on Your Account`,
      html: `
        <!DOCTYPE html>
        <html>
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
              body { font-family: Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 0; }
              .wrapper { max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; }
              .header { background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%); padding: 32px 40px; text-align: center; color: #fff; }
              .header h2 { margin: 0; font-size: 22px; font-weight: 700; letter-spacing: 0.5px; }
              .header-sub { margin-top: 8px; font-size: 14px; opacity: 0.9; }
              .body-content { padding: 36px 40px; color: #334155; line-height: 1.6; }
              .body-content p { margin: 0 0 14px 0; font-size: 15px; }
              .txn-box { background: #fef2f2; border: 1px solid #fecaca; border-radius: 10px; padding: 20px 24px; margin: 20px 0; }
              .txn-box table { width: 100%; border-collapse: collapse; }
              .txn-box td { padding: 5px 0; font-size: 14px; color: #374151; }
              .txn-box td:first-child { color: #6b7280; width: 140px; }
              .score-bar-wrap { background: #f1f5f9; border-radius: 8px; height: 10px; overflow: hidden; margin: 6px 0 16px; }
              .score-bar-fill { height: 10px; border-radius: 8px; background: linear-gradient(90deg, #f59e0b, #dc2626); }
              .signals-wrap { margin: 20px 0; text-align: center; }
              .steps-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 18px 22px; margin: 20px 0; }
              .steps-box p { margin: 0 0 8px 0; font-size: 14px; color: #475569; }
              .steps-box p:last-child { margin: 0; }
              .footer { background: #f8fafc; padding: 28px 40px; border-top: 1px solid #e2e8f0; text-align: center; }
              .footer p { margin: 0 0 6px 0; font-size: 12px; color: #64748b; }
            </style>
          </head>
          <body>
            <div class="wrapper">

              <!-- Header -->
              <div class="header">
                <h2>⚠️ Suspicious Transaction Alert</h2>
                <div class="header-sub">Sentinel AI Security — Probable Fault Detection</div>
              </div>

              <!-- Body -->
              <div class="body-content">
                <p>Dear <strong>${first_name} ${last_name}</strong>,</p>
                <p>
                  Our AI security system has flagged a potentially suspicious transaction
                  on your account. This transaction has been <strong>temporarily
                  quarantined</strong> and will <strong>not affect your risk score</strong>
                  until reviewed.
                </p>

                <!-- Transaction details -->
                <p style="margin:0 0 8px 0;font-size:14px;font-weight:600;color:#0f172a;">
                  🔍 Flagged Transaction Details
                </p>
                <div class="txn-box">
                  <table>
                    <tr>
                      <td>Amount</td>
                      <td><strong>${amountFormatted} ${currency ?? 'INR'}</strong></td>
                    </tr>
                    <tr>
                      <td>Platform</td>
                      <td>${platform ?? '—'}</td>
                    </tr>
                    <tr>
                      <td>Receiver</td>
                      <td>${receiverLine}</td>
                    </tr>
                  </table>
                </div>

                <!-- Fraud score -->
                <p style="margin:0 0 4px 0;font-size:14px;font-weight:600;color:#0f172a;">
                  🧠 Suspicion Score: ${fraudScorePct}%
                </p>
                <div class="score-bar-wrap">
                  <div class="score-bar-fill" style="width:${fraudScorePct}%;"></div>
                </div>

                <!-- Signal badges -->
                <p style="margin:0 0 8px 0;font-size:14px;font-weight:600;color:#0f172a;">
                  🚨 Signals Detected
                </p>
                <div class="signals-wrap">
                  ${signalBadges(signal_international, signal_amount_spike, signal_freq_spike)}
                </div>

                <!-- Reason -->
                <div style="margin:20px 0;background:#fafafa;border:1px solid #e2e8f0;
                            border-radius:8px;padding:16px;">
                  <p style="margin:0 0 6px 0;font-size:13px;font-weight:600;color:#374151;">
                    System Analysis
                  </p>
                  <p style="margin:0;font-size:13px;color:#64748b;font-style:italic;line-height:1.6;">
                    "${fraud_reason ?? 'Anomalous transaction pattern detected'}"
                  </p>
                </div>

                <!-- EMI / payment holiday block (conditional) -->
                ${emiWarningBlock(payment_holiday_suggested, next_emi_due_date, emi_amount)}

                <!-- What to do -->
                <div class="steps-box">
                  <p><strong>What should you do?</strong></p>
                  <p>✅ <strong>If this was you:</strong> Contact your Credit Officer to confirm and release the transaction.</p>
                  <p>🚫 <strong>If this was NOT you:</strong> Call our fraud helpline immediately and request an account freeze.</p>
                  <p>⏳ <strong>Do not ignore this alert</strong> — unreviewed alerts are automatically escalated after 48 hours.</p>
                </div>

                <p style="font-size:13px;color:#94a3b8;text-align:center;margin-top:8px;">
                  Alert ID: <code>${alert_id}</code> — Keep this for your records.
                </p>
              </div>

              <!-- Footer -->
              <div class="footer">
                <p><strong>Sentinel AI Security</strong></p>
                <p>This is an automated security alert. Do not reply to this email.</p>
                <p>&copy; ${new Date().getFullYear()} Sentinel AI Security Operations.</p>
              </div>
            </div>
          </body>
        </html>
      `,
    };

    // ── Send (or simulate) ─────────────────────────────────────────────────
    if (cachedTransporter) {
      await cachedTransporter.sendMail(mailOptions);
    } else {
      console.log(`[SIMULATED FRAUD ALERT] Would send to ${RECEIVER_EMAIL}`);
      console.log(`[SIMULATED] Alert ID: ${alert_id} | Customer: ${first_name} ${last_name}`);
      console.log(`[SIMULATED] Fraud score: ${fraudScorePct}% | Reason: ${fraud_reason}`);
    }

    // ── Stamp alert_email_sent on the FastAPI side ─────────────────────────
    try {
      await sentinelApi.markFraudAlertEmailSent(alert_id);
    } catch (stampErr) {
      // Non-fatal — email was sent, just the stamp failed. Log and continue.
      console.error('[PFD] Failed to stamp alert_email_sent:', stampErr);
    }

    return NextResponse.json({
      success:    true,
      alert_id,
      message:    `Fraud alert email sent for ${first_name} ${last_name}`,
      email_sent: !!cachedTransporter,
    });

  } catch (err: any) {
    console.error('[PFD] Failed to send fraud alert email:', err);
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}