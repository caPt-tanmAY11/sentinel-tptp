import { NextResponse } from 'next/server';
import nodemailer from 'nodemailer';

const SENDER_EMAIL = process.env.SENDER_EMAIL || 'your_new_gmail@gmail.com';
const BANK_EMAIL = SENDER_EMAIL; // Grievance goes back to the bank's email
const PASS = process.env.EMAIL_PASS || '';

let cachedTransporter: any = null;

async function getTransporter() {
  if (cachedTransporter) return cachedTransporter;

  if (PASS) {
    cachedTransporter = nodemailer.createTransport({
      service: 'gmail',
      auth: { user: SENDER_EMAIL, pass: PASS },
      pool: true,
    });
  } else {
    const testAccount = await nodemailer.createTestAccount();
    cachedTransporter = nodemailer.createTransport({
      host: 'smtp.ethereal.email',
      port: 587,
      secure: false,
      auth: { user: testAccount.user, pass: testAccount.pass },
    });
    console.log('📧 Using Ethereal test account:', testAccount.user);
  }

  return cachedTransporter;
}

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const { intervention_id, message } = body;

    if (!intervention_id || !message?.trim()) {
      return NextResponse.json(
        { error: 'Missing intervention_id or message' },
        { status: 400 }
      );
    }

    // ── 1. Fetch intervention + customer details from FastAPI backend ──
    const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';
    const detailsRes = await fetch(`${apiBase}/interventions/${intervention_id}/details`);

    if (!detailsRes.ok) {
      return NextResponse.json(
        { error: 'Intervention not found or expired.' },
        { status: 404 }
      );
    }

    const details = await detailsRes.json();
    const { customer_name, customer_id, risk_tier } = details;

    // ── 2. Save grievance to DB via FastAPI ──
    const saveRes = await fetch(`${apiBase}/grievances`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        intervention_id,
        customer_id,
        customer_name,
        message: message.trim(),
      }),
    });

    if (!saveRes.ok) {
      const err = await saveRes.json();
      return NextResponse.json(
        { error: err.detail || 'Failed to save grievance.' },
        { status: 500 }
      );
    }

    const saved = await saveRes.json();

    // ── 3. Email the bank officer ──
    const transporter = await getTransporter();

    const mailOptions = {
      from: `"Sentinel AI Security" <${SENDER_EMAIL}>`,
      to: BANK_EMAIL,
      subject: `[GRIEVANCE] New query from ${customer_name} — ${risk_tier} Tier`,
      html: `
        <!DOCTYPE html>
        <html>
          <head>
            <meta charset="utf-8">
            <style>
              body { font-family: Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 0; }
              .wrapper { max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; }
              .header { background-color: #2563eb; padding: 28px 40px; color: #fff; }
              .header h2 { margin: 0; font-size: 22px; font-weight: 700; }
              .header p { margin: 6px 0 0 0; font-size: 14px; opacity: 0.85; }
              .body { padding: 36px 40px; color: #334155; }
              .body p { margin: 0 0 14px 0; font-size: 15px; line-height: 1.6; }
              .info-grid { background: #f1f5f9; border-radius: 8px; padding: 20px; margin: 20px 0; }
              .info-row { display: flex; justify-content: space-between; margin-bottom: 10px; font-size: 14px; }
              .info-row:last-child { margin-bottom: 0; }
              .info-label { color: #64748b; font-weight: 600; }
              .info-value { color: #0f172a; font-weight: 500; }
              .message-box { background: #fffbeb; border-left: 4px solid #f59e0b; padding: 18px 20px; border-radius: 0 8px 8px 0; margin: 20px 0; }
              .message-box p { margin: 0; font-size: 15px; color: #0f172a; line-height: 1.7; }
              .tier-badge { display: inline-block; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 700; background: ${risk_tier === 'CRITICAL' ? '#fee2e2' : '#fef3c7'}; color: ${risk_tier === 'CRITICAL' ? '#b91c1c' : '#b45309'}; }
              .footer { background: #f8fafc; padding: 24px 40px; border-top: 1px solid #e2e8f0; text-align: center; font-size: 12px; color: #94a3b8; }
            </style>
          </head>
          <body>
            <div class="wrapper">
              <div class="header">
                <h2>New Customer Grievance</h2>
                <p>A customer has submitted a query regarding their risk tier alert.</p>
              </div>
              <div class="body">
                <p>A grievance has been submitted by a customer. Please review the details below and follow up as needed.</p>

                <div class="info-grid">
                  <div class="info-row">
                    <span class="info-label">Customer Name</span>
                    <span class="info-value">${customer_name}</span>
                  </div>
                  <div class="info-row">
                    <span class="info-label">Customer ID</span>
                    <span class="info-value">${customer_id}</span>
                  </div>
                  <div class="info-row">
                    <span class="info-label">Risk Tier</span>
                    <span class="info-value"><span class="tier-badge">${risk_tier}</span></span>
                  </div>
                  <div class="info-row">
                    <span class="info-label">Grievance ID</span>
                    <span class="info-value">${saved.grievance_id}</span>
                  </div>
                  <div class="info-row">
                    <span class="info-label">Submitted At</span>
                    <span class="info-value">${new Date().toLocaleString('en-IN', {
                      day: '2-digit', month: 'short', year: 'numeric',
                      hour: '2-digit', minute: '2-digit'
                    })}</span>
                  </div>
                </div>

                <p><strong>Customer Message:</strong></p>
                <div class="message-box">
                  <p>${message.trim()}</p>
                </div>

                <p style="font-size:13px; color:#64748b;">
                  Please log into the Sentinel dashboard to view and manage this grievance.
                </p>
              </div>
              <div class="footer">
                &copy; ${new Date().getFullYear()} Sentinel AI Security Operations. All rights reserved.
              </div>
            </div>
          </body>
        </html>
      `,
    };

    const info = await transporter.sendMail(mailOptions);
    const previewUrl = nodemailer.getTestMessageUrl(info);
    if (previewUrl) {
      console.log(`\n📬 Grievance Email Preview: ${previewUrl}\n`);
    }

    return NextResponse.json({
      success: true,
      grievance_id: saved.grievance_id,
      message: 'Grievance submitted successfully.',
    });

  } catch (err: any) {
    console.error('Failed to submit grievance:', err);
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}