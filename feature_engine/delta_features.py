"""
feature_engine/delta_features.py
─────────────────────────────────────────────────────────────────────────────
Computes the 48-dimensional input vector for the PulseScorer model.

Given a new real-time transaction and the customer's stored baseline,
produces:
  - 42 z-score deltas (current feature value vs baseline mean/std)
  - 6 transaction-specific features

The model sees ONLY these 48 numbers. It never sees raw labels.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, Any, List

from baseline.baseline_schema import CustomerBaseline
from enrichment.transaction_category import TransactionCategory
from feature_engine.features import FEATURE_NAMES


# ── Transaction-specific feature names (appended after the 42 z-scores) ──────
TXN_FEATURE_NAMES: List[str] = [
    "inferred_category_encoded",    # 0-14 ordinal encoding of category
    "amount_vs_baseline_ratio",     # amount / customer's avg daily spend
    "time_of_day_risk",             # 0=day(9-18h)  1=evening(18-22h)  2=night(22-9h)
    "day_of_month_risk",            # proximity to EMI due dates [0.0-1.0]
    "balance_depletion_pct",        # fraction of balance_before consumed
    "is_failed",                    # 1.0 if payment_status == 'failed'/'reversed'
]

DELTA_FEATURE_NAMES: List[str] = FEATURE_NAMES + TXN_FEATURE_NAMES
assert len(DELTA_FEATURE_NAMES) == 48

# Ordinal encoding for categories (stable — never reorder)
CATEGORY_ENCODING: Dict[str, int] = {
    "SALARY_CREDIT":      0,
    "EMI_DEBIT":          1,
    "FAILED_EMI_DEBIT":   2,
    "LENDING_APP_DEBIT":  3,
    "LENDING_APP_CREDIT": 4,
    "UTILITY_PAYMENT":    5,
    "ATM_WITHDRAWAL":     6,
    "GROCERY":            7,
    "FOOD_DELIVERY":      8,
    "FUEL":               9,
    "ECOMMERCE":          10,
    "OTT":                11,
    "GENERAL_DEBIT":      12,
    "GENERAL_CREDIT":     13,
    "UNKNOWN":            14,
}


def compute_delta_features(
    current_features: Dict[str, float],
    baseline: CustomerBaseline,
    transaction: Dict[str, Any],
    category: TransactionCategory,
) -> Dict[str, float]:
    """
    Compute the 48-dimensional input vector for PulseScorer.

    Args:
        current_features: 42 feature values computed as of transaction timestamp
        baseline:         Customer's stored statistical baseline (days 1-90)
        transaction:      Raw transaction dict from the transactions table
        category:         Classifier output for this transaction

    Returns:
        Dict of {feature_name: float} with exactly 48 entries in DELTA_FEATURE_NAMES order.
    """
    delta: Dict[str, float] = {}

    # ── Part 1: 42 z-score deltas ─────────────────────────────────────────────
    for fname in FEATURE_NAMES:
        current_val = current_features.get(fname, 0.0)
        delta[fname] = baseline.z_score(fname, current_val)

    # ── Part 2: 6 transaction-specific features ───────────────────────────────

    # 1. Category encoding
    delta["inferred_category_encoded"] = float(
        CATEGORY_ENCODING.get(category.category, 14)
    )

    # 2. Amount vs baseline ratio (how large is this txn vs customer's normal?)
    avg_daily = baseline.feature_means.get("total_debit_30d", 0.0) / 30.0
    amount = float(transaction.get("amount", 0.0))
    if avg_daily > 1.0:
        ratio = amount / avg_daily
    else:
        bal_mean = baseline.feature_means.get("balance_7d_avg", 1.0)
        daily_from_bal = bal_mean / 30.0 if bal_mean > 0 else 1.0
        ratio = amount / max(daily_from_bal, 1.0)
    delta["amount_vs_baseline_ratio"] = round(min(ratio, 50.0), 4)

    # 3. Time of day risk
    txn_ts = transaction.get("txn_timestamp")
    if isinstance(txn_ts, str):
        try:
            txn_ts = datetime.fromisoformat(txn_ts.replace("Z", "+00:00"))
        except Exception:
            txn_ts = None
    hour = txn_ts.hour if (txn_ts and hasattr(txn_ts, "hour")) else 12
    if 9 <= hour < 18:
        time_risk = 0.0
    elif 18 <= hour < 22:
        time_risk = 1.0
    else:
        time_risk = 2.0
    delta["time_of_day_risk"] = time_risk

    # 4. Day of month risk (proximity to EMI due dates)
    dom = txn_ts.day if (txn_ts and hasattr(txn_ts, "day")) else 15
    emi_dates = [1, 5, 7, 10, 15, 20, 25, 28]
    min_dist = min(abs(dom - d) for d in emi_dates)
    delta["day_of_month_risk"] = round(max(0.0, 1.0 - min_dist / 5.0), 4)

    # 5. Balance depletion %
    bb = transaction.get("balance_before")
    if bb is not None and float(bb) > 0 and category.is_debit:
        delta["balance_depletion_pct"] = round(min(amount / float(bb), 2.0), 4)
    else:
        delta["balance_depletion_pct"] = 0.0

    # 6. Is failed
    status = str(transaction.get("payment_status", "success")).lower()
    delta["is_failed"] = 1.0 if status in ("failed", "reversed") else 0.0

    # ── Sanitise ──────────────────────────────────────────────────────────────
    return {
        k: 0.0 if (v is None or not math.isfinite(float(v))) else round(float(v), 6)
        for k, v in delta.items()
    }