"""
scoring_service/app.py
─────────────────────────────────────────────────────────────────────────────
FastAPI scoring service.

Endpoints:
  POST /ingest/transaction        — score one raw transaction synchronously
  GET  /customer/{id}/pulse       — get current pulse score + tier
  GET  /customer/{id}/pulse_history — last N transaction pulse events
  GET  /customer/{id}/baseline    — view the stored baseline
  POST /score/batch               — score a list of customers (overall score)
  GET  /health                    — service health check
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional, Any, Dict

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config.settings import get_settings
from schemas.transaction_event import TransactionEvent
from realtime.pulse_engine import PulseEngine
from realtime.pulse_accumulator import assign_risk_tier
from baseline.baseline_builder import get_baseline

from scoring_service.report_endpoints import report_router

settings = get_settings()

# ── Global state ──────────────────────────────────────────────────────────────
_engine: Optional[PulseEngine] = None
_redis  = None


def _get_db():
    return psycopg2.connect(
        host=settings.POSTGRES_HOST, port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB, user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine, _redis

    # Connect Redis
    try:
        import redis
        _redis = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            decode_responses=True,
        )
        _redis.ping()
        print("  ✓ Redis connected")
    except Exception as e:
        print(f"  ⚠ Redis unavailable: {e}")
        _redis = None

    # Initialise pulse engine (lazy-loads model on first call)
    _engine = PulseEngine(redis_client=_redis)
    print("  ✓ PulseEngine ready")

    yield

    print("Scoring service shutting down...")


app = FastAPI(
    title="SENTINEL V2 — Scoring Service",
    description="Real-time Pre-Delinquency Pulse Scoring API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(report_router)

# ── Response schemas ──────────────────────────────────────────────────────────

class TransactionScoreResponse(BaseModel):
    event_id:              str
    customer_id:           str
    scored_at:             str
    amount:                float
    platform:              str
    inferred_category:     str
    classifier_confidence: float
    txn_severity:          float
    severity_direction:    str
    delta_applied:         float
    pulse_score_before:    float
    pulse_score_after:     float
    risk_tier:             int
    risk_label:            str
    top_features:          List[Dict[str, Any]]
    model_version:         str
    scoring_latency_ms:    int
    # ── PFD fields — only populated when fraud_quarantined=True ──
    fraud_quarantined:          Optional[bool]  = None
    fraud_score:                Optional[float] = None
    fraud_reason:               Optional[str]   = None
    signal_international:       Optional[bool]  = None
    signal_amount_spike:        Optional[bool]  = None
    signal_freq_spike:          Optional[bool]  = None
    payment_holiday_suggested:  Optional[bool]  = None
    next_emi_due_date:          Optional[str]   = None
    emi_amount:                 Optional[float] = None
    alert_id: Optional[str] = None


class CustomerPulseResponse(BaseModel):
    customer_id:    str
    pulse_score:    float
    risk_tier:      int
    risk_label:     str
    last_updated:   Optional[str]
    score_count:    int


class PulseHistoryItem(BaseModel):
    event_id:           str
    event_ts:           str
    amount:             float
    platform:           str
    inferred_category:  str
    txn_severity:       float
    severity_direction: str
    delta_applied:      float
    pulse_score_before: float
    pulse_score_after:  float
    top_features:       List[Dict[str, Any]]


class HealthResponse(BaseModel):
    status:           str
    model_loaded:     bool
    redis_connected:  bool
    postgres_ok:      bool
    timestamp:        str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/ingest/transaction", response_model=TransactionScoreResponse)
async def ingest_transaction(event: TransactionEvent):
    """
    Accept a raw transaction event, score it immediately, return result.
    Same code path as the Kafka consumer — used for direct API injection.

    If the transaction triggers the Probable Fault Detection (PFD) engine,
    the response will contain fraud_quarantined=True and the pulse score
    will be unchanged. The Next.js layer checks this flag and dispatches
    the fraud alert email automatically.
    """
    if _engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialised")
    try:
        result = _engine.process(event)

        # Baseline / feature errors — not a fraud case, just incomplete data
        if "skip_reason" in result:
            raise HTTPException(
                status_code=422,
                detail=f"Transaction not scored: {result['skip_reason']}"
            )

        return TransactionScoreResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/customer/{customer_id}/pulse", response_model=CustomerPulseResponse)
async def get_customer_pulse(customer_id: str):
    """Get the current overall pulse score for a customer."""
    conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Verify customer exists
        cursor.execute("SELECT customer_id FROM customers WHERE customer_id = %s", (customer_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

        # Get latest score
        cursor.execute("""
            SELECT pulse_score, risk_tier, risk_label, score_ts, COUNT(*) OVER() as total
            FROM pulse_scores
            WHERE customer_id = %s
            ORDER BY score_ts DESC LIMIT 1
        """, (customer_id,))
        row = cursor.fetchone()

        if not row:
            tier = assign_risk_tier(0.0)
            return CustomerPulseResponse(
                customer_id=customer_id,
                pulse_score=0.0,
                risk_tier=tier["tier"],
                risk_label=tier["label"],
                last_updated=None,
                score_count=0,
            )

        cursor.execute("SELECT COUNT(*) as cnt FROM pulse_scores WHERE customer_id = %s", (customer_id,))
        cnt = cursor.fetchone()["cnt"]

        return CustomerPulseResponse(
            customer_id=customer_id,
            pulse_score=float(row["pulse_score"]),
            risk_tier=int(row["risk_tier"]),
            risk_label=row["risk_label"],
            last_updated=row["score_ts"].isoformat() if row["score_ts"] else None,
            score_count=int(cnt),
        )
    finally:
        conn.close()


@app.get("/customer/{customer_id}/pulse_history")
async def get_pulse_history(
    customer_id: str,
    last_n: int = Query(default=50, le=200),
):
    """Returns the last N transaction pulse events for a customer."""
    conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT event_id, event_ts, amount, platform,
                   inferred_category, txn_severity, severity_direction,
                   delta_applied, pulse_score_before, pulse_score_after,
                   top_features
            FROM transaction_pulse_events
            WHERE customer_id = %s
            ORDER BY event_ts DESC
            LIMIT %s
        """, (customer_id, last_n))
        rows = cursor.fetchall()
        return {
            "customer_id": customer_id,
            "total":       len(rows),
            "events": [
                {
                    "event_id":           str(r["event_id"]),
                    "event_ts":           r["event_ts"].isoformat(),
                    "amount":             float(r["amount"]),
                    "platform":           r["platform"],
                    "inferred_category":  r["inferred_category"],
                    "txn_severity":       float(r["txn_severity"]),
                    "severity_direction": r["severity_direction"],
                    "delta_applied":      float(r["delta_applied"]),
                    "pulse_score_before": float(r["pulse_score_before"]),
                    "pulse_score_after":  float(r["pulse_score_after"]),
                    "top_features":       r["top_features"] or [],
                }
                for r in rows
            ],
        }
    finally:
        conn.close()


@app.get("/customer/{customer_id}/baseline")
async def get_customer_baseline(customer_id: str):
    """Returns the stored statistical baseline for a customer."""
    conn = _get_db()
    try:
        baseline = get_baseline(customer_id, redis_client=_redis, conn=conn)
        if not baseline:
            raise HTTPException(status_code=404, detail="No baseline found. Run --step baselines first.")
        return {
            "customer_id":       baseline.customer_id,
            "computed_at":       baseline.computed_at.isoformat(),
            "window_days":       baseline.window_days,
            "transaction_count": baseline.transaction_count,
            "low_confidence":    baseline.low_confidence,
            "history_start":     baseline.history_start_date,
            "history_end":       baseline.history_end_date,
            "feature_means":     baseline.feature_means,
            "feature_stds":      baseline.feature_stds,
        }
    finally:
        conn.close()


@app.get("/scores/high_risk")
async def get_high_risk_customers(
    min_score: float = Query(default=0.55, ge=0.0, le=1.0),
    limit:     int   = Query(default=20,   le=100),
):
    """Returns customers with pulse score above threshold, latest score only."""
    conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT DISTINCT ON (ps.customer_id)
                ps.customer_id, c.first_name, c.last_name,
                ps.pulse_score, ps.risk_tier, ps.risk_label, ps.score_ts
            FROM pulse_scores ps
            JOIN customers c ON c.customer_id = ps.customer_id
            WHERE ps.pulse_score >= %s
            ORDER BY ps.customer_id, ps.score_ts DESC
        """, (min_score,))
        rows = cursor.fetchall()
        rows_sorted = sorted(rows, key=lambda r: float(r["pulse_score"]), reverse=True)[:limit]
        return {
            "total":    len(rows_sorted),
            "customers": [
                {
                    "customer_id":  str(r["customer_id"]),
                    "name":         f"{r['first_name']} {r['last_name']}",
                    "pulse_score":  float(r["pulse_score"]),
                    "risk_tier":    int(r["risk_tier"]),
                    "risk_label":   r["risk_label"],
                    "last_scored":  r["score_ts"].isoformat(),
                }
                for r in rows_sorted
            ],
        }
    finally:
        conn.close()


@app.get("/health", response_model=HealthResponse)
async def health_check():
    pg_ok = False
    try:
        conn = _get_db(); conn.close(); pg_ok = True
    except Exception:
        pass

    model_loaded = False
    if _engine:
        m = _engine._get_model()
        model_loaded = m is not None and m.is_loaded

    return HealthResponse(
        status="healthy",
        model_loaded=model_loaded,
        redis_connected=_redis is not None,
        postgres_ok=pg_ok,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.SCORING_SERVICE_PORT, reload=False)


# ── Additional endpoints for dashboard (Layer 7) ──────────────────────────────

@app.post("/auth/login")
async def login(form_data: dict):
    """
    Simple demo login. Returns a mock token.
    In production replace with real JWT auth.
    """
    email    = form_data.get("username", "")
    password = form_data.get("password", "")
    if email == "admin@sentinel.bank" and password == "sentinel_admin":
        return {
            "access_token": "sentinel_demo_token_v2",
            "role":         "credit_officer",
            "full_name":    "Credit Officer",
        }
    raise HTTPException(status_code=401, detail="Invalid credentials")


@app.get("/portfolio/metrics")
async def get_portfolio_metrics():
    """Portfolio-level KPIs for the dashboard header."""
    conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Total customers
        cursor.execute("SELECT COUNT(*) AS total FROM customers")
        total = cursor.fetchone()["total"]

        # Latest pulse score per customer → tier distribution
        cursor.execute("""
            SELECT risk_label, COUNT(*) AS cnt
            FROM (
                SELECT DISTINCT ON (customer_id)
                    customer_id, risk_label
                FROM pulse_scores
                ORDER BY customer_id, score_ts DESC
            ) latest
            GROUP BY risk_label
        """)
        tiers = {r["risk_label"]: int(r["cnt"]) for r in cursor.fetchall()}

        # Average pulse score
        cursor.execute("""
            SELECT ROUND(AVG(pulse_score)::numeric, 4) AS avg_score
            FROM (
                SELECT DISTINCT ON (customer_id)
                    customer_id, pulse_score
                FROM pulse_scores
                ORDER BY customer_id, score_ts DESC
            ) latest
        """)
        avg_row = cursor.fetchone()
        avg_score = float(avg_row["avg_score"]) if avg_row["avg_score"] else 0.0

        # Customers scored
        cursor.execute("""
            SELECT COUNT(DISTINCT customer_id) AS scored FROM pulse_scores
        """)
        scored = cursor.fetchone()["scored"]

        # Recent high-severity events (last 24h)
        cursor.execute("""
            SELECT COUNT(*) AS cnt FROM transaction_pulse_events
            WHERE event_ts > NOW() - INTERVAL '24 hours'
              AND txn_severity >= 0.55
        """)
        high_sev_24h = cursor.fetchone()["cnt"]

        cursor.close()

        return {
            "total_customers":    int(total),
            "scored_customers":   int(scored),
            "avg_pulse_score":    avg_score,
            "critical_count":     tiers.get("CRITICAL",  0),
            "high_count":         tiers.get("HIGH",       0),
            "moderate_count":     tiers.get("MODERATE",   0),
            "watch_count":        tiers.get("WATCH",      0),
            "stable_count":       tiers.get("STABLE",     0),
            "high_severity_24h":  int(high_sev_24h),
        }
    finally:
        conn.close()


@app.get("/customers")
async def get_customers(
    risk_label: Optional[str] = Query(default=None),
    search:     Optional[str] = Query(default=None),
    limit:      int           = Query(default=100, le=1500),
    offset:     int           = Query(default=0),
):
    """
    Paginated customer list with latest pulse score.
    Filterable by risk_label and name/account search.
    """
    conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Build query
        where_clauses = []
        params: list = []

        if risk_label and risk_label != "all":
            where_clauses.append("ps.risk_label = %s")
            params.append(risk_label.upper())

        if search:
            where_clauses.append("""(
                LOWER(c.first_name || ' ' || c.last_name) LIKE %s
                OR c.customer_id::text ILIKE %s
                OR c.account_id ILIKE %s
                OR c.account_number ILIKE %s
            )""")
            pattern_lower = f"%{search.lower()}%"
            pattern_ilike = f"%{search}%"
            params.extend([pattern_lower, pattern_ilike, pattern_ilike, pattern_ilike])

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        # Count total
        cursor.execute(f"""
            SELECT COUNT(*) AS total
            FROM customers c
            LEFT JOIN (
                SELECT DISTINCT ON (customer_id)
                    customer_id, pulse_score, risk_tier, risk_label, score_ts
                FROM pulse_scores
                ORDER BY customer_id, score_ts DESC
            ) ps ON ps.customer_id = c.customer_id
            {where_sql}
        """, params)
        total = cursor.fetchone()["total"]

        # Fetch page
        cursor.execute(f"""
            SELECT
                c.customer_id,
                c.first_name || ' ' || c.last_name   AS full_name,
                c.account_id,
                c.customer_segment                    AS segment,
                c.state,
                c.monthly_income,
                c.employment_type,
                COALESCE(ps.pulse_score, 0)           AS pulse_score,
                COALESCE(ps.risk_tier,  5)            AS risk_tier,
                COALESCE(ps.risk_label, 'STABLE')     AS risk_label,
                ps.score_ts
            FROM customers c
            LEFT JOIN (
                SELECT DISTINCT ON (customer_id)
                    customer_id, pulse_score, risk_tier, risk_label, score_ts
                FROM pulse_scores
                ORDER BY customer_id, score_ts DESC
            ) ps ON ps.customer_id = c.customer_id
            {where_sql}
            ORDER BY COALESCE(ps.pulse_score, 0) DESC
            LIMIT %s OFFSET %s
        """, params + [limit, offset])

        rows = cursor.fetchall()
        cursor.close()

        return {
            "total": int(total),
            "customers": [
                {
                    "customer_id":  str(r["customer_id"]),
                    "full_name":    r["full_name"],
                    "account_id":   r["account_id"],
                    "segment":      r["segment"],
                    "state":        r["state"],
                    "monthly_income": float(r["monthly_income"]),
                    "employment_type": r["employment_type"],
                    "pulse_score":  float(r["pulse_score"]),
                    "risk_tier":    int(r["risk_tier"]),
                    "risk_label":   r["risk_label"],
                    "last_scored":  r["score_ts"].isoformat() if r["score_ts"] else None,
                }
                for r in rows
            ],
        }
    finally:
        conn.close()


@app.get("/customer/{customer_id}/profile")
async def get_customer_profile(customer_id: str):
    """Returns full customer demographics, employment, and bank details."""
    conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT
                customer_id, first_name, last_name,
                first_name || ' ' || last_name AS full_name,
                email, phone, date_of_birth, gender, pan_number,
                employment_type, employer_id, employer_name,
                monthly_income, expected_salary_day,
                state, city, pincode, geography_risk_tier,
                customer_segment,
                account_id, account_number, account_type,
                account_open_date, customer_vintage_months,
                upi_vpa, ifsc_code, opening_balance,
                historical_delinquency_count, credit_bureau_score,
                created_at, updated_at
            FROM customers
            WHERE customer_id = %s
        """, (customer_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

        return {
            "customer_id":                str(row["customer_id"]),
            "first_name":                 row["first_name"],
            "last_name":                  row["last_name"],
            "full_name":                  row["full_name"],
            "email":                      row["email"],
            "phone":                      row["phone"],
            "date_of_birth":              row["date_of_birth"].isoformat() if row["date_of_birth"] else None,
            "gender":                     row["gender"],
            "pan_number":                 row["pan_number"],
            "employment_type":            row["employment_type"],
            "employer_id":                row["employer_id"],
            "employer_name":              row["employer_name"],
            "monthly_income":             float(row["monthly_income"]),
            "expected_salary_day":        row["expected_salary_day"],
            "state":                      row["state"],
            "city":                       row["city"],
            "pincode":                    row["pincode"],
            "geography_risk_tier":        row["geography_risk_tier"],
            "customer_segment":           row["customer_segment"],
            "account_id":                 row["account_id"],
            "account_number":             row["account_number"],
            "account_type":               row["account_type"],
            "account_open_date":          row["account_open_date"].isoformat() if row["account_open_date"] else None,
            "customer_vintage_months":    row["customer_vintage_months"],
            "upi_vpa":                    row["upi_vpa"],
            "ifsc_code":                  row["ifsc_code"],
            "opening_balance":            float(row["opening_balance"]) if row["opening_balance"] else 0,
            "historical_delinquency_count": row["historical_delinquency_count"],
            "credit_bureau_score":        row["credit_bureau_score"],
            "created_at":                 row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at":                 row["updated_at"].isoformat() if row["updated_at"] else None,
        }
    finally:
        conn.close()


@app.get("/interventions/pending")
async def get_pending_interventions():
    """
    Returns customers in HIGH or CRITICAL risk tier who have NOT received
    an intervention email in the current calendar week.
    """
    conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # Find high-risk customers, exclude those who are in the interventions table with sent_at in the last 7 days (or current week)
        cursor.execute("""
            SELECT ps.customer_id, c.first_name, c.last_name, c.email, ps.risk_tier, ps.risk_label
            FROM (
                SELECT DISTINCT ON (customer_id) customer_id, risk_tier, risk_label, score_ts
                FROM pulse_scores
                ORDER BY customer_id, score_ts DESC
            ) ps
            JOIN customers c ON c.customer_id = ps.customer_id
            WHERE ps.risk_tier <= 2
            AND NOT EXISTS (
                SELECT 1
                FROM interventions i
                WHERE i.customer_id = ps.customer_id
                  AND i.sent_at >= NOW() - INTERVAL '7 days'
            )
        """)
        rows = cursor.fetchall()
        return {
            "total": len(rows),
            "pending": [
                {
                    "customer_id": str(r["customer_id"]),
                    "first_name": r["first_name"],
                    "last_name": r["last_name"],
                    "email": r["email"],
                    "risk_tier": r["risk_tier"],
                    "risk_label": r["risk_label"],
                }
                for r in rows
            ]
        }
    finally:
        conn.close()


@app.post("/interventions")
async def create_intervention(payload: dict):
    """
    Record that an intervention email has been sent.
    Payload: {"customer_id": "uuid", "risk_tier": "HIGH"}
    """
    customer_id = payload.get("customer_id")
    risk_tier = payload.get("risk_tier")
    intervention_id = payload.get("intervention_id")
    
    if not customer_id or not risk_tier:
        raise HTTPException(status_code=400, detail="Missing customer_id or risk_tier")

    conn = _get_db()
    try:
        cursor = conn.cursor()
        if intervention_id:
            cursor.execute("""
                INSERT INTO interventions (intervention_id, customer_id, risk_tier, status)
                VALUES (%s, %s, %s, 'SENT')
                RETURNING intervention_id
            """, (intervention_id, customer_id, risk_tier))
        else:
            cursor.execute("""
                INSERT INTO interventions (customer_id, risk_tier, status)
                VALUES (%s, %s, 'SENT')
                RETURNING intervention_id
            """, (customer_id, risk_tier))
            
        final_id = cursor.fetchone()[0]
        conn.commit()
        return {"intervention_id": str(final_id), "status": "SENT"}
    finally:
        conn.close()


@app.post("/interventions/{intervention_id}/acknowledge")
async def acknowledge_intervention(intervention_id: str):
    """
    Mark an intervention as acknowledged by the customer.
    """
    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE interventions
            SET status = 'ACKNOWLEDGED', acknowledged_at = NOW()
            WHERE intervention_id = %s
            RETURNING intervention_id
        """, (intervention_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Intervention not found")
        conn.commit()
        return {"status": "ACKNOWLEDGED"}
    finally:
        conn.close()


@app.get("/interventions")
async def get_interventions():
    """
    Get all sent interventions for the dashboard.
    """
    conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT i.intervention_id, i.customer_id, c.first_name, c.last_name, 
                   i.risk_tier, i.sent_at, i.status, i.acknowledged_at
            FROM interventions i
            JOIN customers c ON c.customer_id = i.customer_id
            ORDER BY i.sent_at DESC
        """)
        rows = cursor.fetchall()
        return {
            "total": len(rows),
            "interventions": [
                {
                    "intervention_id": str(r["intervention_id"]),
                    "customer_id": str(r["customer_id"]),
                    "customer_name": f'{r["first_name"]} {r["last_name"]}',
                    "risk_tier": r["risk_tier"],
                    "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
                    "status": r["status"],
                    "acknowledged_at": r["acknowledged_at"].isoformat() if r["acknowledged_at"] else None
                }
                for r in rows
            ]
        }
    finally:
        conn.close()


@app.get("/customer/{customer_id}/loans")
async def get_customer_loans(customer_id: str):
    """Returns all loans for a customer."""
    conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Verify customer exists
        cursor.execute("SELECT customer_id FROM customers WHERE customer_id = %s", (customer_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

        cursor.execute("""
            SELECT
                loan_id, loan_account_number, loan_type,
                sanctioned_amount, outstanding_principal,
                emi_amount, emi_due_date, interest_rate,
                tenure_months, remaining_tenure, disbursement_date,
                days_past_due, failed_auto_debit_count_30d,
                status, created_at, updated_at
            FROM loans
            WHERE customer_id = %s
            ORDER BY disbursement_date DESC
        """, (customer_id,))
        rows = cursor.fetchall()

        return {
            "customer_id": customer_id,
            "total": len(rows),
            "loans": [
                {
                    "loan_id":                    str(r["loan_id"]),
                    "loan_account_number":        r["loan_account_number"],
                    "loan_type":                  r["loan_type"],
                    "sanctioned_amount":          float(r["sanctioned_amount"]),
                    "outstanding_principal":      float(r["outstanding_principal"]),
                    "emi_amount":                 float(r["emi_amount"]),
                    "emi_due_date":               r["emi_due_date"],
                    "interest_rate":              float(r["interest_rate"]),
                    "tenure_months":              r["tenure_months"],
                    "remaining_tenure":           r["remaining_tenure"],
                    "disbursement_date":          r["disbursement_date"].isoformat() if r["disbursement_date"] else None,
                    "days_past_due":              r["days_past_due"],
                    "failed_auto_debit_count_30d": r["failed_auto_debit_count_30d"],
                    "status":                     r["status"],
                }
                for r in rows
            ],
        }
    finally:
        conn.close()


@app.get("/customer/{customer_id}/credit_cards")
async def get_customer_credit_cards(customer_id: str):
    """Returns all credit cards for a customer."""
    conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Verify customer exists
        cursor.execute("SELECT customer_id FROM customers WHERE customer_id = %s", (customer_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

        cursor.execute("""
            SELECT
                card_id, card_account_number, credit_limit,
                current_balance, credit_utilization_pct,
                min_payment_due, min_payment_made,
                bureau_enquiry_count_90d, payment_due_date,
                status, created_at, updated_at
            FROM credit_cards
            WHERE customer_id = %s
            ORDER BY created_at DESC
        """, (customer_id,))
        rows = cursor.fetchall()

        return {
            "customer_id": customer_id,
            "total": len(rows),
            "credit_cards": [
                {
                    "card_id":                   str(r["card_id"]),
                    "card_account_number":       r["card_account_number"],
                    "credit_limit":              float(r["credit_limit"]),
                    "current_balance":           float(r["current_balance"]) if r["current_balance"] else 0,
                    "credit_utilization_pct":    float(r["credit_utilization_pct"]) if r["credit_utilization_pct"] else 0,
                    "min_payment_due":           float(r["min_payment_due"]) if r["min_payment_due"] else 0,
                    "min_payment_made":          r["min_payment_made"],
                    "bureau_enquiry_count_90d":  r["bureau_enquiry_count_90d"],
                    "payment_due_date":          r["payment_due_date"],
                    "status":                    r["status"],
                }
                for r in rows
            ],
        }
    finally:
        conn.close()


@app.get("/transactions/live")
async def get_live_transactions(
    limit: int = Query(default=50, le=200),
):
    """
    Returns the most recent N scored transaction events across ALL customers.
    Designed for the real-time feed — poll every 2-3 seconds.
    """
    conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT
                tpe.event_id,
                tpe.event_ts,
                tpe.customer_id,
                c.first_name || ' ' || c.last_name  AS customer_name,
                tpe.amount,
                tpe.platform,
                tpe.payment_status,
                tpe.receiver_id,
                tpe.inferred_category,
                tpe.txn_severity,
                tpe.severity_direction,
                tpe.delta_applied,
                tpe.pulse_score_after
            FROM transaction_pulse_events tpe
            JOIN customers c ON c.customer_id = tpe.customer_id
            ORDER BY tpe.event_ts DESC
            LIMIT %s
        """, (limit,))
        rows = cursor.fetchall()
        return {
            "total": len(rows),
            "transactions": [
                {
                    "event_id":           str(r["event_id"]),
                    "event_ts":           r["event_ts"].isoformat(),
                    "customer_id":        str(r["customer_id"]),
                    "customer_name":      r["customer_name"],
                    "amount":             float(r["amount"]),
                    "platform":           r["platform"] or "UPI",
                    "payment_status":     r["payment_status"] or "success",
                    "receiver_id":        r["receiver_id"] or "",
                    "inferred_category":  r["inferred_category"] or "GENERAL_DEBIT",
                    "txn_severity":       float(r["txn_severity"]),
                    "severity_direction": r["severity_direction"] or "neutral",
                    "delta_applied":      float(r["delta_applied"]),
                    "pulse_score_after":  float(r["pulse_score_after"]),
                }
                for r in rows
            ],
        }
    finally:
        conn.close()


@app.get("/customer/{customer_id}/transactions")
async def get_customer_transactions(
    customer_id: str,
    limit: int = Query(default=50, le=200),
):
    """Returns raw transactions for a customer, most recent first."""
    conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Verify customer exists
        cursor.execute("SELECT customer_id FROM customers WHERE customer_id = %s", (customer_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

        cursor.execute("""
            SELECT
                transaction_id, account_number,
                sender_id, sender_name, receiver_id, receiver_name,
                amount, platform, payment_status, reference_number,
                balance_before, balance_after,
                txn_timestamp
            FROM transactions
            WHERE customer_id = %s
            ORDER BY txn_timestamp DESC
            LIMIT %s
        """, (customer_id, limit))
        rows = cursor.fetchall()

        return {
            "customer_id": customer_id,
            "total": len(rows),
            "transactions": [
                {
                    "transaction_id":   str(r["transaction_id"]),
                    "account_number":   r["account_number"],
                    "sender_id":        r["sender_id"],
                    "sender_name":      r["sender_name"],
                    "receiver_id":      r["receiver_id"],
                    "receiver_name":    r["receiver_name"],
                    "amount":           float(r["amount"]),
                    "platform":         r["platform"],
                    "payment_status":   r["payment_status"],
                    "reference_number": r["reference_number"],
                    "balance_before":   float(r["balance_before"]) if r["balance_before"] is not None else None,
                    "balance_after":    float(r["balance_after"]) if r["balance_after"] is not None else None,
                    "txn_timestamp":    r["txn_timestamp"].isoformat(),
                }
                for r in rows
            ],
        }
    finally:
        conn.close()

@app.get("/interventions/{intervention_id}/details")
async def get_intervention_details(intervention_id: str):
    """
    Returns intervention details + customer info for a given intervention_id.
    Used by the grievance submission route to identify the customer.
    """
    conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT 
                i.intervention_id,
                i.customer_id,
                i.risk_tier,
                i.status,
                i.sent_at,
                c.first_name || ' ' || c.last_name AS customer_name,
                c.email AS customer_email
            FROM interventions i
            JOIN customers c ON c.customer_id = i.customer_id
            WHERE i.intervention_id = %s
        """, (intervention_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Intervention not found")
        return {
            "intervention_id": str(row["intervention_id"]),
            "customer_id":     str(row["customer_id"]),
            "customer_name":   row["customer_name"],
            "customer_email":  row["customer_email"],
            "risk_tier":       row["risk_tier"],
            "status":          row["status"],
            "sent_at":         row["sent_at"].isoformat() if row["sent_at"] else None,
        }
    finally:
        conn.close()


@app.post("/grievances")
async def create_grievance(payload: dict):
    """
    Save a customer grievance to the DB.
    Payload: { intervention_id, customer_id, customer_name, message }
    """
    intervention_id = payload.get("intervention_id")
    customer_id     = payload.get("customer_id")
    customer_name   = payload.get("customer_name")
    message         = payload.get("message")

    if not all([intervention_id, customer_id, customer_name, message]):
        raise HTTPException(status_code=400, detail="Missing required fields")

    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO grievances 
                (intervention_id, customer_id, customer_name, message)
            VALUES (%s, %s, %s, %s)
            RETURNING grievance_id, submitted_at
        """, (intervention_id, customer_id, customer_name, message))
        row = cursor.fetchone()
        conn.commit()
        return {
            "grievance_id":  str(row[0]),
            "submitted_at":  row[1].isoformat(),
            "status":        "OPEN",
        }
    finally:
        conn.close()


@app.get("/grievances")
async def get_grievances():
    """
    Returns all grievances for the dashboard, most recent first.
    """
    conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT
                g.grievance_id,
                g.customer_id,
                g.customer_name,
                g.message,
                g.submitted_at,
                g.status,
                i.risk_tier
            FROM grievances g
            LEFT JOIN interventions i ON i.intervention_id = g.intervention_id
            ORDER BY g.submitted_at DESC
        """)
        rows = cursor.fetchall()
        return {
            "total": len(rows),
            "grievances": [
                {
                    "grievance_id":  str(r["grievance_id"]),
                    "customer_id":   str(r["customer_id"]),
                    "customer_name": r["customer_name"],
                    "message":       r["message"],
                    "submitted_at":  r["submitted_at"].isoformat() if r["submitted_at"] else None,
                    "status":        r["status"],
                    "risk_tier":     r["risk_tier"],
                }
                for r in rows
            ],
        }
    finally:
        conn.close()


@app.get("/monitoring/psi-air")
async def get_psi_air_monitoring():
    """
    Returns PSI (Population Stability Index) and AIR (Adverse Impact Ratio) monitoring data.
    Includes drift detection and fairness audit metrics.
    """
    conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Fetch PSI monitoring data
        cursor.execute("""
            SELECT
                feature_name,
                metric_value as psi_value,
                status as psi_status,
                monitored_at as created_at,
                details
            FROM model_monitoring
            WHERE monitor_type = 'PSI'
            ORDER BY monitored_at DESC, feature_name ASC
            LIMIT 100
        """)
        psi_rows = cursor.fetchall()
        
        # Fetch AIR monitoring data
        cursor.execute("""
            SELECT
                feature_name as air_group,
                metric_value as air_value,
                status as air_status,
                monitored_at as created_at,
                details
            FROM model_monitoring
            WHERE monitor_type = 'AIR'
            ORDER BY monitored_at DESC, feature_name ASC
            LIMIT 100
        """)
        air_rows = cursor.fetchall()
        
        # Get latest timestamp
        cursor.execute("""
            SELECT MAX(monitored_at) as latest_update
            FROM model_monitoring
        """)
        latest = cursor.fetchone()
        
        return {
            "latest_update": latest["latest_update"].isoformat() if latest["latest_update"] else None,
            "psi": [
                {
                    "feature_name": r["feature_name"],
                    "psi_value": float(r["psi_value"]),
                    "psi_status": r["psi_status"],
                    "created_at": r["created_at"].isoformat(),
                    "details": r["details"] or {},
                }
                for r in psi_rows
            ],
            "air": [
                {
                    "air_group": r["air_group"],
                    "air_value": float(r["air_value"]),
                    "air_status": r["air_status"],
                    "created_at": r["created_at"].isoformat(),
                    "details": r["details"] or {},
                }
                for r in air_rows
            ],
        }
    finally:
        conn.close()


@app.get("/audit/full-trail")
async def get_full_audit_trail(
    customer_id: Optional[str] = None,
    limit: int = Query(default=500, le=5000),
):
    """
    Returns the complete audit trail of transaction pulse events.
    Optionally filtered by customer_id. Includes all transaction details and scoring decisions.
    """
    conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        if customer_id:
            cursor.execute("""
                SELECT
                    event_id,
                    event_ts,
                    customer_id,
                    amount,
                    platform,
                    payment_status,
                    receiver_id,
                    inferred_category,
                    classifier_confidence,
                    txn_severity,
                    severity_direction,
                    delta_applied,
                    pulse_score_before,
                    pulse_score_after,
                    top_features,
                    model_version,
                    scoring_latency_ms
                FROM transaction_pulse_events
                WHERE customer_id = %s
                ORDER BY event_ts DESC
                LIMIT %s
            """, (customer_id, limit))
        else:
            cursor.execute("""
                SELECT
                    event_id,
                    event_ts,
                    customer_id,
                    amount,
                    platform,
                    payment_status,
                    receiver_id,
                    inferred_category,
                    classifier_confidence,
                    txn_severity,
                    severity_direction,
                    delta_applied,
                    pulse_score_before,
                    pulse_score_after,
                    top_features,
                    model_version,
                    scoring_latency_ms
                FROM transaction_pulse_events
                ORDER BY event_ts DESC
                LIMIT %s
            """, (limit,))
        
        rows = cursor.fetchall()
        
        return {
            "total": len(rows),
            "customer_id": customer_id,
            "audit_events": [
                {
                    "event_id": str(r["event_id"]),
                    "event_ts": r["event_ts"].isoformat(),
                    "customer_id": str(r["customer_id"]),
                    "amount": float(r["amount"]),
                    "platform": r["platform"],
                    "payment_status": r["payment_status"],
                    "receiver_id": r["receiver_id"],
                    "inferred_category": r["inferred_category"],
                    "classifier_confidence": float(r["classifier_confidence"]) if r["classifier_confidence"] else None,
                    "txn_severity": float(r["txn_severity"]),
                    "severity_direction": r["severity_direction"],
                    "delta_applied": float(r["delta_applied"]),
                    "pulse_score_before": float(r["pulse_score_before"]),
                    "pulse_score_after": float(r["pulse_score_after"]),
                    "top_features": json.loads(r["top_features"]) if isinstance(r["top_features"], str) else r["top_features"],
                    "model_version": r["model_version"],
                    "scoring_latency_ms": r["scoring_latency_ms"],
                }
                for r in rows
            ],
        }
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════════════
# PROBABLE FAULT DETECTION (PFD) — Fraud Alert Endpoints
# ═══════════════════════════════════════════════════════════════════════════

# ── Pydantic models ───────────────────────────────────────────────────────

class FraudAlertSummary(BaseModel):
    alert_id:                   str
    customer_id:                str
    first_name:                 Optional[str] = None
    last_name:                  Optional[str] = None
    email:                      Optional[str] = None
    transaction_id:             str
    txn_timestamp:              str
    txn_amount:                 float
    platform:                   str
    receiver_vpa:               Optional[str] = None
    receiver_name:              Optional[str] = None
    receiver_country:           str
    currency:                   str
    signal_international:       bool
    signal_amount_spike:        bool
    signal_freq_spike:          bool
    fraud_score:                float
    fraud_reason:               str
    amount_zscore:              Optional[float] = None
    baseline_amount_avg:        Optional[float] = None
    baseline_amount_std:        Optional[float] = None
    hourly_txn_count:           Optional[int]   = None
    baseline_hourly_avg:        Optional[float] = None
    status:                     str
    alert_email_sent:           bool
    alert_email_sent_at:        Optional[str]   = None
    reviewed_by:                Optional[str]   = None
    reviewed_at:                Optional[str]   = None
    review_notes:               Optional[str]   = None
    next_emi_due_date:          Optional[str]   = None
    emi_amount:                 Optional[float] = None
    payment_holiday_suggested:  bool
    created_at:                 str


class FraudReviewRequest(BaseModel):
    status:       str    # REVIEWED | DISMISSED | CONFIRMED
    reviewed_by:  str
    review_notes: Optional[str] = None


# ── Helper — shared row → dict serialiser ────────────────────────────────

def _serialise_alert(row: dict) -> dict:
    """Convert a fraud_alerts DB row to a JSON-safe dict."""
    def _dt(v):
        return v.isoformat() if v and hasattr(v, "isoformat") else (str(v) if v else None)

    return {
        "alert_id":                 str(row["alert_id"]),
        "customer_id":              str(row["customer_id"]),
        "first_name":               row.get("first_name"),
        "last_name":                row.get("last_name"),
        "email":                    row.get("email"),
        "transaction_id":           str(row["transaction_id"]),
        "txn_timestamp":            _dt(row["txn_timestamp"]),
        "txn_amount":               float(row["txn_amount"]),
        "platform":                 row["platform"],
        "receiver_vpa":             row.get("receiver_vpa"),
        "receiver_name":            row.get("receiver_name"),
        "receiver_country":         row["receiver_country"],
        "currency":                 row["currency"],
        "signal_international":     bool(row["signal_international"]),
        "signal_amount_spike":      bool(row["signal_amount_spike"]),
        "signal_freq_spike":        bool(row["signal_freq_spike"]),
        "fraud_score":              float(row["fraud_score"]),
        "fraud_reason":             row["fraud_reason"],
        "amount_zscore":            float(row["amount_zscore"]) if row.get("amount_zscore") else None,
        "baseline_amount_avg":      float(row["baseline_amount_avg"]) if row.get("baseline_amount_avg") else None,
        "baseline_amount_std":      float(row["baseline_amount_std"]) if row.get("baseline_amount_std") else None,
        "hourly_txn_count":         int(row["hourly_txn_count"]) if row.get("hourly_txn_count") else None,
        "baseline_hourly_avg":      float(row["baseline_hourly_avg"]) if row.get("baseline_hourly_avg") else None,
        "status":                   row["status"],
        "alert_email_sent":         bool(row["alert_email_sent"]),
        "alert_email_sent_at":      _dt(row.get("alert_email_sent_at")),
        "reviewed_by":              row.get("reviewed_by"),
        "reviewed_at":              _dt(row.get("reviewed_at")),
        "review_notes":             row.get("review_notes"),
        "next_emi_due_date":        _dt(row.get("next_emi_due_date")),
        "emi_amount":               float(row["emi_amount"]) if row.get("emi_amount") else None,
        "payment_holiday_suggested": bool(row["payment_holiday_suggested"]),
        "created_at":               _dt(row["created_at"]),
    }


# ── Endpoint 1: All fraud alerts for one customer ─────────────────────────

@app.get("/customer/{customer_id}/fraud_alerts")
async def get_customer_fraud_alerts(
    customer_id: str,
    status:  Optional[str] = Query(None, description="Filter by status: OPEN|REVIEWED|DISMISSED|CONFIRMED"),
    limit:   int           = Query(50, ge=1, le=200),
):
    """
    Return all fraud alerts for a specific customer, newest first.
    Optionally filter by lifecycle status.
    """
    conn = _get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if status:
                cur.execute("""
                    SELECT fa.*,
                           c.first_name, c.last_name, c.email
                    FROM   fraud_alerts fa
                    JOIN   customers    c  USING (customer_id)
                    WHERE  fa.customer_id = %s
                      AND  fa.status      = %s
                    ORDER  BY fa.created_at DESC
                    LIMIT  %s
                """, (customer_id, status.upper(), limit))
            else:
                cur.execute("""
                    SELECT fa.*,
                           c.first_name, c.last_name, c.email
                    FROM   fraud_alerts fa
                    JOIN   customers    c  USING (customer_id)
                    WHERE  fa.customer_id = %s
                    ORDER  BY fa.created_at DESC
                    LIMIT  %s
                """, (customer_id, limit))

            rows = cur.fetchall()
            return {
                "customer_id":  customer_id,
                "total":        len(rows),
                "fraud_alerts": [_serialise_alert(dict(r)) for r in rows],
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ── Endpoint 2: Portfolio-wide open fraud alerts (for dashboard) ──────────

@app.get("/fraud_alerts")
async def get_all_fraud_alerts(
    status: Optional[str] = Query("OPEN", description="OPEN|REVIEWED|DISMISSED|CONFIRMED|ALL"),
    limit:  int           = Query(100, ge=1, le=500),
):
    """
    Return fraud alerts across all customers — used by the dashboard
    fraud monitoring panel. Defaults to OPEN alerts only.
    Pass status=ALL to return every alert regardless of lifecycle stage.
    """
    conn = _get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if status and status.upper() != "ALL":
                cur.execute("""
                    SELECT fa.*,
                           c.first_name, c.last_name, c.email
                    FROM   fraud_alerts fa
                    JOIN   customers    c  USING (customer_id)
                    WHERE  fa.status = %s
                    ORDER  BY fa.created_at DESC
                    LIMIT  %s
                """, (status.upper(), limit))
            else:
                cur.execute("""
                    SELECT fa.*,
                           c.first_name, c.last_name, c.email
                    FROM   fraud_alerts fa
                    JOIN   customers    c  USING (customer_id)
                    ORDER  BY fa.created_at DESC
                    LIMIT  %s
                """, (limit,))

            rows = cur.fetchall()
            alerts = [_serialise_alert(dict(r)) for r in rows]

            # Quick summary counts for the dashboard header
            open_count      = sum(1 for a in alerts if a["status"] == "OPEN")
            confirmed_count = sum(1 for a in alerts if a["status"] == "CONFIRMED")
            holiday_count   = sum(1 for a in alerts if a["payment_holiday_suggested"])

            return {
                "total":                  len(alerts),
                "open_count":             open_count,
                "confirmed_count":        confirmed_count,
                "payment_holiday_count":  holiday_count,
                "fraud_alerts":           alerts,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ── Endpoint 3: Officer reviews an alert ─────────────────────────────────

@app.patch("/fraud_alerts/{alert_id}/review")
async def review_fraud_alert(alert_id: str, payload: FraudReviewRequest):
    """
    Bank officer marks an alert as REVIEWED, DISMISSED, or CONFIRMED.
    Sets reviewed_by, reviewed_at, and optional review_notes.
    """
    valid_statuses = {"REVIEWED", "DISMISSED", "CONFIRMED"}
    if payload.status.upper() not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {valid_statuses}"
        )

    conn = _get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                UPDATE fraud_alerts
                SET    status       = %s,
                       reviewed_by  = %s,
                       reviewed_at  = NOW(),
                       review_notes = %s
                WHERE  alert_id = %s
                RETURNING alert_id, status, reviewed_by, reviewed_at
            """, (
                payload.status.upper(),
                payload.reviewed_by,
                payload.review_notes,
                alert_id,
            ))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Alert not found")
            conn.commit()
            return {
                "alert_id":    str(row["alert_id"]),
                "status":      row["status"],
                "reviewed_by": row["reviewed_by"],
                "reviewed_at": row["reviewed_at"].isoformat(),
            }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ── Endpoint 4: Next.js marks email as sent ───────────────────────────────

@app.post("/fraud_alerts/{alert_id}/email_sent")
async def mark_fraud_alert_email_sent(alert_id: str):
    """
    Called by the Next.js fraud alert email route immediately after
    nodemailer successfully dispatches the alert email.
    Stamps alert_email_sent=True and alert_email_sent_at=NOW().
    Kept separate from the alert creation so email failures never
    roll back the fraud_alert row itself.
    """
    conn = _get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                UPDATE fraud_alerts
                SET    alert_email_sent    = TRUE,
                       alert_email_sent_at = NOW()
                WHERE  alert_id = %s
                RETURNING alert_id, alert_email_sent, alert_email_sent_at
            """, (alert_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Alert not found")
            conn.commit()
            return {
                "alert_id":            str(row["alert_id"]),
                "alert_email_sent":    row["alert_email_sent"],
                "alert_email_sent_at": row["alert_email_sent_at"].isoformat(),
            }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()