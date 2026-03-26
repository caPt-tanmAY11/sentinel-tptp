import { NextResponse } from 'next/server';
import { sentinelApi } from '@/lib/api';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const id = searchParams.get('id');

  if (!id) {
    return new NextResponse('Missing intervention id', { status: 400 });
  }

  try {
    await sentinelApi.acknowledgeIntervention(id);

    return new NextResponse(`
      <!DOCTYPE html>
      <html lang="en">
        <head>
          <meta charset="UTF-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1.0" />
          <title>Sentinel AI - Alert Acknowledged</title>
          <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
            body { font-family: 'Inter', sans-serif; background-color: #f1f5f9; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; color: #0f172a; }
            .container { background: white; padding: 48px; border-radius: 16px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05); text-align: center; max-width: 480px; width: 90%; border-top: 6px solid #2563eb; }
            .logo { font-size: 24px; font-weight: 700; color: #1e293b; margin-bottom: 32px; letter-spacing: -0.5px; display: flex; align-items: center; justify-content: center; gap: 8px; }
            .logo-icon { width: 32px; height: 32px; background: #2563eb; border-radius: 8px; display: inline-block; position: relative; }
            .logo-icon::after { content: ''; position: absolute; inset: 6px; border: 2px solid white; border-radius: 4px; }
            h1 { color: #16a34a; font-size: 28px; margin: 0 0 16px 0; font-weight: 700; letter-spacing: -0.5px; }
            p { color: #475569; line-height: 1.6; font-size: 16px; margin-bottom: 24px; }
            .icon-wrapper { width: 80px; height: 80px; background: #dcfce7; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 24px auto; }
            .icon { font-size: 40px; fill: #16a34a; display: block; }
            .footer { margin-top: 32px; font-size: 13px; color: #94a3b8; border-top: 1px solid #e2e8f0; padding-top: 24px; }
          </style>
        </head>
        <body>
          <div class="container">
            <div class="logo">
              <div class="logo-icon"></div>
              Sentinel AI
            </div>
            <div class="icon-wrapper">
              <svg class="icon" viewBox="0 0 24 24" width="40" height="40">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
              </svg>
            </div>
            <h1>Alert Acknowledged</h1>
            <p>Thank you. Your risk tier alert has been successfully acknowledged. The update has been securely recorded in the Sentinel AI compliance system.</p>
            <p style="font-size: 14px; background: #f8fafc; padding: 16px; border-radius: 8px; border: 1px solid #e2e8f0;">
              You may now safely close this window and return to your inbox.
            </p>
            <div class="footer">
              &copy; ${new Date().getFullYear()} Sentinel AI Security Operations. All rights reserved.
            </div>
          </div>
        </body>
      </html>
    `, {
      headers: { 'Content-Type': 'text/html' }
    });

  } catch (err: any) {
    console.error('Failed to acknowledge intervention', err);
    return new NextResponse('Failed to acknowledge intervention', { status: 500 });
  }
}
