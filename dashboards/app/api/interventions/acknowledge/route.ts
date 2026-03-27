// dashboards/app/api/interventions/acknowledge/route.ts

import { NextResponse } from 'next/server';
import { sentinelApi } from '@/lib/api';

export const dynamic = 'force-dynamic';

// ✅ NEW: POST handler — called programmatically from the report page
export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { interventionId } = body;

    if (!interventionId) {
      return NextResponse.json(
        { error: 'Missing interventionId in request body' },
        { status: 400 }
      );
    }

    await sentinelApi.acknowledgeIntervention(interventionId);

    return NextResponse.json({
      success: true,
      message: 'Intervention acknowledged successfully.',
      interventionId,
    });

  } catch (err: any) {
    console.error('Failed to acknowledge intervention:', err);
    return NextResponse.json(
      { error: err.message || 'Failed to acknowledge intervention' },
      { status: 500 }
    );
  }
}

// ✅ KEEP: GET handler as a fallback (old email links won't break)
// Redirects old-style links to the report page instead of instant-acknowledging
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const id = searchParams.get('id');

  if (!id) {
    return new Response('Missing intervention id', { status: 400 });
  }

  // Redirect old links gracefully — customer sees the report first
  const baseUrl = process.env.NEXT_PUBLIC_BASE_URL || 'http://localhost:3000';
  return Response.redirect(`${baseUrl}/report/legacy?interventionId=${id}`, 302);
}