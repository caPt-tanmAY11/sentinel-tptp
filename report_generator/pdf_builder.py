"""
report_generator/pdf_builder.py
─────────────────────────────────────────────────────────────────────────────
SENTINEL V2 — Dual PDF Builder

Builds two completely different PDFs from report dicts:

  BankReportPDFBuilder  — Report A (Internal Compliance Record)
    Design: Formal, dense, technical. Navy/grey palette.
    Pages : Cover → Customer Summary → Transaction Log →
            AI Audit → Model Stats → Compliance Narrative →
            Legal Checklist → Human Oversight → Section 65B Cert

  CustomerNoticePDFBuilder — Report B (Customer Wellness Notice)
    Design: Warm, open, readable. Teal/blue palette.
    Pages : Cover letter → Transaction timeline (date-wise) →
            Pulse explanation → Intervention solution plan →
            Your rights → Contact

Usage:
    from report_generator.pdf_builder import BankReportPDFBuilder, CustomerNoticePDFBuilder

    bank_pdf  = BankReportPDFBuilder().build(bank_report_dict)
    cust_pdf  = CustomerNoticePDFBuilder().build(customer_notice_dict)
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import io
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, HRFlowable, PageBreak,
    PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

# ── Shared Geometry ────────────────────────────────────────────────────────
PAGE_W, PAGE_H  = A4
MARGIN_L        = 22 * mm
MARGIN_R        = 22 * mm
MARGIN_T        = 36 * mm
MARGIN_B        = 26 * mm

# ── Colour Palettes ────────────────────────────────────────────────────────
# Bank report — formal, authoritative
B_DARK    = colors.HexColor("#002C77")  # Navy
B_BLUE    = colors.HexColor("#00AEEF")  # Barclays blue
B_GREY    = colors.HexColor("#53565A")  # Body grey
B_LIGHT   = colors.HexColor("#E8F4FB")  # Light blue
B_RED     = colors.HexColor("#C0001A")  # Alert red (checklist fails)
B_GREEN   = colors.HexColor("#1A6B1A")  # Checklist pass
B_BLACK   = colors.HexColor("#1A1A1A")
WHITE     = colors.white

# Customer notice — warm, approachable
C_TEAL    = colors.HexColor("#00847F")  # Primary warm teal
C_NAVY    = colors.HexColor("#002C77")  # Shared navy
C_BLUE    = colors.HexColor("#00AEEF")  # Barclays blue
C_LIGHT   = colors.HexColor("#E8F4FB")  # Light bg
C_SOFT    = colors.HexColor("#F0FAF9")  # Very light teal
C_AMBER   = colors.HexColor("#F5A623")  # Warm accent
C_GREY    = colors.HexColor("#53565A")
C_BLACK   = colors.HexColor("#1A1A1A")

BANK_NAME_SHORT = "Barclays Bank India Private Limited"
BANK_ADDRESS    = "One Indiabulls Centre, Tower 1, Level 10, 841 Senapati Bapat Marg, Mumbai – 400 013"
BANK_REG        = "CIN: U65100MH2005PTC157999  |  RBI Licence: OSMOS/MUM/2005/0012"
BANK_SUPPORT    = "customersupport.india@barclays.com  |  1800-102-3456"
MODEL_ID        = "llama-3.3-70b-versatile"


# ══════════════════════════════════════════════════════════════════════════
#  Shared helpers
# ══════════════════════════════════════════════════════════════════════════

def _frame():
    return Frame(MARGIN_L, MARGIN_B,
                 PAGE_W - MARGIN_L - MARGIN_R,
                 PAGE_H - MARGIN_T - MARGIN_B,
                 id="main")


def _page_template(page_id, header_fn, footer_fn):
    def _cb(canvas, doc):
        header_fn(canvas, doc)
        footer_fn(canvas, doc)
    return PageTemplate(id=page_id, frames=[_frame()], onPage=_cb)


def _para(text, style):
    return Paragraph(str(text).replace("\n", "<br/>"), style)


def _hr(color=B_BLUE, thickness=0.8):
    return HRFlowable(width="100%", thickness=thickness, color=color)


def _sp(h=3):
    return Spacer(1, h * mm)


def _boxed_table(content_rows, bg, border_color, col_widths=None):
    tbl = Table(content_rows, colWidths=col_widths or ["100%"])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), bg),
        ("BOX",           (0, 0), (-1, -1), 1, border_color),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return tbl


# ══════════════════════════════════════════════════════════════════════════
#  REPORT A — Bank Internal Compliance PDF
# ══════════════════════════════════════════════════════════════════════════

def _bank_styles() -> Dict:
    return {
        "title": ParagraphStyle("bt", fontName="Helvetica-Bold", fontSize=13,
                                textColor=WHITE, alignment=TA_CENTER, leading=18),
        "subtitle": ParagraphStyle("bst", fontName="Helvetica", fontSize=9,
                                   textColor=B_LIGHT, alignment=TA_CENTER, spaceAfter=4),
        "section_head": ParagraphStyle("bsh", fontName="Helvetica-Bold", fontSize=9.5,
                                       textColor=WHITE, backColor=B_DARK,
                                       leftIndent=4, spaceBefore=8, spaceAfter=4, leading=14),
        "field_label": ParagraphStyle("bfl", fontName="Helvetica-Bold", fontSize=8,
                                      textColor=B_DARK, spaceAfter=1),
        "field_value": ParagraphStyle("bfv", fontName="Helvetica", fontSize=8,
                                      textColor=B_BLACK, spaceAfter=5),
        "body": ParagraphStyle("bb", fontName="Helvetica", fontSize=8.5,
                               textColor=B_BLACK, alignment=TA_JUSTIFY,
                               spaceAfter=6, leading=13),
        "body_mono": ParagraphStyle("bbm", fontName="Courier", fontSize=7.5,
                                    textColor=B_BLACK, spaceAfter=4, leading=11, leftIndent=6),
        "check_pass": ParagraphStyle("bcp", fontName="Helvetica", fontSize=8,
                                     textColor=B_GREEN, spaceAfter=2),
        "check_fail": ParagraphStyle("bcf", fontName="Helvetica", fontSize=8,
                                     textColor=B_RED, spaceAfter=2),
        "ai_watermark": ParagraphStyle("baw", fontName="Helvetica-Oblique", fontSize=7.5,
                                       textColor=B_GREY, alignment=TA_CENTER, spaceAfter=3),
        "footer": ParagraphStyle("bft", fontName="Helvetica", fontSize=6.5,
                                 textColor=B_GREY, alignment=TA_CENTER),
    }


def _bank_header(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(B_DARK)
    canvas.rect(0, PAGE_H - 15 * mm, PAGE_W, 15 * mm, fill=1, stroke=0)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.setFillColor(WHITE)
    canvas.drawString(MARGIN_L, PAGE_H - 10 * mm, BANK_NAME_SHORT)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(B_LIGHT)
    canvas.drawRightString(PAGE_W - MARGIN_R, PAGE_H - 10 * mm,
                           "INTERNAL COMPLIANCE RECORD — CONFIDENTIAL")
    canvas.setStrokeColor(B_BLUE)
    canvas.setLineWidth(1.5)
    canvas.line(0, PAGE_H - 16 * mm, PAGE_W, PAGE_H - 16 * mm)
    canvas.setFont("Helvetica", 6.5)
    canvas.setFillColor(B_GREY)
    canvas.drawString(MARGIN_L, PAGE_H - 21 * mm,
                      "Sentinel V2 AI Compliance System  |  AI-Assisted  |  Human-Reviewed  |  RBI/IBA Compliant")
    canvas.restoreState()


def _bank_footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(B_BLUE)
    canvas.setLineWidth(0.6)
    canvas.line(MARGIN_L, MARGIN_B - 3 * mm, PAGE_W - MARGIN_R, MARGIN_B - 3 * mm)
    canvas.setFont("Helvetica", 6)
    canvas.setFillColor(B_GREY)
    canvas.drawString(MARGIN_L, MARGIN_B - 8 * mm, BANK_ADDRESS)
    canvas.drawString(MARGIN_L, MARGIN_B - 12 * mm, BANK_REG)
    canvas.setFont("Helvetica-Bold", 7)
    canvas.setFillColor(B_DARK)
    canvas.drawRightString(PAGE_W - MARGIN_R, MARGIN_B - 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


class BankReportPDFBuilder:
    """Builds the Bank Internal Compliance Report PDF (Report A)."""

    def __init__(self):
        self.s = _bank_styles()

    def build(self, report: Dict[str, Any]) -> bytes:
        buf = io.BytesIO()
        doc = BaseDocTemplate(
            buf, pagesize=A4,
            leftMargin=MARGIN_L, rightMargin=MARGIN_R,
            topMargin=MARGIN_T, bottomMargin=MARGIN_B,
            title="Barclays Sentinel V2 — Internal Compliance Report",
            author=BANK_NAME_SHORT,
            subject="Confidential AI Compliance Record",
        )
        doc.addPageTemplates([
            _page_template("bank", _bank_header, _bank_footer)
        ])
        doc.build(self._story(report))
        return buf.getvalue()

    def _story(self, report: Dict) -> List:
        s    = self.s
        secs = report.get("sections", {})
        raw  = report.get("raw_data", {})
        story = []

        # ── Cover ──────────────────────────────────────────────────────
        story += self._cover(report)
        story.append(PageBreak())

        # ── S1: Identification ─────────────────────────────────────────
        story += self._fields_section(secs.get("s1_identification", {}))

        # ── S2: Customer Summary ───────────────────────────────────────
        story += self._fields_section(secs.get("s2_customer_summary", {}))
        story.append(PageBreak())

        # ── S3: Transaction Log ────────────────────────────────────────
        story += self._transaction_log(secs.get("s3_transaction_log", {}))
        story.append(PageBreak())

        # ── S4: AI Audit (AI-generated) ────────────────────────────────
        story += self._ai_section(secs.get("s4_ai_audit", {}))

        # ── S5: Model Stats ────────────────────────────────────────────
        story += self._fields_section(secs.get("s5_model_stats", {}))
        story.append(PageBreak())

        # ── S6: Compliance Narrative (AI-generated) ────────────────────
        story += self._ai_section(secs.get("s6_compliance", {}))

        # ── S7: Legal Checklist ────────────────────────────────────────
        story += self._checklist_section(secs.get("s7_legal_checklist", {}))
        story.append(PageBreak())

        # ── S8: Human Oversight ────────────────────────────────────────
        story += self._oversight_section(secs.get("s8_human_oversight", {}))

        # ── S9: Section 65B Certificate ────────────────────────────────
        story += self._cert_section(secs.get("s9_certification", {}))

        return story

    def _cover(self, report):
        s = self.s
        cover_bg = Table(
            [[_para("BARCLAYS SENTINEL V2", s["title"]),],
             [_para("Internal AI Compliance & Transparency Record", s["subtitle"])],
             [_para("CONFIDENTIAL — FOR BANK & REGULATORY USE ONLY", s["subtitle"])]],
            colWidths=["100%"],
        )
        cover_bg.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), B_DARK),
            ("TOPPADDING",    (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ]))

        meta_rows = [
            ["Report ID",       report.get("report_id", "N/A")[:18] + "..."],
            ["Reference",       report.get("reference", "N/A")],
            ["Generated",       report.get("generated_at", "")[:10]],
            ["Generated By",    report.get("generated_by", "N/A")],
            ["Classification",  "CONFIDENTIAL — INTERNAL"],
        ]
        lbl = ParagraphStyle("ml", fontName="Helvetica-Bold", fontSize=8, textColor=B_DARK)
        val = ParagraphStyle("mv", fontName="Helvetica", fontSize=8, textColor=B_BLACK)
        meta_tbl = Table(
            [[_para(r[0], lbl), _para(r[1], val)] for r in meta_rows],
            colWidths=["35%", "65%"],
        )
        meta_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), B_LIGHT),
            ("BOX",           (0, 0), (-1, -1), 0.8, B_DARK),
            ("INNERGRID",     (0, 0), (-1, -1), 0.2, B_GREY),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ]))

        return [
            _sp(4), cover_bg, _sp(6), meta_tbl, _sp(4),
            _para(
                "This document is a complete AI compliance and transparency record "
                "maintained by Barclays Bank India pursuant to RBI Digital Lending "
                "Guidelines (RBI/2022-23/111) and the RBI Early Warning Signal Framework. "
                "It documents every AI decision, model methodology, transaction processed, "
                "and human oversight action. It is intended for internal compliance teams, "
                "external auditors, and regulatory bodies only.",
                s["body"]
            ),
            _sp(3), _hr(B_DARK, 1),
        ]

    def _fields_section(self, section: Dict) -> List:
        s = self.s
        if not section:
            return []
        elems = [
            _sp(3),
            _para(section.get("title", ""), s["section_head"]),
            _sp(2),
        ]
        fields = section.get("fields", {})
        lbl = ParagraphStyle("fl", fontName="Helvetica-Bold", fontSize=8, textColor=B_DARK)
        val = ParagraphStyle("fv", fontName="Helvetica", fontSize=8, textColor=B_BLACK)
        rows = [[_para(k, lbl), _para(v, val)] for k, v in fields.items()]
        if rows:
            tbl = Table(rows, colWidths=["38%", "62%"])
            tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), B_LIGHT),
                ("INNERGRID",     (0, 0), (-1, -1), 0.2, B_GREY),
                ("BOX",           (0, 0), (-1, -1), 0.6, B_DARK),
                ("TOPPADDING",    (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ]))
            elems.append(tbl)
        return elems

    def _ai_section(self, section: Dict) -> List:
        s = self.s
        if not section:
            return []
        content = section.get("content", "")
        elems = [
            _sp(3),
            _para(section.get("title", ""), s["section_head"]),
            _para(
                "[ AI-ASSISTED CONTENT — Generated by Sentinel V2 / Meta Llama 3.3 70B via Groq"
                " | Grounded in structured data | No invented facts | Human-reviewed ]",
                s["ai_watermark"],
            ),
            _sp(2),
        ]
        for para in content.split("\n\n"):
            para = para.strip()
            if para:
                elems.append(_para(para, s["body"]))
        return elems

    def _transaction_log(self, section: Dict) -> List:
        s = self.s
        if not section:
            return []
        txns = section.get("transactions", [])
        elems = [
            _sp(3),
            _para(section.get("title", ""), s["section_head"]),
            _sp(1),
            _para(section.get("description", ""), s["body"]),
            _sp(2),
        ]
        if not txns:
            elems.append(_para("No transactions recorded.", s["body"]))
            return elems

        lbl = ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=7.5, textColor=WHITE)
        val = ParagraphStyle("td", fontName="Helvetica", fontSize=7.5, textColor=B_BLACK)
        mono = ParagraphStyle("tm", fontName="Courier", fontSize=7, textColor=B_BLACK)

        header = [
            _para("#", lbl), _para("Date", lbl), _para("Amount", lbl),
            _para("Platform", lbl), _para("Category", lbl),
            _para("Severity", lbl), _para("Pulse Δ", lbl), _para("Score After", lbl),
        ]
        rows = [header]
        row_styles = [
            ("BACKGROUND", (0, 0), (-1, 0), B_DARK),
            ("TEXTCOLOR",  (0, 0), (-1, 0), WHITE),
        ]
        for i, t in enumerate(txns, 1):
            bg = colors.HexColor("#EDF4FB") if i % 2 == 0 else WHITE
            rows.append([
                _para(str(t["seq"]), val),
                _para(t["date"], val),
                _para(t["amount"], val),
                _para(t["platform"], val),
                _para(t["category_label"], val),
                _para(t["severity"], mono),
                _para(t["pulse_delta"], mono),
                _para(t["pulse_after"], mono),
            ])
            row_styles.append(("BACKGROUND", (0, i), (-1, i), bg))

        col_w = [8*mm, 20*mm, 22*mm, 24*mm, 40*mm, 17*mm, 16*mm, 18*mm]
        tbl = Table(rows, colWidths=col_w, repeatRows=1)
        tbl.setStyle(TableStyle(row_styles + [
            ("BOX",           (0, 0), (-1, -1), 0.8, B_DARK),
            ("INNERGRID",     (0, 0), (-1, -1), 0.2, B_GREY),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING",   (0, 0), (-1, -1), 3),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ]))
        elems.append(tbl)
        elems.append(_sp(2))
        elems.append(_para(
            f"Total transactions in this log: {section.get('total_count', 0)}  |  "
            f"All entries verifiable in core banking system.",
            s["body"]
        ))
        return elems

    def _checklist_section(self, section: Dict) -> List:
        s = self.s
        if not section:
            return []
        checks = section.get("checks", {})
        all_ok = section.get("all_passed", False)
        elems = [
            _sp(3),
            _para(section.get("title", ""), s["section_head"]),
            _sp(2),
        ]
        rows = []
        for label, passed in checks.items():
            tick   = "✓" if passed else "✗"
            colour = B_GREEN if passed else B_RED
            style  = ParagraphStyle(
                "ck", fontName="Helvetica-Bold", fontSize=8.5, textColor=colour
            )
            rows.append([
                _para(tick, style),
                _para(label, s["body"]),
            ])
        tbl = Table(rows, colWidths=[10*mm, None])
        tbl.setStyle(TableStyle([
            ("INNERGRID",    (0, 0), (-1, -1), 0.2, B_GREY),
            ("TOPPADDING",   (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
            ("LEFTPADDING",  (0, 0), (-1, -1), 4),
        ]))
        elems.append(tbl)
        elems.append(_sp(3))
        status_text = "ALL COMPLIANCE CHECKS PASSED" if all_ok else "ONE OR MORE CHECKS REQUIRE ATTENTION"
        status_color = B_GREEN if all_ok else B_RED
        status_style = ParagraphStyle(
            "cs", fontName="Helvetica-Bold", fontSize=9,
            textColor=WHITE, backColor=status_color,
            alignment=TA_CENTER, spaceAfter=4, leading=14
        )
        elems.append(_para(status_text, status_style))
        return elems

    def _oversight_section(self, section: Dict) -> List:
        s = self.s
        if not section:
            return []
        elems = self._fields_section(section)
        principle = section.get("principle", "")
        if principle:
            elems.append(_sp(3))
            principle_tbl = _boxed_table(
                [[_para(principle, s["body"])]],
                B_LIGHT, B_DARK
            )
            elems.append(principle_tbl)
        return elems

    def _cert_section(self, section: Dict) -> List:
        s = self.s
        if not section:
            return []
        cert = section.get("certification", "")
        elems = [
            _sp(4),
            _para(section.get("title", ""), s["section_head"]),
            _sp(3),
        ]
        cert_tbl = _boxed_table(
            [[_para(cert, s["body"])]],
            colors.HexColor("#F8F8F0"), B_DARK
        )
        elems.append(cert_tbl)
        return elems


# ══════════════════════════════════════════════════════════════════════════
#  REPORT B — Customer Wellness Notice PDF
# ══════════════════════════════════════════════════════════════════════════

def _cust_styles() -> Dict:
    return {
        "date":      ParagraphStyle("cd", fontName="Helvetica", fontSize=9,
                                    textColor=C_GREY, alignment=TA_RIGHT, spaceAfter=2),
        "ref":       ParagraphStyle("cr", fontName="Helvetica", fontSize=8,
                                    textColor=C_GREY, alignment=TA_RIGHT, spaceAfter=8),
        "salutation": ParagraphStyle("cs", fontName="Helvetica-Bold", fontSize=14,
                                     textColor=C_NAVY, spaceAfter=6, leading=20),
        "notice":    ParagraphStyle("cn", fontName="Helvetica-Oblique", fontSize=8.5,
                                    textColor=C_TEAL, alignment=TA_CENTER,
                                    spaceAfter=4, leading=13),
        "body":      ParagraphStyle("cb", fontName="Helvetica", fontSize=9.5,
                                    textColor=C_BLACK, alignment=TA_JUSTIFY,
                                    spaceAfter=8, leading=15),
        "body_small": ParagraphStyle("cbs", fontName="Helvetica", fontSize=8.5,
                                     textColor=C_GREY, alignment=TA_JUSTIFY,
                                     spaceAfter=6, leading=13),
        "section_head": ParagraphStyle("csh", fontName="Helvetica-Bold", fontSize=11.5,
                                       textColor=C_NAVY, spaceBefore=10,
                                       spaceAfter=4, leading=16),
        "subhead":   ParagraphStyle("csu", fontName="Helvetica-Bold", fontSize=9.5,
                                    textColor=C_TEAL, spaceBefore=6, spaceAfter=3),
        "txn_label": ParagraphStyle("ctl", fontName="Helvetica-Bold", fontSize=8,
                                    textColor=C_NAVY),
        "txn_value": ParagraphStyle("ctv", fontName="Helvetica", fontSize=8,
                                    textColor=C_BLACK),
        "txn_plain": ParagraphStyle("ctp", fontName="Helvetica-Oblique", fontSize=8,
                                    textColor=C_TEAL, leading=12),
        "option_title": ParagraphStyle("cot", fontName="Helvetica-Bold", fontSize=10,
                                       textColor=C_NAVY, spaceAfter=2),
        "option_body": ParagraphStyle("cob", fontName="Helvetica", fontSize=9,
                                      textColor=C_BLACK, spaceAfter=6, leading=14,
                                      leftIndent=4),
        "right_title": ParagraphStyle("crt", fontName="Helvetica-Bold", fontSize=9,
                                      textColor=C_NAVY, spaceAfter=1),
        "right_body": ParagraphStyle("crb", fontName="Helvetica", fontSize=8.5,
                                     textColor=C_BLACK, spaceAfter=5, leading=13,
                                     leftIndent=4),
        "sign_off":  ParagraphStyle("cso", fontName="Helvetica", fontSize=9.5,
                                    textColor=C_NAVY, spaceAfter=4, leading=16),
        "gen_note":  ParagraphStyle("cgn", fontName="Helvetica-Oblique", fontSize=7.5,
                                    textColor=C_GREY, spaceAfter=4, leading=11),
        "footer":    ParagraphStyle("cft", fontName="Helvetica", fontSize=6.5,
                                    textColor=C_GREY, alignment=TA_CENTER),
        "ai_badge":  ParagraphStyle("cab", fontName="Helvetica-Oblique", fontSize=8,
                                    textColor=C_TEAL, alignment=TA_CENTER,
                                    spaceAfter=3, leading=12),
    }


def _cust_header(label: str):
    def _h(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(C_NAVY)
        canvas.rect(0, PAGE_H - 14 * mm, PAGE_W, 14 * mm, fill=1, stroke=0)
        canvas.setFont("Helvetica-Bold", 11)
        canvas.setFillColor(WHITE)
        canvas.drawString(MARGIN_L, PAGE_H - 9.5 * mm, BANK_NAME_SHORT)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(C_BLUE)
        canvas.drawRightString(PAGE_W - MARGIN_R, PAGE_H - 9.5 * mm, label)
        canvas.setStrokeColor(C_TEAL)
        canvas.setLineWidth(1.5)
        canvas.line(0, PAGE_H - 15 * mm, PAGE_W, PAGE_H - 15 * mm)
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(C_GREY)
        canvas.drawString(MARGIN_L, PAGE_H - 20 * mm,
                          "Customer Wellness Programme  |  AI-Assisted  |  Human-Reviewed  |  Confidential")
        canvas.restoreState()
    return _h


def _cust_footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(C_TEAL)
    canvas.setLineWidth(0.6)
    canvas.line(MARGIN_L, MARGIN_B - 3 * mm, PAGE_W - MARGIN_R, MARGIN_B - 3 * mm)
    canvas.setFont("Helvetica", 6)
    canvas.setFillColor(C_GREY)
    canvas.drawString(MARGIN_L, MARGIN_B - 8 * mm, BANK_ADDRESS)
    canvas.drawString(MARGIN_L, MARGIN_B - 12 * mm, BANK_REG)
    canvas.drawString(MARGIN_L, MARGIN_B - 16 * mm, BANK_SUPPORT)
    canvas.setFont("Helvetica-Bold", 7)
    canvas.setFillColor(C_NAVY)
    canvas.drawRightString(PAGE_W - MARGIN_R, MARGIN_B - 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _cust_page(pid, label):
    def _cb(canvas, doc):
        _cust_header(label)(canvas, doc)
        _cust_footer(canvas, doc)
    return PageTemplate(id=pid, frames=[_frame()], onPage=_cb)


class CustomerNoticePDFBuilder:
    """Builds the Customer Wellness Notice PDF (Report B)."""

    def __init__(self):
        self.s = _cust_styles()

    def build(self, report: Dict[str, Any]) -> bytes:
        buf = io.BytesIO()
        doc = BaseDocTemplate(
            buf, pagesize=A4,
            leftMargin=MARGIN_L, rightMargin=MARGIN_R,
            topMargin=MARGIN_T, bottomMargin=MARGIN_B,
            title="Barclays — Your Account Wellness Check-In",
            author=BANK_NAME_SHORT,
            subject="Customer Wellness Notice",
        )
        doc.addPageTemplates([
            _cust_page("p1", "Your Wellness Check-In"),
            _cust_page("p2", "Account Activity & Wellness Score"),
            _cust_page("p3", "Your Support Plan"),
            _cust_page("p4", "Your Rights & How to Reach Us"),
        ])
        doc.build(self._story(report))
        return buf.getvalue()

    def _story(self, report: Dict) -> List:
        secs = report.get("sections", {})
        story = []

        # ── PAGE 1: Cover letter ───────────────────────────────────────
        story += self._page1(secs)

        # ── PAGE 2: Transaction timeline + pulse explanation ───────────
        story.append(PageBreak())
        story += self._page2(secs)

        # ── PAGE 3: Intervention solution plan ────────────────────────
        story.append(PageBreak())
        story += self._page3(secs, report.get("chosen_method", {}))

        # ── PAGE 4: Rights + Contact ───────────────────────────────────
        story.append(PageBreak())
        story += self._page4(secs)

        return story

    def _page1(self, secs: Dict) -> List:
        s    = self.s
        hdr  = secs.get("header", {})
        opening = secs.get("opening", "")
        elems = []

        elems.append(_para(hdr.get("date", ""), s["date"]))
        elems.append(_para(f"Reference: {hdr.get('ref_no', '')}", s["ref"]))
        elems.append(_para(hdr.get("salutation", "Dear Customer,"), s["salutation"]))

        # Important note box (non-threatening)
        notice_tbl = _boxed_table(
            [[_para(hdr.get("important_note", ""), s["notice"])]],
            C_SOFT, C_TEAL
        )
        elems += [notice_tbl, _sp(4)]

        # AI-generated opening paragraphs
        for para in opening.split("\n\n"):
            para = para.strip()
            if para:
                elems.append(_para(para, s["body"]))

        elems += [_sp(3), _hr(C_TEAL, 0.8)]
        return elems

    def _page2(self, secs: Dict) -> List:
        s    = self.s
        txn_sec  = secs.get("transaction_summary", {})
        pulse_exp = secs.get("pulse_explanation", "")
        elems = []

        elems.append(_para("Account Activity We Noticed", s["section_head"]))
        elems.append(_hr(C_TEAL, 1))
        elems.append(_sp(2))

        note = txn_sec.get("note", "")
        if note:
            elems.append(_para(note, s["body_small"]))
            elems.append(_sp(2))

        # Date-wise transaction cards
        for entry in txn_sec.get("entries", []):
            elems += self._txn_card(entry)

        elems += [_sp(4), _hr(C_TEAL, 0.5), _sp(3)]
        elems.append(_para("What This Means for Your Wellness Score", s["section_head"]))
        elems.append(_sp(2))

        for para in pulse_exp.split("\n\n"):
            para = para.strip()
            if para:
                elems.append(_para(para, s["body"]))

        return elems

    def _page3(self, secs: Dict, method: Dict) -> List:
        s         = self.s
        solution  = secs.get("solution", "")
        next_steps = secs.get("next_steps", {})
        elems     = []

        method_name = method.get("name", "Support Option")
        elems.append(_para("Your Personal Support Plan", s["section_head"]))
        elems.append(_hr(C_TEAL, 1))
        elems.append(_sp(2))

        # Method badge
        badge_style = ParagraphStyle(
            "mb", fontName="Helvetica-Bold", fontSize=10,
            textColor=WHITE, backColor=C_TEAL,
            alignment=TA_CENTER, spaceAfter=4, leading=15
        )
        elems.append(_para(f"Recommended Support: {method_name}", badge_style))
        elems.append(_sp(3))

        # AI-generated solution text
        for para in solution.split("\n\n"):
            para = para.strip()
            if para:
                elems.append(_para(para, s["body"]))

        elems += [_sp(4), _hr(C_TEAL, 0.5), _sp(3)]
        elems.append(_para(next_steps.get("intro", "Your next steps:"), s["subhead"]))
        elems.append(_sp(2))

        for opt in next_steps.get("options", []):
            elems += self._option_card(opt)

        return elems

    def _page4(self, secs: Dict) -> List:
        s       = self.s
        rights  = secs.get("rights", {})
        contact = secs.get("contact", {})
        elems   = []

        elems.append(_para("Your Rights — Plain and Simple", s["section_head"]))
        elems.append(_para(
            "Because an AI system was involved in preparing this letter, you have "
            "specific rights under RBI and Indian data protection law. Here they are:",
            s["body_small"]
        ))
        elems.append(_hr(C_TEAL, 1))
        elems.append(_sp(3))

        for right in rights.get("rights", []):
            elems.append(_para(f"✓  {right['title']}", s["right_title"]))
            elems.append(_para(right["detail"], s["right_body"]))

        data_note = rights.get("data_note", "")
        if data_note:
            dn = _boxed_table([[_para(data_note, s["body_small"])]], C_LIGHT, C_TEAL)
            elems += [_sp(2), dn]

        elems += [_sp(5), _hr(C_GREY, 0.4), _sp(4)]

        sign_off = contact.get("sign_off", "")
        for line in sign_off.split("\n"):
            if line.strip():
                elems.append(_para(line, s["sign_off"]))

        elems.append(_sp(5))
        contact_rows = [
            ["Phone",         contact.get("phone", "")],
            ["Email",         contact.get("email", "")],
            ["Grievance",     contact.get("grievance", "")],
            ["Nodal Officer", contact.get("nodal", "")],
        ]
        lbl = ParagraphStyle("rcl", fontName="Helvetica-Bold", fontSize=8, textColor=C_NAVY)
        val = ParagraphStyle("rcv", fontName="Helvetica", fontSize=8, textColor=C_BLACK)
        ctbl = Table(
            [[_para(r[0], lbl), _para(r[1], val)] for r in contact_rows],
            colWidths=["28%", "72%"]
        )
        ctbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), C_LIGHT),
            ("BOX",           (0, 0), (-1, -1), 0.8, C_TEAL),
            ("INNERGRID",     (0, 0), (-1, -1), 0.2, C_GREY),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ]))
        elems.append(ctbl)
        elems.append(_sp(4))

        gen_note = contact.get("generated_note", "")
        if gen_note:
            elems.append(_para(gen_note, s["gen_note"]))

        return elems

    # ── Customer Card Components ───────────────────────────────────────

    def _txn_card(self, entry: Dict) -> List:
        s     = self.s
        lbl   = ParagraphStyle("tl", fontName="Helvetica-Bold", fontSize=8, textColor=C_NAVY)
        val   = ParagraphStyle("tv", fontName="Helvetica", fontSize=8, textColor=C_BLACK)

        detail_rows = [
            [_para("Date",         lbl), _para(entry.get("date", ""), val),
             _para("Amount",       lbl), _para(entry.get("amount", ""), val)],
            [_para("Via",          lbl), _para(entry.get("platform", ""), val),
             _para("Wellness Δ",   lbl), _para(entry.get("pulse_change", ""), val)],
            [_para("What happened:", lbl),
             _para(entry.get("what_happened", ""), val), _para("", lbl), _para("", val)],
        ]
        inner = Table(detail_rows, colWidths=["18%", "32%", "18%", "32%"])
        inner.setStyle(TableStyle([
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ]))

        plain = entry.get("in_plain_english", "")
        card_rows = [[inner]]
        if plain:
            card_rows.append([_para(plain, s["txn_plain"])])

        card = Table(card_rows, colWidths=["100%"])
        card.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), C_LIGHT),
            ("BOX",           (0, 0), (-1, -1), 0.6, C_TEAL),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return [card, _sp(2)]

    def _option_card(self, opt: Dict) -> List:
        s     = self.s
        title  = opt.get("title", "")
        detail = opt.get("detail", "")
        rows   = [
            [_para(f"→  {title}", s["option_title"])],
            [_para(detail, s["option_body"])],
        ]
        card = Table(rows, colWidths=["100%"])
        card.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#F9FBFD")),
            ("BOX",           (0, 0), (-1, -1), 0.6, C_BLUE),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return [card, _sp(3)]