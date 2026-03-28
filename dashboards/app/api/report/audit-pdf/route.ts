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
  let yOffset = height - 120;

  const margin = 40;
  const contentWidth = width - 2 * margin;
  const navy = rgb(0.0, 0.2, 0.45);
  const lightGrey = rgb(0.95, 0.95, 0.97);
  const borderGrey = rgb(0.7, 0.75, 0.85);

  const setHeader = (pageObj: any) => {
    // Navy top bar
    pageObj.drawRectangle({
      x: 0, y: height - 50, width: width, height: 50, color: navy
    });
    // Bar text
    pageObj.drawText('Barclays Bank India Private Limited', {
      x: margin, y: height - 30, size: 12, font: helveticaBold, color: rgb(1,1,1)
    });
    pageObj.drawText('INTERNAL COMPLIANCE RECORD — CONFIDENTIAL', {
      x: width - margin - 220, y: height - 30, size: 8, font: helveticaFont, color: rgb(1,1,1)
    });
    // Sub-header
    pageObj.drawText('Sentinel V2 AI Compliance System | AI-Assisted | Human-Reviewed | RBI/IBA Compliant', {
      x: margin, y: height - 70, size: 8, font: helveticaFont, color: navy
    });
    // Line separator
    pageObj.drawLine({
      start: { x: margin, y: height - 85 },
      end: { x: width - margin, y: height - 85 },
      thickness: 1, color: navy
    });
  };

  const drawKVTable = (pageObj: any, startY: number, title: string, rows: [string, string][]) => {
    let currentY = startY;
    
    // Section Title
    if (title) {
      pageObj.drawRectangle({
        x: margin, y: currentY - 14, width: contentWidth, height: 16, color: navy
      });
      pageObj.drawText(title, {
        x: margin + 5, y: currentY - 10, size: 9, font: helveticaBold, color: rgb(1,1,1)
      });
      currentY -= 14;
    }
    
    for (let i = 0; i < rows.length; i++) {
      const isAlt = i % 2 !== 0;
      const rowHeight = 18;
      
      if (isAlt) {
        pageObj.drawRectangle({
          x: margin, y: currentY - rowHeight, width: contentWidth, height: rowHeight, color: lightGrey
        });
      }
      
      pageObj.drawRectangle({
        x: margin, y: currentY - rowHeight, width: contentWidth, height: rowHeight, 
        borderColor: borderGrey, borderWidth: 0.5, color: undefined
      });
      pageObj.drawLine({
        start: { x: margin + 140, y: currentY },
        end: { x: margin + 140, y: currentY - rowHeight },
        thickness: 0.5, color: borderGrey
      });

      pageObj.drawText(rows[i][0], {
        x: margin + 5, y: currentY - 12, size: 8, font: helveticaBold, color: navy
      });
      pageObj.drawText(rows[i][1], {
        x: margin + 145, y: currentY - 12, size: 8, font: helveticaFont, color: rgb(0.1, 0.1, 0.1)
      });
      
      currentY -= rowHeight;
    }
    return currentY;
  };

  setHeader(page);

  // Big Title Box
  const boxHeight = 70;
  yOffset -= boxHeight;
  page.drawRectangle({
    x: margin + 30, y: yOffset, width: contentWidth - 60, height: boxHeight, color: navy
  });
  
  const title1 = 'BARCLAYS SENTINEL V2';
  const width1 = helveticaBold.widthOfTextAtSize(title1, 16);
  page.drawText(title1, {
    x: margin + 30 + (contentWidth - 60 - width1) / 2, y: yOffset + 45, size: 16, font: helveticaBold, color: rgb(1,1,1)
  });
  
  const title2 = 'Regulatory AI Compliance & Transparency Record';
  const width2 = helveticaFont.widthOfTextAtSize(title2, 10);
  page.drawText(title2, {
    x: margin + 30 + (contentWidth - 60 - width2) / 2, y: yOffset + 25, size: 10, font: helveticaFont, color: rgb(1,1,1)
  });
  
  const title3 = 'CONFIDENTIAL — FOR BANK & REGULATORY USE ONLY';
  const width3 = helveticaFont.widthOfTextAtSize(title3, 9);
  page.drawText(title3, {
    x: margin + 30 + (contentWidth - 60 - width3) / 2, y: yOffset + 8, size: 9, font: helveticaFont, color: rgb(1,1,1)
  });
  yOffset -= 25;

  const introTxt = "This document is a complete AI compliance and transparency record maintained by Barclays Bank India pursuant to RBI Digital Lending Guidelines and the RBI Early Warning Signal Framework. It documents overall portfolio health, model methodology, and intervention metrics. It is intended for internal compliance teams, external auditors, and regulatory bodies only.";
  const wrappedIntro = wrapText(introTxt, helveticaFont, 8, contentWidth);
  for (const line of wrappedIntro) {
    page.drawText(line, { x: margin, y: yOffset, size: 8, font: helveticaFont, color: rgb(0.1, 0.1, 0.1) });
    yOffset -= 12;
  }
  yOffset -= 15;

  const getReportId = () => `SV2-${new Date().getTime().toString(16).toUpperCase().slice(-8)}-${String(data.total_customers).padStart(4,'0')}`;

  yOffset = drawKVTable(page, yOffset, "SECTION 1: REPORT IDENTIFICATION", [
    ['Report ID', getReportId()],
    ['Reference', `BCI/INT/SV2/PORTFOLIO/${new Date().getFullYear()}`],
    ['Generated', new Date(data.generated_at).toLocaleString('en-US')],
    ['Generated By', 'Sentinel V2 — Portfolio Audit Service'],
    ['Classification', 'CONFIDENTIAL — INTERNAL USE ONLY'],
    ['Model Configuration', data.model || 'os-models-v2'],
  ]);
  yOffset -= 20;

  yOffset = drawKVTable(page, yOffset, "SECTION 2: PORTFOLIO METRICS", [
    ['Total Customers Monitored', String(data.total_customers)],
    ['Scored Customers', String(data.scored_customers)],
    ['System Pulse Index', `${data.system_pulse}% / 100%`],
    ['Average Pulse Score', `${(data.avg_pulse_score * 100).toFixed(1)}`],
    ['High Severity Events (24h)', String(data.high_severity_24h)],
    ['Total Interventions Triggered', String(data.total_interventions)],
  ]);
  yOffset -= 20;

  yOffset = drawKVTable(page, yOffset, "SECTION 3: RISK DISTRIBUTION (SEGMENTATION)", [
    ['Critical Tier (Immediate Action)', String(data.critical_count)],
    ['High Tier (72hr Window)', String(data.high_count)],
    ['Moderate Tier', String(data.moderate_count)],
    ['Watch Tier', String(data.watch_count)],
    ['Stable Tier', String(data.stable_count)],
  ]);
  yOffset -= 20;

  // -- MAIN REPORT PARAGRAPHS --
  yOffset = drawKVTable(page, yOffset, "SECTION 4: AI-GENERATED AUDIT SUMMARY", []);
  yOffset -= 5;

  const cleanReportText = data.report_text
    .replace(/\r/g, '')
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201C\u201D]/g, '"')
    .replace(/[\u2013\u2014]/g, '-')
    .replace(/[\u2026]/g, '...')
    .replace(/[^\x00-\x7F]/g, "");

  const paragraphs = cleanReportText.split('\n');
  const textFontSize = 8;
  const lineSpacing = 12;

  const checkPageBreak = (needed: number) => {
    if (yOffset - needed < 50) {
      drawFooter(page, width, margin, helveticaFont);
      page = pdfDoc.addPage([595.28, 841.89]);
      setHeader(page);
      yOffset = height - 120;
    }
  };

  for (let paragraph of paragraphs) {
    paragraph = paragraph.trim();
    if (paragraph === '') {
      yOffset -= lineSpacing;
      continue;
    }

    const isHeading = paragraph.includes('SECTION') || paragraph.startsWith('**');
    const fontToUse = isHeading ? helveticaBold : helveticaFont;
    const cleanParagraph = paragraph.replace(/\*\*/g, '');

    const lines = wrapText(cleanParagraph, fontToUse, textFontSize, contentWidth);
    for (const line of lines) {
      checkPageBreak(lineSpacing);
      page.drawText(line, { x: margin, y: yOffset, size: textFontSize, font: fontToUse, color: rgb(0.1, 0.1, 0.1) });
      yOffset -= lineSpacing;
    }
    yOffset -= 4; // Paragraph spacing
  }

  drawFooter(page, width, margin, helveticaFont);
  return await pdfDoc.save();
}

function wrapText(text: string, font: any, fontSize: number, maxWidth: number) {
  const words = text.split(' ');
  const lines = [];
  let currentLine = '';

  for (const word of words) {
    const width = font.widthOfTextAtSize(currentLine + word + ' ', fontSize);
    if (width > maxWidth) {
      lines.push(currentLine.trim());
      currentLine = word + ' ';
    } else {
      currentLine += word + ' ';
    }
  }
  if (currentLine.trim()) lines.push(currentLine.trim());
  return lines;
}

function drawFooter(page: any, width: number, margin: number, font: any) {
  const y = 30;
  const blue = rgb(0.0, 0.2, 0.45);
  page.drawLine({
    start: { x: margin, y: y + 10 },
    end: { x: width - margin, y: y + 10 },
    thickness: 1,
    color: blue,
  });
  page.drawText('Internal Compliance Record — Sentinel AI', {
    x: margin,
    y: y,
    size: 7,
    font: font,
    color: rgb(0.4, 0.4, 0.4),
  });
  page.drawText(`Page Generated Timestamp: ${new Date().toISOString()}`, {
    x: width - margin - 180,
    y: y,
    size: 7,
    font: font,
    color: rgb(0.4, 0.4, 0.4),
  });
}
