import { NextRequest, NextResponse } from 'next/server';
import { PDFDocument, rgb, StandardFonts } from 'pdf-lib';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const {
      report_text,
      generated_at,
      model,
      total_customers,
      critical_count,
      high_count,
      moderate_count,
      watch_count,
      stable_count,
      avg_pulse_score,
      scored_customers,
      high_severity_24h,
      total_interventions,
      system_pulse,
    } = body;

    // Validate required fields
    if (!report_text) {
      return NextResponse.json({ error: 'Missing report_text' }, { status: 400 });
    }

    // Generate PDF Bytes using pdf-lib
    const pdfBytes = await generatePdfBytes({
      report_text,
      generated_at,
      model,
      total_customers,
      critical_count,
      high_count,
      moderate_count,
      watch_count,
      stable_count,
      avg_pulse_score,
      scored_customers,
      high_severity_24h,
      total_interventions,
      system_pulse,
    });

    // Return as PDF file
    return new NextResponse(pdfBytes as any, {
      status: 200,
      headers: {
        'Content-Type': 'application/pdf',
        'Content-Disposition': `attachment; filename="Barclays_Sentinel_AI_Audit_${String(generated_at).slice(0, 10).replace(/-/g, '')}.pdf"`,
      },
    });
  } catch (error: any) {
    console.error('PDF generation error:', error);
    return NextResponse.json(
      { error: error.message || 'PDF generation failed' },
      { status: 500 }
    );
  }
}

async function generatePdfBytes(data: any): Promise<Uint8Array> {
  const pdfDoc = await PDFDocument.create();
  const helveticaFont = await pdfDoc.embedFont(StandardFonts.Helvetica);
  const helveticaBold = await pdfDoc.embedFont(StandardFonts.HelveticaBold);
  
  let page = pdfDoc.addPage([595.28, 841.89]); // A4 Size
  const { width, height } = page.getSize();
  let y = height - 50;

  const margin = 50;
  const barclaysBlue = rgb(0.0, 0.678, 0.937); // Light blue
  const darkBlue = rgb(0.0, 0.22, 0.44); // Darker text blue
  const textDark = rgb(0.2, 0.2, 0.2);

  const drawText = (text: string, font: any, size: number, color: any, xOffset: number, yOffset: number) => {
    page.drawText(text, { x: xOffset, y: yOffset, font, size, color });
  };

  // --- HEADER ---
  drawText('BARCLAYS', helveticaBold, 24, barclaysBlue, margin, y);
  y -= 30;

  drawText('Sentinel AI V2 - Regulatory Compliance Audit Report', helveticaBold, 18, darkBlue, margin, y);
  y -= 20;

  const genDate = new Date(data.generated_at).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
  
  drawText(`Date: ${genDate}`, helveticaFont, 10, textDark, margin, y);
  drawText(`Model: ${data.model}`, helveticaFont, 10, textDark, width - margin - 200, y);
  y -= 15;

  // Separator
  page.drawLine({
    start: { x: margin, y },
    end: { x: width - margin, y },
    thickness: 1,
    color: barclaysBlue,
  });
  y -= 25;

  // --- PORTFOLIO METRICS ---
  page.drawRectangle({
    x: margin,
    y: y - 85,
    width: width - 2 * margin,
    height: 100,
    color: rgb(0.96, 0.98, 1.0),
    borderColor: barclaysBlue,
    borderWidth: 1,
  });

  y -= 15;
  drawText('PORTFOLIO METRICS', helveticaBold, 12, darkBlue, margin + 15, y);
  y -= 20;

  const drawMetric = (label: string, value: string, xPos: number, yPos: number) => {
    drawText(`${label}:`, helveticaFont, 10, textDark, xPos, yPos);
    drawText(value, helveticaBold, 10, darkBlue, xPos + 110, yPos);
  };

  drawMetric('Total Customers', String(data.total_customers), margin + 15, y);
  drawMetric('Scored Customers', String(data.scored_customers), margin + 250, y);
  y -= 20;

  drawMetric('System Pulse', `${data.system_pulse}%`, margin + 15, y);
  drawMetric('Avg Pulse Score', `${(data.avg_pulse_score * 100).toFixed(1)}%`, margin + 250, y);
  y -= 20;

  drawMetric('High Severity (24h)', String(data.high_severity_24h), margin + 15, y);
  drawMetric('Total Interventions', String(data.total_interventions), margin + 250, y);
  y -= 45; // Move past the box

  // --- RISK DISTRIBUTION ---
  drawText('RISK DISTRIBUTION', helveticaBold, 12, darkBlue, margin, y);
  y -= 10;
  
  page.drawLine({
    start: { x: margin, y },
    end: { x: margin + 150, y },
    thickness: 1,
    color: barclaysBlue,
  });
  y -= 20;

  drawText(`Critical: ${data.critical_count}`, helveticaBold, 10, rgb(0.8, 0, 0), margin, y);
  drawText(`High: ${data.high_count}`, helveticaBold, 10, rgb(0.8, 0.4, 0), margin + 70, y);
  drawText(`Moderate: ${data.moderate_count}`, helveticaFont, 10, rgb(0.6, 0.6, 0), margin + 140, y);
  drawText(`Watch: ${data.watch_count}`, helveticaFont, 10, textDark, margin + 220, y);
  drawText(`Stable: ${data.stable_count}`, helveticaFont, 10, rgb(0, 0.5, 0), margin + 290, y);
  y -= 35;

  // --- AI-GENERATED REPORT ---
  drawText('AI-GENERATED AUDIT SUMMARY', helveticaBold, 12, darkBlue, margin, y);
  y -= 10;
  page.drawLine({
    start: { x: margin, y },
    end: { x: width - margin, y },
    thickness: 1,
    color: barclaysBlue,
  });
  y -= 20;

  const cleanReportText = data.report_text
    .replace(/\r/g, '')
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201C\u201D]/g, '"')
    .replace(/[\u2013\u2014]/g, '-')
    .replace(/[\u2026]/g, '...')
    .replace(/[^\x00-\x7F]/g, "");

  const paragraphs = cleanReportText.split('\n');
  const textFontSize = 10;
  const lineSpacing = 14;
  const maxWidth = width - 2 * margin;

  const checkPageBreak = (spaceNeeded: number) => {
    if (y < margin + spaceNeeded) {
      drawFooter(page, width, margin, helveticaFont);
      page = pdfDoc.addPage([595.28, 841.89]);
      y = height - margin;
    }
  };

  for (let paragraph of paragraphs) {
    paragraph = paragraph.trim();
    if (paragraph === '') {
      y -= lineSpacing;
      continue;
    }

    const isHeading = paragraph.includes('SECTION') || paragraph.startsWith('**');
    const fontToUse = isHeading ? helveticaBold : helveticaFont;
    const cleanParagraph = paragraph.replace(/\*\*/g, '');

    const words = cleanParagraph.split(' ');
    let currentLine = '';

    for (const word of words) {
      const lineWidth = fontToUse.widthOfTextAtSize(currentLine + word + ' ', textFontSize);
      
      if (lineWidth > maxWidth) {
        checkPageBreak(lineSpacing);
        drawText(currentLine.trim(), fontToUse, textFontSize, textDark, margin, y);
        y -= lineSpacing;
        currentLine = word + ' ';
      } else {
        currentLine += word + ' ';
      }
    }
    
    if (currentLine.trim() !== '') {
      checkPageBreak(lineSpacing);
      drawText(currentLine.trim(), fontToUse, textFontSize, textDark, margin, y);
      y -= lineSpacing;
    }
    
    // Extra spacing after paragraphs
    y -= 5;
  }

  drawFooter(page, width, margin, helveticaFont);
  return await pdfDoc.save();
}

function drawFooter(page: any, width: number, margin: number, font: any) {
  const y = 30;
  page.drawLine({
    start: { x: margin, y: y + 10 },
    end: { x: width - margin, y: y + 10 },
    thickness: 0.5,
    color: rgb(0.7, 0.7, 0.7),
  });
  page.drawText('Sentinel AI System - Internal Use Only - Confidential', {
    x: margin,
    y: y,
    size: 8,
    font: font,
    color: rgb(0.5, 0.5, 0.5),
  });
  page.drawText(`Generated on: ${new Date().toLocaleString()}`, {
    x: width - margin - 180,
    y: y,
    size: 8,
    font: font,
    color: rgb(0.5, 0.5, 0.5),
  });
}
