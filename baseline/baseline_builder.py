"""
baseline/baseline_builder.py
─────────────────────────────────────────────────────────────────────────────
Builds per-customer statistical baselines from historical transaction data.

TIME BOUNDARY (strictly enforced):
  baseline_end   = now - 30 days   ← hard upper limit, never crossed
  baseline_start = now - 120 days  ← start of all generated history

Weekly snapshots are taken within the baseline window.
Feature engine is called with as_of = each snapshot datetime.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List

import numpy as np
import psycopg2
from psycopg2.extras import RealDictCursor

from config.settings import get_settings
from feature_engine.features import compute_all_features, FEATURE_NAMES
from baseline.baseline_schema import CustomerBaseline

settings = get_settings()


def _get_db():
    return psycopg2.connect(
        host=settings.POSTGRES_HOST, port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB, user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )


def build_customer_baseline(
    customer_id: str,
    conn=None,
    redis_client=None,
) -> Optional[CustomerBaseline]:
    """
    Build and store the statistical baseline for one customer.

    Returns:
        CustomerBaseline if successful, None if customer not found.
    """
    close_conn = conn is None
    if conn is None:
        conn = _get_db()

    try:
        now = datetime.now(timezone.utc)

        # Strict time boundaries — never cross baseline_end
        baseline_end   = now - timedelta(days=30)
        baseline_start = now - timedelta(days=settings.BASELINE_HISTORY_TOTAL_DAYS)

        # Count transactions in baseline window
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM transactions
            WHERE customer_id = %s
              AND txn_timestamp > %s AND txn_timestamp <= %s
        """, (customer_id, baseline_start, baseline_end))
        row = cursor.fetchone()
        txn_count      = int(row["cnt"]) if row else 0
        low_confidence = txn_count < settings.BASELINE_MIN_TRANSACTIONS

        # Build weekly snapshot schedule within the baseline window
        snap_dt   = baseline_start + timedelta(days=settings.BASELINE_SNAPSHOT_INTERVAL_DAYS)
        snapshots = []
        while snap_dt <= baseline_end:
            snapshots.append(snap_dt)
            snap_dt += timedelta(days=settings.BASELINE_SNAPSHOT_INTERVAL_DAYS)

        if not snapshots:
            cursor.close()
            return None

        # Compute feature vector at each snapshot
        feature_vectors: List[Dict[str, float]] = []
        for snap in snapshots:
            try:
                fv = compute_all_features(customer_id, as_of=snap, conn=conn)
                feature_vectors.append(fv)
            except Exception:
                continue  # skip bad snapshots

        if not feature_vectors:
            cursor.close()
            return None

        # Aggregate statistics across all snapshots
        feature_means: Dict[str, float] = {}
        feature_stds:  Dict[str, float] = {}
        feature_p25:   Dict[str, float] = {}
        feature_p75:   Dict[str, float] = {}
        feature_p95:   Dict[str, float] = {}

        for fname in FEATURE_NAMES:
            vals = [fv.get(fname, 0.0) for fv in feature_vectors]
            arr  = np.array(vals, dtype=np.float64)
            arr  = arr[np.isfinite(arr)]

            if len(arr) == 0:
                feature_means[fname] = 0.0
                feature_stds[fname]  = 0.0
                feature_p25[fname]   = 0.0
                feature_p75[fname]   = 0.0
                feature_p95[fname]   = 0.0
            else:
                feature_means[fname] = round(float(np.mean(arr)),              6)
                feature_stds[fname]  = round(float(np.std(arr)),               6)
                feature_p25[fname]   = round(float(np.percentile(arr, 25)),    6)
                feature_p75[fname]   = round(float(np.percentile(arr, 75)),    6)
                feature_p95[fname]   = round(float(np.percentile(arr, 95)),    6)

        cursor.close()

        baseline = CustomerBaseline(
            customer_id=customer_id,
            computed_at=now,
            window_days=settings.BASELINE_WINDOW_DAYS,
            history_start_date=baseline_start.date().isoformat(),
            history_end_date=baseline_end.date().isoformat(),
            transaction_count=txn_count,
            low_confidence=low_confidence,
            feature_means=feature_means,
            feature_stds=feature_stds,
            feature_p25=feature_p25,
            feature_p75=feature_p75,
            feature_p95=feature_p95,
        )

        _save_to_postgres(baseline, conn)

        if redis_client:
            _save_to_redis(baseline, redis_client)

        return baseline

    finally:
        if close_conn:
            conn.close()


def _save_to_postgres(baseline: CustomerBaseline, conn) -> None:
    cursor = conn.cursor()
    # Deactivate previous baseline
    cursor.execute("""
        UPDATE customer_baselines SET is_active = FALSE
        WHERE customer_id = %s AND is_active = TRUE
    """, (baseline.customer_id,))
    # Insert new
    cursor.execute("""
        INSERT INTO customer_baselines (
            baseline_id, customer_id, computed_at,
            window_days, history_start_date, history_end_date,
            transaction_count, low_confidence,
            feature_means, feature_stds,
            feature_p25, feature_p75, feature_p95,
            is_active
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
    """, (
        str(uuid.uuid4()), baseline.customer_id, baseline.computed_at,
        baseline.window_days, baseline.history_start_date, baseline.history_end_date,
        baseline.transaction_count, baseline.low_confidence,
        json.dumps(baseline.feature_means), json.dumps(baseline.feature_stds),
        json.dumps(baseline.feature_p25),   json.dumps(baseline.feature_p75),
        json.dumps(baseline.feature_p95),
    ))
    conn.commit()
    cursor.close()


def _save_to_redis(baseline: CustomerBaseline, redis_client) -> None:
    key     = f"baseline:{baseline.customer_id}"
    payload = json.dumps(baseline.to_redis_dict())
    ttl_sec = settings.BASELINE_REDIS_TTL_HOURS * 3600
    redis_client.setex(key, ttl_sec, payload)


def get_baseline(
    customer_id: str,
    redis_client=None,
    conn=None,
) -> Optional[CustomerBaseline]:
    """
    Get baseline for a customer. Tries Redis first, falls back to PostgreSQL.
    """
    # Try Redis first
    if redis_client:
        try:
            data = redis_client.get(f"baseline:{customer_id}")
            if data:
                return CustomerBaseline.from_redis_dict(json.loads(data))
        except Exception:
            pass

    # Fall back to PostgreSQL
    close_conn = conn is None
    if conn is None:
        conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT * FROM customer_baselines
            WHERE customer_id = %s AND is_active = TRUE
            ORDER BY computed_at DESC LIMIT 1
        """, (customer_id,))
        row = cursor.fetchone()
        cursor.close()
        if not row:
            return None
        return CustomerBaseline(
            customer_id=str(row["customer_id"]),
            computed_at=row["computed_at"],
            window_days=int(row["window_days"]),
            history_start_date=str(row["history_start_date"]) if row["history_start_date"] else None,
            history_end_date=str(row["history_end_date"])     if row["history_end_date"]   else None,
            transaction_count=int(row["transaction_count"]),
            low_confidence=bool(row["low_confidence"]),
            feature_means=row["feature_means"] or {},
            feature_stds=row["feature_stds"]   or {},
            feature_p25=row["feature_p25"]     or {},
            feature_p75=row["feature_p75"]     or {},
            feature_p95=row["feature_p95"]     or {},
        )
    finally:
        if close_conn:
            conn.close()


def batch_get_baselines(
    customer_ids: list,
    conn=None,
) -> Dict[str, "CustomerBaseline"]:
    """
    Fetch active baselines for multiple customers in a single query.

    Returns:
        Dict of {customer_id: CustomerBaseline} for all customers that have
        an active baseline. Customers without baselines are omitted.
    """
    if not customer_ids:
        return {}

    close_conn = conn is None
    if conn is None:
        conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT DISTINCT ON (customer_id) *
            FROM customer_baselines
            WHERE customer_id = ANY(%s::uuid[]) AND is_active = TRUE
            ORDER BY customer_id, computed_at DESC
        """, (customer_ids,))
        rows = cursor.fetchall()
        cursor.close()

        result: Dict[str, CustomerBaseline] = {}
        for row in rows:
            cid = str(row["customer_id"])
            result[cid] = CustomerBaseline(
                customer_id=cid,
                computed_at=row["computed_at"],
                window_days=int(row["window_days"]),
                history_start_date=str(row["history_start_date"]) if row["history_start_date"] else None,
                history_end_date=str(row["history_end_date"])     if row["history_end_date"]   else None,
                transaction_count=int(row["transaction_count"]),
                low_confidence=bool(row["low_confidence"]),
                feature_means=row["feature_means"] or {},
                feature_stds=row["feature_stds"]   or {},
                feature_p25=row["feature_p25"]     or {},
                feature_p75=row["feature_p75"]     or {},
                feature_p95=row["feature_p95"]     or {},
            )
        return result
    finally:
        if close_conn:
            conn.close()