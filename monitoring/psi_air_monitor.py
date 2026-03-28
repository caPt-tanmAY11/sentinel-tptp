"""
monitoring/psi_air_monitor.py
─────────────────────────────────────────────────────────────────────────────
PSI (Population Stability Index) + AIR (Adverse Impact Ratio) monitoring.

PSI:
  Measures how much a feature distribution has shifted between the baseline
  window (days 1-90) and the real-time window (recent 30 days).

  PSI formula: Σ (p_i - q_i) × ln(p_i / q_i)
  - PSI < 0.10  → STABLE
  - PSI 0.10-0.25 → WATCH
  - PSI > 0.25  → RETRAIN (alert)

AIR:
  Measures whether the model flags different demographic groups at
  disproportionately different rates (fairness check).

  AIR = high_risk_rate(group) / high_risk_rate(reference_group)
  - AIR < 0.80 → ALERT (group is flagged at < 80% the rate of reference)
  - AIR > 1.25 → ALERT (group is flagged at > 125% the rate of reference)
  - 0.80 ≤ AIR ≤ 1.25 → STABLE
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple

import numpy as np
import psycopg2
from psycopg2.extras import RealDictCursor

from config.settings import get_settings
from feature_engine.features import FEATURE_NAMES

settings = get_settings()


def _get_db():
    return psycopg2.connect(
        host=settings.POSTGRES_HOST, port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB, user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )


# ── PSI Core ──────────────────────────────────────────────────────────────────

def compute_psi(
    baseline_values: np.ndarray,
    current_values:  np.ndarray,
    n_bins: int = 10,
) -> float:
    """
    Compute Population Stability Index between two distributions.

    Args:
        baseline_values: Feature values from the baseline window
        current_values:  Feature values from the current production window
        n_bins:          Number of bins for discretisation

    Returns:
        PSI value (float). Higher = more drift.
    """
    eps = 1e-8

    # Use baseline to define bins (avoids data leakage)
    baseline_values = baseline_values[np.isfinite(baseline_values)]
    current_values  = current_values[np.isfinite(current_values)]

    if len(baseline_values) < 2 or len(current_values) < 2:
        return 0.0

    bins = np.percentile(baseline_values, np.linspace(0, 100, n_bins + 1))
    bins = np.unique(bins)

    if len(bins) < 2:
        return 0.0

    base_counts, _ = np.histogram(baseline_values, bins=bins)
    curr_counts, _ = np.histogram(current_values,  bins=bins)

    # Convert to proportions and add epsilon to avoid log(0)
    base_props = (base_counts / max(base_counts.sum(), 1)) + eps
    curr_props = (curr_counts / max(curr_counts.sum(), 1)) + eps

    base_props /= base_props.sum()
    curr_props /= curr_props.sum()

    psi = float(np.sum((curr_props - base_props) * np.log(curr_props / base_props)))
    return round(psi, 6)


def classify_psi(psi_value: float) -> str:
    """Classify PSI into STABLE / WATCH / RETRAIN."""
    if psi_value < 0.10:
        return "STABLE"
    elif psi_value < settings.MODEL_RETRAIN_PSI_THRESHOLD:
        return "WATCH"
    else:
        return "RETRAIN"


# ── Feature PSI Monitoring ────────────────────────────────────────────────────

def run_feature_psi_monitoring(conn=None) -> List[Dict[str, Any]]:
    """
    Compare feature distributions between baseline window and real-time window.

    Baseline window: feature_means stored in customer_baselines
    Real-time window: recent transaction_pulse_events.delta_features
    """
    close_conn = conn is None
    if conn is None:
        conn = _get_db()

    results = []

    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        now = datetime.now(timezone.utc)

        # ── Baseline distribution: feature means from all active baselines ──
        cursor.execute("""
            SELECT feature_means FROM customer_baselines
            WHERE is_active = TRUE
        """)
        baseline_rows = cursor.fetchall()

        if not baseline_rows:
            print("  ⚠ No baselines found — run --step baselines first")
            return []

        # Build per-feature arrays from baseline means
        baseline_feature_arrays: Dict[str, List[float]] = {f: [] for f in FEATURE_NAMES}
        for row in baseline_rows:
            fm = row["feature_means"] or {}
            for fname in FEATURE_NAMES:
                val = fm.get(fname)
                if val is not None and math.isfinite(float(val)):
                    baseline_feature_arrays[fname].append(float(val))

        # ── Current distribution: z-score deltas from recent pulse events ──
        # We use the delta_features (z-scores) from events in the last 30 days
        rt_start = now - timedelta(days=30)
        cursor.execute("""
            SELECT delta_features FROM transaction_pulse_events
            WHERE event_ts > %s
            LIMIT 5000
        """, (rt_start,))
        rt_rows = cursor.fetchall()

        if not rt_rows:
            print("  ⚠ No recent transaction_pulse_events — inject some transactions first")
            return []

        current_feature_arrays: Dict[str, List[float]] = {f: [] for f in FEATURE_NAMES}
        for row in rt_rows:
            df = row["delta_features"] or {}
            for fname in FEATURE_NAMES:
                val = df.get(fname)
                if val is not None and math.isfinite(float(val)):
                    current_feature_arrays[fname].append(float(val))

        # ── Compute PSI per feature ──────────────────────────────────────────
        for fname in FEATURE_NAMES:
            base_arr = np.array(baseline_feature_arrays[fname], dtype=np.float64)
            curr_arr = np.array(current_feature_arrays[fname],  dtype=np.float64)

            if len(base_arr) < 5 or len(curr_arr) < 5:
                continue

            psi_val = compute_psi(base_arr, curr_arr)
            status  = classify_psi(psi_val)

            results.append({
                "monitor_type": "PSI",
                "feature_name": fname,
                "metric_value": psi_val,
                "status":       status,
                "details": {
                    "baseline_n": len(base_arr),
                    "current_n":  len(curr_arr),
                    "baseline_mean": round(float(np.mean(base_arr)), 4),
                    "current_mean":  round(float(np.mean(curr_arr)), 4),
                },
            })

        cursor.close()

    finally:
        if close_conn:
            conn.close()

    return results


# ── Score Distribution PSI ────────────────────────────────────────────────────

def run_score_distribution_psi(conn=None) -> Dict[str, Any]:
    """
    Check if the overall pulse score distribution has drifted.
    Compares early scores (first 20% of history) vs recent scores.
    """
    close_conn = conn is None
    if conn is None:
        conn = _get_db()

    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT pulse_score, score_ts
            FROM pulse_scores
            ORDER BY score_ts ASC
        """)
        rows = cursor.fetchall()
        cursor.close()

        if len(rows) < 20:
            return {"monitor_type": "PSI", "feature_name": "pulse_score_distribution",
                    "metric_value": 0.0, "status": "STABLE",
                    "details": {"note": "Not enough score history yet"}}

        scores = [float(r["pulse_score"]) for r in rows]
        split  = max(1, len(scores) // 5)

        baseline_scores = np.array(scores[:split])
        current_scores  = np.array(scores[-split:])

        psi_val = compute_psi(baseline_scores, current_scores, n_bins=10)
        status  = classify_psi(psi_val)

        return {
            "monitor_type": "PSI",
            "feature_name": "pulse_score_distribution",
            "metric_value": psi_val,
            "status":       status,
            "details": {
                "baseline_mean": round(float(np.mean(baseline_scores)), 4),
                "current_mean":  round(float(np.mean(current_scores)), 4),
                "baseline_n":    len(baseline_scores),
                "current_n":     len(current_scores),
            },
        }

    finally:
        if close_conn:
            conn.close()


# ── Severity Distribution PSI ─────────────────────────────────────────────────

def run_severity_distribution_psi(conn=None) -> Dict[str, Any]:
    """
    Check if the transaction severity distribution has shifted.
    A sudden spike (many txns scoring > 0.80) may indicate data drift
    or a real portfolio-wide stress event.
    """
    close_conn = conn is None
    if conn is None:
        conn = _get_db()

    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        now    = datetime.now(timezone.utc)

        cursor.execute("""
            SELECT txn_severity FROM transaction_pulse_events
            WHERE event_ts > %s - INTERVAL '60 days'
            ORDER BY event_ts ASC
            LIMIT 10000
        """, (now,))
        rows = cursor.fetchall()
        cursor.close()

        if len(rows) < 20:
            return {"monitor_type": "PSI", "feature_name": "severity_distribution",
                    "metric_value": 0.0, "status": "STABLE",
                    "details": {"note": "Not enough events yet"}}

        severities = [float(r["txn_severity"]) for r in rows]
        split      = max(1, len(severities) // 2)

        baseline_sev = np.array(severities[:split])
        current_sev  = np.array(severities[split:])

        psi_val = compute_psi(baseline_sev, current_sev, n_bins=10)
        status  = classify_psi(psi_val)

        high_sev_pct = sum(1 for s in severities[split:] if s >= 0.80) / len(severities[split:]) * 100

        return {
            "monitor_type": "PSI",
            "feature_name": "severity_distribution",
            "metric_value": psi_val,
            "status":       "ALERT" if high_sev_pct > 40 else status,
            "details": {
                "high_severity_pct_recent": round(high_sev_pct, 2),
                "recent_mean_severity":     round(float(np.mean(current_sev)), 4),
                "baseline_mean_severity":   round(float(np.mean(baseline_sev)), 4),
            },
        }

    finally:
        if close_conn:
            conn.close()


# ── AIR (Adverse Impact Ratio) Monitoring ─────────────────────────────────────

def run_air_monitoring(conn=None) -> List[Dict[str, Any]]:
    """
    Adverse Impact Ratio fairness check.

    Compares the rate at which each group is classified as HIGH or CRITICAL risk.
    Groups: geography_risk_tier (1-4) and customer_segment.

    Reference group: lowest-risk tier / largest segment.
    AIR = group_high_risk_rate / reference_high_risk_rate

    0.80 ≤ AIR ≤ 1.25 → STABLE (within 80/125 rule)
    AIR < 0.80 or > 1.25 → ALERT
    """
    close_conn = conn is None
    if conn is None:
        conn = _get_db()

    results = []

    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        high_risk_threshold = settings.RISK_TIER_HIGH  # 0.55

        # ── AIR by geography_risk_tier ────────────────────────────────────────
        cursor.execute("""
            SELECT
                c.geography_risk_tier,
                COUNT(DISTINCT c.customer_id)                                   AS total_customers,
                COUNT(DISTINCT CASE WHEN ps.pulse_score >= %s
                                    THEN c.customer_id END)                     AS high_risk_customers
            FROM customers c
            LEFT JOIN (
                SELECT DISTINCT ON (customer_id)
                    customer_id, pulse_score
                FROM pulse_scores
                ORDER BY customer_id, score_ts DESC
            ) ps ON ps.customer_id = c.customer_id
            GROUP BY c.geography_risk_tier
            ORDER BY c.geography_risk_tier
        """, (high_risk_threshold,))
        geo_rows = cursor.fetchall()

        if geo_rows:
            # Reference: tier 1 (lowest geographic risk)
            ref_row  = next((r for r in geo_rows if r["geography_risk_tier"] == 1), geo_rows[0])
            ref_rate = float(ref_row["high_risk_customers"]) / max(float(ref_row["total_customers"]), 1)

            for row in geo_rows:
                if not row["geography_risk_tier"]:
                    continue
                total     = int(row["total_customers"])
                high_risk = int(row["high_risk_customers"] or 0)
                group_rate = high_risk / max(total, 1)
                air        = round(group_rate / max(ref_rate, 0.001), 4)
                status     = "STABLE" if 0.80 <= air <= 1.25 else "ALERT"
                if ref_rate < 0.01:
                    status = "STABLE"  # reference group has too few cases to evaluate

                results.append({
                    "monitor_type": "AIR",
                    "feature_name": f"geo_tier_{row['geography_risk_tier']}",
                    "metric_value": air,
                    "status":       status,
                    "details": {
                        "group":            f"geo_tier_{row['geography_risk_tier']}",
                        "total_customers":  total,
                        "high_risk_count":  high_risk,
                        "high_risk_rate":   round(group_rate, 4),
                        "reference_rate":   round(ref_rate, 4),
                        "air":              air,
                    },
                })

        # ── AIR by customer_segment ───────────────────────────────────────────
        cursor.execute("""
            SELECT
                c.customer_segment,
                COUNT(DISTINCT c.customer_id)                                   AS total_customers,
                COUNT(DISTINCT CASE WHEN ps.pulse_score >= %s
                                    THEN c.customer_id END)                     AS high_risk_customers
            FROM customers c
            LEFT JOIN (
                SELECT DISTINCT ON (customer_id)
                    customer_id, pulse_score
                FROM pulse_scores
                ORDER BY customer_id, score_ts DESC
            ) ps ON ps.customer_id = c.customer_id
            GROUP BY c.customer_segment
            ORDER BY total_customers DESC
        """, (high_risk_threshold,))
        seg_rows = cursor.fetchall()

        if seg_rows:
            # Reference: RETAIL (largest segment)
            ref_row  = next((r for r in seg_rows if r["customer_segment"] == "RETAIL"), seg_rows[0])
            ref_rate = float(ref_row["high_risk_customers"]) / max(float(ref_row["total_customers"]), 1)

            for row in seg_rows:
                total     = int(row["total_customers"])
                high_risk = int(row["high_risk_customers"] or 0)
                group_rate = high_risk / max(total, 1)
                air        = round(group_rate / max(ref_rate, 0.001), 4)
                status     = "STABLE" if 0.80 <= air <= 1.25 else "ALERT"
                if ref_rate < 0.01:
                    status = "STABLE"

                results.append({
                    "monitor_type": "AIR",
                    "feature_name": f"segment_{row['customer_segment']}",
                    "metric_value": air,
                    "status":       status,
                    "details": {
                        "group":           row["customer_segment"],
                        "total_customers": total,
                        "high_risk_count": high_risk,
                        "high_risk_rate":  round(group_rate, 4),
                        "reference_rate":  round(ref_rate, 4),
                        "air":             air,
                    },
                })

        cursor.close()

    finally:
        if close_conn:
            conn.close()

    return results


# ── Persist results to DB ─────────────────────────────────────────────────────

def save_monitoring_results(results: List[Dict[str, Any]], conn=None) -> None:
    """Write monitoring results to model_monitoring table."""
    if not results:
        return

    close_conn = conn is None
    if conn is None:
        conn = _get_db()

    try:
        cursor = conn.cursor()
        for r in results:
            cursor.execute("""
                INSERT INTO model_monitoring
                    (monitor_type, feature_name, metric_value, status, details)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                r["monitor_type"],
                r.get("feature_name", ""),
                r.get("metric_value", 0.0),
                r.get("status", "STABLE"),
                json.dumps(r.get("details", {})),
            ))
        conn.commit()
        cursor.close()
    finally:
        if close_conn:
            conn.close()


# ── Full Monitoring Run ───────────────────────────────────────────────────────

def run_all_monitoring(conn=None) -> Dict[str, Any]:
    """
    Run all monitoring checks and return a summary.
    Saves results to model_monitoring table.
    """
    import time
    start = time.time()

    print("  Running PSI feature monitoring...")
    feature_results = run_feature_psi_monitoring(conn=conn)

    print("  Running score distribution PSI...")
    score_psi = run_score_distribution_psi(conn=conn)

    print("  Running severity distribution PSI...")
    severity_psi = run_severity_distribution_psi(conn=conn)

    print("  Running AIR fairness monitoring...")
    air_results = run_air_monitoring(conn=conn)

    all_results = feature_results + [score_psi, severity_psi] + air_results

    # Persist to DB
    save_monitoring_results(all_results, conn=conn)

    # Build summary
    psi_statuses  = [r["status"] for r in feature_results]
    air_statuses  = [r["status"] for r in air_results]

    retrain_needed = "RETRAIN" in psi_statuses
    alerts         = psi_statuses.count("RETRAIN") + psi_statuses.count("WATCH")
    air_alerts     = air_statuses.count("ALERT")

    # Find most drifted features
    top_drifted = sorted(
        [r for r in feature_results if r["status"] != "STABLE"],
        key=lambda r: r["metric_value"],
        reverse=True,
    )[:5]

    summary = {
        "run_at":           datetime.now(timezone.utc).isoformat(),
        "elapsed_s":        round(time.time() - start, 2),
        "total_features":   len(feature_results),
        "stable_features":  psi_statuses.count("STABLE"),
        "watch_features":   psi_statuses.count("WATCH"),
        "retrain_features": psi_statuses.count("RETRAIN"),
        "retrain_needed":   retrain_needed,
        "air_alerts":       air_alerts,
        "score_psi":        score_psi,
        "severity_psi":     severity_psi,
        "top_drifted":      top_drifted,
        "air_results":      air_results,
    }

    return summary
if __name__ == "__main__":
    print("🚀 Starting PSI + AIR Monitoring...\n")

    summary = run_all_monitoring()

    print("\n✅ Monitoring Summary:\n")
    print(json.dumps(summary, indent=2))