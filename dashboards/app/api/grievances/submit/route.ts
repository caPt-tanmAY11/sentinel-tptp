import { NextResponse } from 'next/server';
import nodemailer from 'nodemailer';

const SENDER_EMAIL = process.env.SENDER_EMAIL || 'your_new_gmail@gmail.com';
const BANK_EMAIL   = SENDER_EMAIL;
const PASS         = process.env.EMAIL_PASS || '';

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
      host: 'smtp.ethereal.email', port: 587, secure: false,
      auth: { user: testAccount.user, pass: testAccount.pass },
    });
    console.log('📧 Using Ethereal test account:', testAccount.user);
  }
  return cachedTransporter;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function formatINR(amount: number) {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency', currency: 'INR', maximumFractionDigits: 0,
  }).format(amount);
}

function formatCategory(cat: string | null) {
  if (!cat) return 'Unknown';
  return cat.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase());
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

// Build the per-transaction rows for the email
function buildTransactionRows(disputes: any[]): string {
  if (!disputes || disputes.length === 0) return '';

  const rows = disputes.map((d: any) => {
    const agreed     = d.agreed === true;
    const statusColor = agreed ? '#15803d'  : '#b91c1c';
    const statusBg    = agreed ? '#dcfce7'  : '#fee2e2';
    const statusLabel = agreed ? '✓ Accurate' : '✗ Disputed';

    const disputeRow = !agreed && d.dispute_reason
      ? `<tr>
           <td colspan="4" style="padding:8px 14px 12px 14px; font-size:13px; color:#7c2d12; background:#fff8f8; border-top:1px dashed #fca5a5;">
             <strong>Dispute reason:</strong> ${d.dispute_reason}
           </td>
         </tr>`
      : '';

    return `
      <tr style="border-bottom:1px solid #e2e8f0;">
        <td style="padding:12px 14px; font-size:13px; color:#0f172a; font-weight:600;">${formatINR(d.amount)}</td>
        <td style="padding:12px 14px; font-size:13px; color:#475569;">${formatCategory(d.inferred_category)}</td>
        <td style="padding:12px 14px; font-size:12px; color:#64748b;">${formatDate(d.event_ts)}</td>
        <td style="padding:12px 14px;">
          <span style="display:inline-block; padding:3px 9px; border-radius:5px; font-size:11px; font-weight:700;
                       background:${statusBg}; color:${statusColor};">
            ${statusLabel}
          </span>
        </td>
      </tr>
      ${disputeRow}
    `;
  }).join('');

  return `
    <p style="margin:20px 0 8px 0; font-size:14px; font-weight:700; color:#1e293b;">
      Transaction-Level Disputes
    </p>
    <table width="100%" cellpadding="0" cellspacing="0"
           style="border:1px solid #e2e8f0; border-radius:8px; overflow:hidden; border-collapse:collapse; font-family:Helvetica,Arial,sans-serif;">
      <thead>
        <tr style="background:#f1f5f9;">
          <th style="padding:10px 14px; font-size:12px; color:#64748b; text-align:left; font-weight:600;">Amount</th>
          <th style="padding:10px 14px; font-size:12px; color:#64748b; text-align:left; font-weight:600;">Category</th>
          <th style="padding:10px 14px; font-size:12px; color:#64748b; text-align:left; font-weight:600;">Date</th>
          <th style="padding:10px 14px; font-size:12px; color:#64748b; text-align:left; font-weight:600;">Status</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

// ── Route handler ──────────────────────────────────────────────────────────────

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const {
      intervention_id,
      message,
      transaction_disputes,
      additional_notes,
    } = body;

    if (!intervention_id) {
      return NextResponse.json({ error: 'Missing intervention_id' }, { status: 400 });
    }

    // ── 1. Fetch intervention + customer details ──────────────────────────────
    const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';
    const detailsRes = await fetch(`${apiBase}/interventions/${intervention_id}/details`);
    if (!detailsRes.ok) {
      return NextResponse.json({ error: 'Intervention not found or expired.' }, { status: 404 });
    }
    const details = await detailsRes.json();
    const { customer_name, customer_id, risk_tier } = details;

    // ── 2. Save grievance to DB via FastAPI ───────────────────────────────────
    const saveRes = await fetch(`${apiBase}/grievances`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        intervention_id,
        customer_id,
        customer_name,
        message:              message?.trim() || 'Transaction dispute submitted.',
        transaction_disputes: transaction_disputes ?? null,
        additional_notes:     additional_notes?.trim() || null,
      }),
    });

    if (!saveRes.ok) {
      const err = await saveRes.json();
      return NextResponse.json({ error: err.detail || 'Failed to save grievance.' }, { status: 500 });
    }

    const saved = await saveRes.json();

    // ── 3. Build summary stats for email ──────────────────────────────────────
    const disputes: any[] = transaction_disputes || [];
    const disputedTxns    = disputes.filter((d: any) => d.agreed === false);
    const agreedTxns      = disputes.filter((d: any) => d.agreed === true);

    const tierColor = risk_tier === 'CRITICAL' ? '#b91c1c' : '#b45309';
    const tierBg    = risk_tier === 'CRITICAL' ? '#fee2e2' : '#fef3c7';

    // ── 4. Send officer notification email ────────────────────────────────────
    const transporter  = await getTransporter();
    const txnTableHtml = buildTransactionRows(disputes);

    const additionalNotesHtml = additional_notes?.trim()
      ? `<p style="margin:20px 0 8px 0; font-size:14px; font-weight:700; color:#1e293b;">
           Additional Notes from Customer
         </p>
         <div style="background:#fffbeb; border-left:4px solid #f59e0b; padding:16px 18px;
                     border-radius:0 8px 8px 0; font-size:14px; color:#0f172a; line-height:1.7;">
           ${additional_notes.trim()}
         </div>`
      : '';

    const mailOptions = {
      from: `"Sentinel AI Security" <${SENDER_EMAIL}>`,
      to:   BANK_EMAIL,
      subject: `[GRIEVANCE] ${customer_name} — ${risk_tier} Tier · ${disputedTxns.length} dispute${disputedTxns.length !== 1 ? 's' : ''}`,
      html: `
        <!DOCTYPE html>
        <html>
          <head><meta charset="utf-8"></head>
          <body style="font-family:Helvetica,Arial,sans-serif; background:#f8fafc; margin:0; padding:0;">
            <div style="max-width:640px; margin:40px auto; background:#fff; border-radius:12px;
                        overflow:hidden; border:1px solid #e2e8f0;">

              <!-- Header -->
              <div style="background:#2563eb; padding:28px 40px; color:#fff;">
                <h2 style="margin:0; font-size:22px; font-weight:700;">New Customer Grievance</h2>
                <p style="margin:6px 0 0 0; font-size:14px; opacity:0.85;">
                  A customer has reviewed their flagged transactions and submitted a dispute.
                </p>
              </div>

              <!-- Body -->
              <div style="padding:32px 40px; color:#334155;">

                <!-- Customer info grid -->
                <div style="background:#f1f5f9; border-radius:8px; padding:20px; margin-bottom:20px;">
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td style="font-size:13px; color:#64748b; font-weight:600; padding-bottom:10px;">Customer Name</td>
                      <td style="font-size:13px; color:#0f172a; font-weight:500; padding-bottom:10px; text-align:right;">${customer_name}</td>
                    </tr>
                    <tr>
                      <td style="font-size:13px; color:#64748b; font-weight:600; padding-bottom:10px;">Customer ID</td>
                      <td style="font-size:13px; color:#0f172a; font-weight:500; padding-bottom:10px; text-align:right;">${customer_id}</td>
                    </tr>
                    <tr>
                      <td style="font-size:13px; color:#64748b; font-weight:600; padding-bottom:10px;">Risk Tier</td>
                      <td style="font-size:13px; text-align:right; padding-bottom:10px;">
                        <span style="display:inline-block; padding:3px 10px; border-radius:5px; font-size:12px;
                                     font-weight:700; background:${tierBg}; color:${tierColor};">
                          ${risk_tier}
                        </span>
                      </td>
                    </tr>
                    <tr>
                      <td style="font-size:13px; color:#64748b; font-weight:600; padding-bottom:10px;">Grievance ID</td>
                      <td style="font-size:13px; color:#0f172a; font-weight:500; padding-bottom:10px; text-align:right;">${saved.grievance_id}</td>
                    </tr>
                    <tr>
                      <td style="font-size:13px; color:#64748b; font-weight:600; padding-bottom:10px;">Transactions Reviewed</td>
                      <td style="font-size:13px; color:#0f172a; font-weight:500; padding-bottom:10px; text-align:right;">${disputes.length}</td>
                    </tr>
                    <tr>
                      <td style="font-size:13px; color:#64748b; font-weight:600; padding-bottom:10px;">Disputed</td>
                      <td style="font-size:13px; font-weight:700; text-align:right; padding-bottom:10px;
                                 color:${disputedTxns.length > 0 ? '#b91c1c' : '#15803d'};">
                        ${disputedTxns.length} of ${disputes.length}
                      </td>
                    </tr>
                    <tr>
                      <td style="font-size:13px; color:#64748b; font-weight:600;">Submitted At</td>
                      <td style="font-size:13px; color:#0f172a; font-weight:500; text-align:right;">
                        ${new Date().toLocaleString('en-IN', {
                          day: '2-digit', month: 'short', year: 'numeric',
                          hour: '2-digit', minute: '2-digit',
                        })}
                      </td>
                    </tr>
                  </table>
                </div>

                ${txnTableHtml}
                ${additionalNotesHtml}

                <p style="font-size:13px; color:#64748b; margin-top:24px;">
                  Please log into the Sentinel dashboard to view and manage this grievance.
                </p>
              </div>

              <!-- Footer -->
              <div style="background:#f8fafc; padding:20px 40px; border-top:1px solid #e2e8f0;
                          text-align:center; font-size:12px; color:#94a3b8;">
                &copy; ${new Date().getFullYear()} Sentinel AI Security Operations. All rights reserved.
              </div>
            </div>
          </body>
        </html>
      `,
    };

    const info = await transporter.sendMail(mailOptions);
    const previewUrl = nodemailer.getTestMessageUrl(info);
    if (previewUrl) console.log(`\n📬 Grievance Email Preview: ${previewUrl}\n`);

    return NextResponse.json({
      success:      true,
      grievance_id: saved.grievance_id,
      message:      'Grievance submitted successfully.',
    });

  } catch (err: any) {
    console.error('Failed to submit grievance:', err);
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}