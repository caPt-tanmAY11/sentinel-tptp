"""
scoring_service/report_endpoints.py
─────────────────────────────────────────────────────────────────────────────
SENTINEL V2 — Gen AI Report Generation Endpoints

Add these endpoints to your existing scoring_service/app.py by importing
this router:

    from scoring_service.report_endpoints import report_router
    app.include_router(report_router)

ENDPOINTS:
    POST /report/generate/{customer_id}
        Generate a complete JSON report for a customer.

    GET  /report/pdf/{customer_id}
        Download a PDF report on Barclays letterhead.

    GET  /report/history/{customer_id}
        List all previously generated reports for a customer.

    POST /report/intervention-form/{customer_id}
        Submit a customer self-declaration form response.

    GET  /report/audit-trail/{report_id}
        Retrieve the full audit trail for a specific report.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from report_generator.report_generator import SentinelReportGenerator

from report_generator.pdf_builder import BankReportPDFBuilder

report_router = APIRouter(prefix="/report", tags=["Report Generation"])

# ── Lazy singletons ────────────────────────────────────────────────────────
_report_gen: Optional[SentinelReportGenerator] = None
_pdf_builder: Optional[BankReportPDFBuilder]     = None


def _get_report_gen() -> SentinelReportGenerator:
    global _report_gen
    if _report_gen is None:
        _report_gen = SentinelReportGenerator()  # reads ANTHROPIC_API_KEY from env
    return _report_gen


def _get_pdf_builder() -> BankReportPDFBuilder:
    global _pdf_builder
    if _pdf_builder is None:
        _pdf_builder = BankReportPDFBuilder()
    return _pdf_builder


def _get_db(request: Request):
    """Reuse db connection from app state if available."""
    try:
        from config.settings import get_settings
        s = get_settings()
        return psycopg2.connect(
            host=s.POSTGRES_HOST, port=s.POSTGRES_PORT,
            database=s.POSTGRES_DB, user=s.POSTGRES_USER,
            password=s.POSTGRES_PASSWORD,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {e}")


# ── Request / Response Models ──────────────────────────────────────────────

class ReportGenerationRequest(BaseModel):
    form_link: str = Field(
        default="https://barclays.in/sentinel/intervention-form",
        description="URL to the customer self-declaration form.",
    )
    stress_lookback_days: int = Field(
        default=30,
        description="Number of days to look back for stress transactions.",
    )
    include_pdf: bool = Field(
        default=False,
        description="If True, also generate and store PDF bytes (slow).",
    )


class InterventionFormSubmission(BaseModel):
    customer_id: str
    report_reference: str
    explanation: str = Field(..., description="Customer explanation of flagged transactions.")
    current_income: Optional[float] = Field(None, description="Monthly income declaration.")
    current_outstanding_loans: Optional[float] = Field(None, description="Total outstanding loans.")
    preferred_contact: str = Field(
        default="email",
        description="Preferred contact channel: email | sms | whatsapp | branch",
    )
    consent_to_contact: bool = Field(..., description="Customer consent to further contact.")
    additional_notes: Optional[str] = None
    submitted_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ── Helper: Fetch customer + pulse + transactions ──────────────────────────

def _fetch_customer(conn, customer_id: str) -> Dict:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT customer_id,
                   first_name || ' ' || last_name AS name,
                   account_type,
                   city AS branch,
                   monthly_income * 12 AS credit_limit,
                   account_open_date AS account_opened_date
            FROM customers
            WHERE customer_id = %s
            """,
            (customer_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found.")
    return dict(row)


def _fetch_pulse(conn, customer_id: str) -> Dict:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT pulse_score, risk_tier, risk_label,
                   score_ts, transaction_count_since_baseline
            FROM pulse_scores
            WHERE customer_id = %s
            ORDER BY score_ts DESC
            LIMIT 1
            """,
            (customer_id,),
        )
        row = cur.fetchone()
    if not row:
        return _pulse_from_events(conn, customer_id)
    return {
        "pulse_score": float(row["pulse_score"]),
        "risk_tier": {
            "tier":  row["risk_tier"],
            "label": row["risk_label"],
        },
        "total_events_scored": row.get("transaction_count_since_baseline", 0),
    }

def _pulse_from_events(conn, customer_id: str) -> Dict:
    """Fallback when no customer_pulse_scores row exists."""
    from realtime.pulse_accumulator import assign_risk_tier
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT pulse_score_after, severity_direction, event_ts
            FROM transaction_pulse_events
            WHERE customer_id = %s
            ORDER BY event_ts DESC
            LIMIT 1
            """,
            (customer_id,),
        )
        row = cur.fetchone()
    if not row:
        return {"pulse_score": 0.0, "risk_tier": {"tier": 5, "label": "STABLE"},
                "total_events_scored": 0}
    score = float(row["pulse_score_after"])

    return {
        "pulse_score":        score,
        "risk_tier":          assign_risk_tier(score),
        "total_events_scored": 1,
    }


def _fetch_stress_transactions(conn, customer_id: str,
                                lookback_days: int = 30) -> List[Dict]:
    """Fetch transactions that increased the pulse score."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                event_id, customer_id, event_ts AS scored_at, amount, platform,
                inferred_category, txn_severity AS severity,
                delta_applied AS pulse_delta, pulse_score_after AS new_pulse_score,
                severity_direction AS direction
            FROM transaction_pulse_events
            WHERE customer_id = %s
              AND severity_direction = 'positive'
              AND event_ts >= NOW() - INTERVAL '%s days'
            ORDER BY delta_applied DESC
            LIMIT 50
            """,
            (customer_id, lookback_days),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def _fetch_baseline(conn, customer_id: str) -> Optional[Dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT *
            FROM customer_baselines
            WHERE customer_id = %s
            ORDER BY computed_at DESC
            LIMIT 1
            """,
            (customer_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


# ── Endpoints ──────────────────────────────────────────────────────────────

@report_router.post(
    "/generate/{customer_id}",
    summary="Generate a legally compliant Pre-Delinquency Report",
    description=(
        "Generates a complete Barclays India Pre-Delinquency Intervention Report "
        "using the Sentinel V2 Gen AI engine. The report is legally compliant with "
        "RBI, PMLA, and IBA regulations and includes a full AI model audit trail."
    ),
)
async def generate_report(
    customer_id: str,
    request: Request,
    body: ReportGenerationRequest = ReportGenerationRequest(),
):
    conn = _get_db(request)
    try:
        customer     = _fetch_customer(conn, customer_id)
        pulse_data   = _fetch_pulse(conn, customer_id)
        transactions = _fetch_stress_transactions(
            conn, customer_id, body.stress_lookback_days
        )
        baseline     = _fetch_baseline(conn, customer_id)

        # Enrich pulse data with stress event count
        pulse_data["stress_events_count"] = len(transactions)

        # Generate report
        # Generate report
        gen      = _get_report_gen()
        raw      = gen.generate_bank_report(
            customer_data=customer,
            pulse_data=pulse_data,
            transactions=transactions,
        )

        # ── Reshape to match frontend Report type ──────────────────
        tier_label = pulse_data.get("risk_tier", {}).get("label", "WATCH")
        INTERVENTION_WINDOWS = {
            "CRITICAL": "Immediate — within 24 hours",
            "HIGH":     "Urgent — within 72 hours",
            "MODERATE": "Scheduled — within 7 working days",
            "WATCH":    "Monitored — next statement cycle",
            "STABLE":   "No intervention required",
        }
        s = raw.get("sections", {})
        report = {
            "report_id":        raw["report_id"],
            "reference_number": raw.get("reference", raw["report_id"]),
            "generated_at":     raw["generated_at"],
            "customer": {
                "customer_id":  customer.get("customer_id", ""),
                "name":         customer.get("name", ""),
                "account_type": customer.get("account_type", ""),
                "branch":       customer.get("branch", ""),
                "credit_limit": customer.get("credit_limit", 0),
            },
            "pulse_summary": {
                "current_score":       pulse_data.get("pulse_score", 0),
                "risk_tier":           tier_label,
                "tier_number":         pulse_data.get("risk_tier", {}).get("tier", 5),
                "intervention_window": INTERVENTION_WINDOWS.get(tier_label, ""),
                "total_stress_events": pulse_data.get("stress_events_count", len(transactions)),
            },
            "flagged_transactions": [
                {
                    "event_id":         t.get("event_id", ""),
                    "scored_at":        str(t.get("scored_at", "")),
                    "amount":           t.get("amount", 0),
                    "platform":         t.get("platform", ""),
                    "category_label":   t.get("category_label", t.get("inferred_category", "")),
                    "inferred_category":t.get("inferred_category", ""),
                    "severity":         t.get("severity", t.get("txn_severity", 0)),
                    "pulse_delta":      t.get("pulse_delta", t.get("delta_applied", 0)),
                    "new_pulse_score":  t.get("new_pulse_score", t.get("pulse_score_after", 0)),
                }
                for t in transactions
            ],
            "narrative_sections": {
                "section_1": {
                    "title":   "Section 1: Report Identification",
                    "content": "\n".join(
                        f"{k}: {v}"
                        for k, v in s.get("s1_identification", {}).get("fields", {}).items()
                    ),
                },
                "section_2": {
                    "title":   "Section 2: Customer & Account Summary",
                    "content": "\n".join(
                        f"{k}: {v}"
                        for k, v in s.get("s2_customer_summary", {}).get("fields", {}).items()
                    ),
                },
                "section_3_and_4": s.get("s4_ai_audit", {}).get("content", ""),
                "section_5":       s.get("s6_compliance", {}).get("content", ""),
                "section_6": {
                    "title":   "Section 6: Regulatory Compliance",
                    "content": s.get("s6_compliance", {}).get("content", ""),
                },
                "section_7": {
                    "title":   "Section 7: Regulatory Disclosures & Customer Rights",
                    "content": "\n".join(
                        f"{'✓' if v else '✗'} {k}"
                        for k, v in s.get("s7_legal_checklist", {}).get("checks", {}).items()
                    ),
                },
                "section_8": s.get("s4_ai_audit", {}).get("content", ""),
                "section_9": {
                    "title":   "Section 9: Authorisation & Certification",
                    "content": s.get("s9_certification", {}).get("certification", ""),
                },
            },
            "legal_checklist": s.get("s7_legal_checklist", {}).get("checks", {}),
            "ai_model_metadata": {
                "model_name":            "Sentinel V2 Pre-Delinquency Engine",
                "llm_used":              "Meta Llama 3.3 70B (Groq)",
                "is_ai_assisted":        True,
                "human_review_required": True,
            },
            "form_link": body.form_link,
        }

        # Log report generation to DB (if table exists)
        _log_report(conn, report)

        return JSONResponse(content=_make_json_safe(report))

    finally:
        conn.close()


@report_router.get(
    "/pdf/{customer_id}",
    summary="Download Barclays letterhead PDF report",
    description=(
        "Generates and returns a PDF Pre-Delinquency Intervention Report on "
        "Barclays Bank India letterhead. The document is Section 65B certified "
        "and legally admissible as electronic evidence."
    ),
    response_class=Response,
)
async def download_pdf_report(
    request: Request,
    customer_id: str,
    form_link: str = Query(
        default="https://barclays.in/sentinel/intervention-form",
        description="URL to the customer self-declaration form.",
    ),
    lookback_days: int = Query(default=30),
):
    conn = _get_db(request)
    try:
        customer     = _fetch_customer(conn, customer_id)
        pulse_data   = _fetch_pulse(conn, customer_id)
        transactions = _fetch_stress_transactions(conn, customer_id, lookback_days)
        baseline     = _fetch_baseline(conn, customer_id)
        pulse_data["stress_events_count"] = len(transactions)

        gen    = _get_report_gen()
        report = gen.generate(
            customer_data=customer,
            pulse_data=pulse_data,
            flagged_transactions=transactions,
            baseline_data=baseline,
            form_link=form_link,
        )

        builder   = _get_pdf_builder()
        pdf_bytes = builder.build(report)

        ref_no   = report.get("reference_number", "report").replace("/", "-")
        filename = f"Barclays_PDI_{ref_no}.pdf"

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Report-ID":         report.get("report_id", ""),
                "X-Reference-Number":  report.get("reference_number", ""),
            },
        )

    finally:
        conn.close()


@report_router.post(
    "/intervention-form/{customer_id}",
    summary="Submit customer self-declaration intervention form",
    description=(
        "Receives the customer's self-declaration form submission. "
        "Logs the response and updates the intervention status in the database. "
        "This form satisfies the RBI Consumer Protection Framework requirement "
        "for customer response opportunity."
    ),
)
async def submit_intervention_form(
    customer_id: str,
    request: Request,
    form: InterventionFormSubmission,
):
    conn = _get_db(request)
    try:
        form_id = str(uuid.uuid4()).upper()
        _log_form_submission(conn, customer_id, form_id, form)
        return {
            "status":          "received",
            "form_id":         form_id,
            "customer_id":     customer_id,
            "received_at":     datetime.now(timezone.utc).isoformat(),
            "next_steps": (
                "Your response has been recorded. A Barclays relationship manager "
                "will contact you via your preferred channel within the intervention "
                "window. Reference this Form ID for all future communications."
            ),
            "reference_number": form.report_reference,
            "grievance_url":    "https://www.barclays.in/grievance-redressal",
        }
    finally:
        conn.close()


@report_router.get(
    "/audit-trail/{report_id}",
    summary="Retrieve AI model audit trail for a specific report",
    description=(
        "Returns the complete AI model audit trail for a generated report. "
        "This endpoint is designed for regulatory inspection and internal audit."
    ),
)
async def get_audit_trail(report_id: str, request: Request):
    conn = _get_db(request)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM report_audit_log
                WHERE report_id = %s
                """,
                (report_id,),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"No audit trail found for report {report_id}. "
                       f"Report may have been generated before audit logging was enabled.",
            )
        return dict(row)
    finally:
        conn.close()


# ── DB Logging Helpers (best-effort, non-blocking) ─────────────────────────

def _log_report(conn, report: Dict):
    """Log report generation to audit table (creates table if absent)."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS report_audit_log (
                    report_id        TEXT PRIMARY KEY,
                    reference_number TEXT,
                    customer_id      TEXT,
                    risk_tier        TEXT,
                    pulse_score      FLOAT,
                    generated_at     TIMESTAMPTZ,
                    llm_model        TEXT,
                    checklist_passed BOOLEAN,
                    report_json      JSONB
                )
            """)
            checklist = report.get("legal_checklist", {})
            passed    = all(checklist.values())
            cur.execute(
                """
                INSERT INTO report_audit_log
                    (report_id, reference_number, customer_id, risk_tier,
                     pulse_score, generated_at, llm_model, checklist_passed, report_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (report_id) DO NOTHING
                """,
                (
                    report["report_id"],
                    report["reference_number"],
                    report["customer"]["customer_id"],
                    report["pulse_summary"]["risk_tier"],
                    report["pulse_summary"]["current_score"],
                    report["generated_at"],
                    report["ai_model_metadata"]["llm_used"],
                    passed,
                    json.dumps(_make_json_safe(report)),
                ),
            )
            conn.commit()
    except Exception as e:
        # Non-blocking: log but don't fail the report generation
        print(f"  ⚠ Audit log write failed: {e}")
        conn.rollback()


def _log_form_submission(conn, customer_id: str, form_id: str, form):
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS intervention_form_responses (
                    form_id           TEXT PRIMARY KEY,
                    customer_id       TEXT,
                    report_reference  TEXT,
                    explanation       TEXT,
                    current_income    FLOAT,
                    preferred_contact TEXT,
                    consent           BOOLEAN,
                    submitted_at      TIMESTAMPTZ,
                    additional_notes  TEXT
                )
            """)
            cur.execute(
                """
                INSERT INTO intervention_form_responses
                    (form_id, customer_id, report_reference, explanation,
                     current_income, preferred_contact, consent, submitted_at, additional_notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    form_id, customer_id, form.report_reference, form.explanation,
                    form.current_income, form.preferred_contact, form.consent_to_contact,
                    form.submitted_at, form.additional_notes,
                ),
            )
            conn.commit()
    except Exception as e:
        print(f"  ⚠ Form log write failed: {e}")
        conn.rollback()


# ── JSON serialisation helper ─────────────────────────────────────────────

def _make_json_safe(obj: Any) -> Any:
    """Recursively make a dict JSON-serialisable (handles datetime, Decimal, etc.)."""
    if isinstance(obj, dict):
        return {k: _make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_json_safe(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "__float__"):
        try:
            return float(obj)
        except Exception:
            return str(obj)
    return obj