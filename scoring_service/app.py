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
    """
    if _engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialised")
    try:
        result = _engine.process(event)
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
                OR c.account_id LIKE %s
            )""")
            pattern = f"%{search.lower()}%"
            params.extend([pattern, pattern.upper()])

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