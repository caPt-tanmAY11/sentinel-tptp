"""
feature_engine/features.py
─────────────────────────────────────────────────────────────────────────────
Computes all 42 behavioural features for a customer at a given point in time.

DESIGN:
  - NO transaction_type queries — uses classifier on raw VPA/platform data
  - Single bulk transaction fetch per call (not N+1 queries)
  - as_of parameter strictly enforced — never reads beyond it
  - Safe for both baseline computation and real-time scoring

Feature groups (42 total):
  Group 1: Balance & Liquidity        (6)
  Group 2: Income / Salary            (5)
  Group 3: EMI / NACH Payments        (6)
  Group 4: ATM / Cash                 (4)
  Group 5: Lending App Activity       (4)
  Group 6: Spending Behaviour         (8)
  Group 7: Cross-product & Context    (9)
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

import numpy as np
import psycopg2
from psycopg2.extras import RealDictCursor

from config.settings import get_settings
from enrichment.transaction_classifier import classify_transaction

settings = get_settings()

FEATURE_NAMES: List[str] = [
    # Group 1: Balance & Liquidity (6)
    "balance_7d_avg", "balance_wow_change_pct", "balance_mom_change_pct",
    "net_cash_flow_7d", "liquidity_buffer_days", "balance_depletion_rate",
    # Group 2: Income / Salary (5)
    "salary_credit_count_90d", "salary_delay_days", "salary_amount_deviation_pct",
    "income_irregularity", "partial_salary_flag",
    # Group 3: EMI / NACH Payments (6)
    "failed_nach_count_30d", "total_nach_count_30d", "nach_failure_rate",
    "emi_payment_delay_days", "consecutive_failed_nach", "bounce_count_30d",
    # Group 4: ATM / Cash (4)
    "atm_withdrawal_amount_7d", "atm_withdrawal_count_7d",
    "atm_amount_30d", "atm_frequency_trend",
    # Group 5: Lending App Activity (4)
    "lending_app_transfer_count_30d", "lending_app_transfer_amount_30d",
    "lending_disbursement_count_30d", "lending_app_dependency_score",
    # Group 5b: Investment Activity (2)
    "investment_debit_count_30d", "investment_debit_amount_30d",
    # Group 6: Spending Behaviour (8)
    "discretionary_spend_7d", "grocery_spend_7d", "discretionary_wow_change_pct",
    "food_delivery_spend_7d", "online_spend_7d", "total_debit_30d",
    "spending_velocity_7d", "large_debit_flag",
    # Group 7: Cross-product & Context (9)
    "total_outstanding_debt", "debt_to_income_ratio", "emi_to_income_ratio",
    "credit_utilization_pct", "active_product_count", "historical_delinquency_count",
    "customer_vintage_months", "geography_risk_tier", "inflow_outflow_ratio_30d",
]

assert len(FEATURE_NAMES) == 44


def _get_db():
    return psycopg2.connect(
        host=settings.POSTGRES_HOST, port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB, user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )


def _safe_div(num: float, denom: float, default: float = 0.0) -> float:
    if denom == 0 or not math.isfinite(denom):
        return default
    result = num / denom
    return result if math.isfinite(result) else default


def compute_all_features(
    customer_id: str,
    as_of: datetime,
    conn=None,
) -> Dict[str, float]:
    """
    Compute all 42 features for a customer as of a given datetime.
    Only reads transactions in the 90-day window ending at as_of.

    Args:
        customer_id: UUID string
        as_of:       Hard upper bound — no transaction after this is read.
        conn:        Optional existing psycopg2 connection (reused for batching).

    Returns:
        Dict of {feature_name: float} for all 42 features.
        All missing/invalid values return 0.0.
    """
    close_conn = conn is None
    if conn is None:
        conn = _get_db()

    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT monthly_income, expected_salary_day, customer_vintage_months,
                   historical_delinquency_count, geography_risk_tier, account_number
            FROM customers WHERE customer_id = %s
        """, (customer_id,))
        cust = cursor.fetchone()
        if not cust:
            return {f: 0.0 for f in FEATURE_NAMES}

        monthly_income   = float(cust["monthly_income"] or 1)
        expected_sal_day = int(cust["expected_salary_day"] or 5)
        account_number   = cust["account_number"] or ""

        # Single bulk fetch — all transactions in 90-day window up to as_of
        window_start = as_of - timedelta(days=90)
        cursor.execute("""
            SELECT sender_id, sender_name, receiver_id, receiver_name,
                   amount, platform, payment_status,
                   balance_before, balance_after, txn_timestamp
            FROM transactions
            WHERE customer_id = %s
              AND txn_timestamp > %s
              AND txn_timestamp <= %s
            ORDER BY txn_timestamp ASC
        """, (customer_id, window_start, as_of))
        raw_rows = cursor.fetchall()

        # Classify each transaction in Python (no extra DB calls)
        txns = []
        for r in raw_rows:
            cat = classify_transaction(dict(r), account_number)
            txns.append({
                "ts":            r["txn_timestamp"],
                "amount":        float(r["amount"] or 0),
                "platform":      r["platform"] or "",
                "status":        r["payment_status"] or "success",
                "balance_after": float(r["balance_after"])  if r["balance_after"]  is not None else None,
                "balance_before":float(r["balance_before"]) if r["balance_before"] is not None else None,
                "receiver_id":   r["receiver_id"] or "",
                "sender_id":     r["sender_id"]   or "",
                "category":      cat.category,
                "is_debit":      cat.is_debit,
                "is_credit":     not cat.is_debit,
            })

        # Time window boundaries
        t7  = as_of - timedelta(days=7)
        t14 = as_of - timedelta(days=14)
        t15 = as_of - timedelta(days=15)
        t30 = as_of - timedelta(days=30)
        t60 = as_of - timedelta(days=60)
        t90 = as_of - timedelta(days=90)

        def W(start, end=None, cat=None, status=None, debit=None, credit=None):
            """Filter transactions by window and optional criteria."""
            end = end or as_of
            r = [t for t in txns if start < t["ts"] <= end]
            if cat:
                cats = [cat] if isinstance(cat, str) else cat
                r = [t for t in r if t["category"] in cats]
            if status:
                r = [t for t in r if t["status"] == status]
            if debit  is not None: r = [t for t in r if t["is_debit"]  == debit]
            if credit is not None: r = [t for t in r if t["is_credit"] == credit]
            return r

        # ── GROUP 1: Balance & Liquidity ──────────────────────────────────────
        b7  = [t["balance_after"] for t in W(t7)       if t["balance_after"] is not None]
        bp7 = [t["balance_after"] for t in W(t14, t7)  if t["balance_after"] is not None]
        b30 = [t["balance_after"] for t in W(t30)      if t["balance_after"] is not None]
        bp30= [t["balance_after"] for t in W(t60, t30) if t["balance_after"] is not None]

        ba7  = float(np.mean(b7))   if b7  else 0.0
        bp7a = float(np.mean(bp7))  if bp7 else ba7
        ba30 = float(np.mean(b30))  if b30 else ba7
        bp30a= float(np.mean(bp30)) if bp30 else ba30

        balance_7d_avg           = round(ba7, 2)
        balance_wow_change_pct   = round(_safe_div((ba7 - bp7a),   abs(bp7a)  + 1) * 100, 2)
        balance_mom_change_pct   = round(_safe_div((ba30 - bp30a), abs(bp30a) + 1) * 100, 2)

        cr7 = sum(t["amount"] for t in W(t7, status="success", credit=True))
        db7 = sum(t["amount"] for t in W(t7, status="success", debit=True))
        net_cash_flow_7d         = round(cr7 - db7, 2)

        db30_all  = W(t30, status="success", debit=True)
        avg_daily = _safe_div(sum(t["amount"] for t in db30_all), 30, default=1)
        liquidity_buffer_days    = round(_safe_div(ba7, avg_daily), 2)

        bal_slope = 0.0
        if len(b30) >= 2:
            bal_slope = _safe_div(b30[0] - b30[-1], max(monthly_income, 1))
        balance_depletion_rate   = round(max(0.0, bal_slope), 4)

        # ── GROUP 2: Income / Salary ───────────────────────────────────────────
        sal90 = W(t90, cat="SALARY_CREDIT", status="success")
        salary_credit_count_90d  = float(len(sal90))

        salary_delay_days = 0.0
        if sal90:
            latest = sal90[-1]
            delay  = latest["ts"].day - expected_sal_day
            if delay < -15: delay += 30
            salary_delay_days = float(max(0, delay))

        sal_amts = [t["amount"] for t in sal90]
        salary_amount_deviation_pct = 0.0
        if len(sal_amts) >= 2:
            avg_s = float(np.mean(sal_amts[:-1]))
            salary_amount_deviation_pct = round(_safe_div(sal_amts[-1] - avg_s, avg_s) * 100, 2)

        income_irregularity = 0.0
        if len(sal90) >= 3:
            days = sorted([t["ts"].day for t in sal90])
            gaps = [days[i+1] - days[i] for i in range(len(days)-1)]
            gaps = [g + 30 if g < 0 else g for g in gaps]
            income_irregularity = round(_safe_div(float(np.std(gaps)), float(np.mean(gaps)) + 1), 4)

        partial_salary_flag = 0.0
        if len(sal_amts) >= 2:
            avg_s = float(np.mean(sal_amts[:-1]))
            partial_salary_flag = 1.0 if sal_amts[-1] < 0.80 * avg_s else 0.0

        # ── GROUP 3: EMI / NACH ────────────────────────────────────────────────
        nach_all    = W(t30, cat=["EMI_DEBIT", "FAILED_EMI_DEBIT"])
        nach_failed = [t for t in nach_all if t["category"] == "FAILED_EMI_DEBIT"]
        nach_ok     = [t for t in nach_all if t["category"] == "EMI_DEBIT"]

        failed_nach_count_30d = float(len(nach_failed))
        total_nach_count_30d  = float(len(nach_all))
        nach_failure_rate     = round(_safe_div(failed_nach_count_30d, total_nach_count_30d), 4)

        emi_payment_delay_days = 0.0
        if nach_ok:
            due_cands = [5, 10, 15, 20, 25, 28]
            delays = []
            for t in nach_ok:
                nd = min(due_cands, key=lambda d: abs(d - t["ts"].day))
                dl = t["ts"].day - nd
                if dl < -15: dl += 30
                delays.append(max(0, dl))
            emi_payment_delay_days = round(float(np.mean(delays)), 2) if delays else 0.0

        consecutive_failed_nach = 0.0
        if nach_all:
            streak = max_s = 0
            for t in sorted(nach_all, key=lambda x: x["ts"]):
                if t["category"] == "FAILED_EMI_DEBIT":
                    streak += 1; max_s = max(max_s, streak)
                else:
                    streak = 0
            consecutive_failed_nach = float(max_s)

        bounce_count_30d = float(len([t for t in W(t30) if t["status"] == "failed"]))

        # ── GROUP 4: ATM / Cash ────────────────────────────────────────────────
        atm7    = W(t7,  cat="ATM_WITHDRAWAL", status="success")
        atm30   = W(t30, cat="ATM_WITHDRAWAL", status="success")
        atm15r  = W(t15, cat="ATM_WITHDRAWAL", status="success")
        atm15p  = W(t30, t15, cat="ATM_WITHDRAWAL", status="success")

        atm_withdrawal_amount_7d = round(sum(t["amount"] for t in atm7), 2)
        atm_withdrawal_count_7d  = float(len(atm7))
        atm_amount_30d           = round(sum(t["amount"] for t in atm30), 2)
        atm_frequency_trend      = round(_safe_div(len(atm15r) - len(atm15p), len(atm15p) + 1), 4)

        # ── GROUP 5: Lending App ───────────────────────────────────────────────
        lend_d = W(t30, cat="LENDING_APP_DEBIT",  status="success")
        lend_c = W(t30, cat="LENDING_APP_CREDIT", status="success")

        lending_app_transfer_count_30d  = float(len(lend_d))
        lending_app_transfer_amount_30d = round(sum(t["amount"] for t in lend_d), 2)
        lending_disbursement_count_30d  = float(len(lend_c))
        lending_app_dependency_score    = round(_safe_div(lending_app_transfer_amount_30d, monthly_income), 4)

        # ── GROUP 5b: Investment Activity ──────────────────────────────────────
        inv_d = W(t30, cat="INVESTMENT_DEBIT", status="success")
        investment_debit_count_30d  = float(len(inv_d))
        investment_debit_amount_30d = round(sum(t["amount"] for t in inv_d), 2)

        # ── GROUP 6: Spending ──────────────────────────────────────────────────
        disc_cats = ["FOOD_DELIVERY", "ECOMMERCE", "OTT"]
        disc7  = W(t7,  cat=disc_cats, status="success")
        discp7 = W(t14, t7, cat=disc_cats, status="success")
        groc7  = W(t7,  cat="GROCERY",       status="success")
        food7  = W(t7,  cat="FOOD_DELIVERY", status="success")
        onl7   = W(t7,  status="success", debit=True)

        discretionary_spend_7d       = round(sum(t["amount"] for t in disc7), 2)
        grocery_spend_7d             = round(sum(t["amount"] for t in groc7), 2)
        food_delivery_spend_7d       = round(sum(t["amount"] for t in food7), 2)
        online_spend_7d              = round(sum(t["amount"] for t in onl7), 2)
        disc_prev                    = sum(t["amount"] for t in discp7)
        discretionary_wow_change_pct = round(_safe_div(discretionary_spend_7d - disc_prev, disc_prev + 1) * 100, 2)
        total_debit_30d              = round(sum(t["amount"] for t in db30_all), 2)
        spending_velocity_7d         = round(_safe_div(len(W(t7)), 7), 4)

        large_debit_flag = 0.0
        if avg_daily > 0:
            for t in W(t7, status="success", debit=True):
                if t["amount"] > 2 * avg_daily:
                    large_debit_flag = 1.0
                    break

        # ── GROUP 7: Cross-product & Context ──────────────────────────────────
        cursor.execute("""
            SELECT COALESCE(SUM(outstanding_principal),0) debt,
                   COALESCE(SUM(emi_amount),0) emi,
                   COUNT(*) loans
            FROM loans WHERE customer_id = %s AND status = 'ACTIVE'
        """, (customer_id,))
        lr = cursor.fetchone()
        total_outstanding_debt = float(lr["debt"]  or 0)
        total_emi              = float(lr["emi"]   or 0)
        active_loan_count      = int(lr["loans"]   or 0)

        cursor.execute("""
            SELECT COALESCE(AVG(credit_utilization_pct),0) util, COUNT(*) cards
            FROM credit_cards WHERE customer_id = %s AND status = 'ACTIVE'
        """, (customer_id,))
        cr = cursor.fetchone()
        credit_utilization_pct = float(cr["util"]  or 0)
        active_card_count      = int(cr["cards"]   or 0)

        cursor.close()

        debt_to_income_ratio   = round(_safe_div(total_outstanding_debt, monthly_income * 12), 4)
        emi_to_income_ratio    = round(_safe_div(total_emi, monthly_income), 4)
        active_product_count   = float(active_loan_count + active_card_count)

        cr30  = sum(t["amount"] for t in W(t30, status="success", credit=True))
        db30a = sum(t["amount"] for t in W(t30, status="success", debit=True))
        inflow_outflow_ratio_30d = round(_safe_div(cr30, db30a + 1), 4)

        features = {
            "balance_7d_avg": balance_7d_avg,
            "balance_wow_change_pct": balance_wow_change_pct,
            "balance_mom_change_pct": balance_mom_change_pct,
            "net_cash_flow_7d": net_cash_flow_7d,
            "liquidity_buffer_days": liquidity_buffer_days,
            "balance_depletion_rate": balance_depletion_rate,
            "salary_credit_count_90d": salary_credit_count_90d,
            "salary_delay_days": salary_delay_days,
            "salary_amount_deviation_pct": salary_amount_deviation_pct,
            "income_irregularity": income_irregularity,
            "partial_salary_flag": partial_salary_flag,
            "failed_nach_count_30d": failed_nach_count_30d,
            "total_nach_count_30d": total_nach_count_30d,
            "nach_failure_rate": nach_failure_rate,
            "emi_payment_delay_days": emi_payment_delay_days,
            "consecutive_failed_nach": consecutive_failed_nach,
            "bounce_count_30d": bounce_count_30d,
            "atm_withdrawal_amount_7d": atm_withdrawal_amount_7d,
            "atm_withdrawal_count_7d": atm_withdrawal_count_7d,
            "atm_amount_30d": atm_amount_30d,
            "atm_frequency_trend": atm_frequency_trend,
            "lending_app_transfer_count_30d": lending_app_transfer_count_30d,
            "lending_app_transfer_amount_30d": lending_app_transfer_amount_30d,
            "lending_disbursement_count_30d": lending_disbursement_count_30d,
            "lending_app_dependency_score": lending_app_dependency_score,
            "investment_debit_count_30d": investment_debit_count_30d,
            "investment_debit_amount_30d": investment_debit_amount_30d,
            "discretionary_spend_7d": discretionary_spend_7d,
            "grocery_spend_7d": grocery_spend_7d,
            "discretionary_wow_change_pct": discretionary_wow_change_pct,
            "food_delivery_spend_7d": food_delivery_spend_7d,
            "online_spend_7d": online_spend_7d,
            "total_debit_30d": total_debit_30d,
            "spending_velocity_7d": spending_velocity_7d,
            "large_debit_flag": large_debit_flag,
            "total_outstanding_debt": round(total_outstanding_debt, 2),
            "debt_to_income_ratio": debt_to_income_ratio,
            "emi_to_income_ratio": emi_to_income_ratio,
            "credit_utilization_pct": round(credit_utilization_pct, 2),
            "active_product_count": active_product_count,
            "historical_delinquency_count": float(cust["historical_delinquency_count"] or 0),
            "customer_vintage_months": float(cust["customer_vintage_months"] or 0),
            "geography_risk_tier": float(cust["geography_risk_tier"] or 2),
            "inflow_outflow_ratio_30d": inflow_outflow_ratio_30d,
        }

        # Sanitise: replace any NaN/Inf with 0.0
        return {
            k: 0.0 if (v is None or not math.isfinite(float(v))) else round(float(v), 6)
            for k, v in features.items()
        }

    finally:
        if close_conn:
            conn.close()


# ── In-memory variant (no DB queries) ─────────────────────────────────────────

def compute_all_features_from_data(
    customer_info: Dict[str, Any],
    all_customer_txns: list,
    loans_agg: Dict[str, Any],
    cards_agg: Dict[str, Any],
    as_of: datetime,
    account_number: str = "",
) -> Dict[str, float]:
    """
    Compute all 42 features for a customer using pre-fetched data.

    Identical logic to compute_all_features() but takes pre-fetched data
    instead of querying the database, enabling batch optimisation.

    Args:
        customer_info:     Dict with monthly_income, expected_salary_day,
                           customer_vintage_months, historical_delinquency_count,
                           geography_risk_tier.
        all_customer_txns: ALL transactions for this customer (will be filtered
                           to the 90-day window ending at as_of).
        loans_agg:         Pre-aggregated loans: {debt, emi, loans}.
        cards_agg:         Pre-aggregated credit cards: {util, cards}.
        as_of:             Hard upper bound — no transaction after this is used.
        account_number:    Customer's account number for classifier.

    Returns:
        Dict of {feature_name: float} for all 42 features.
    """
    monthly_income   = float(customer_info.get("monthly_income") or 1)
    expected_sal_day = int(customer_info.get("expected_salary_day") or 5)

    # Filter to 90-day window ending at as_of
    window_start = as_of - timedelta(days=90)
    raw_rows = [
        t for t in all_customer_txns
        if window_start < t["txn_timestamp"] <= as_of
    ]

    # Classify each transaction in Python
    txns = []
    for r in raw_rows:
        cat = classify_transaction(dict(r), account_number)
        txns.append({
            "ts":            r["txn_timestamp"],
            "amount":        float(r["amount"] or 0),
            "platform":      r["platform"] or "",
            "status":        r["payment_status"] or "success",
            "balance_after": float(r["balance_after"])  if r["balance_after"]  is not None else None,
            "balance_before":float(r["balance_before"]) if r["balance_before"] is not None else None,
            "receiver_id":   r["receiver_id"] or "",
            "sender_id":     r["sender_id"]   or "",
            "category":      cat.category,
            "is_debit":      cat.is_debit,
            "is_credit":     not cat.is_debit,
        })

    # Time window boundaries
    t7  = as_of - timedelta(days=7)
    t14 = as_of - timedelta(days=14)
    t15 = as_of - timedelta(days=15)
    t30 = as_of - timedelta(days=30)
    t60 = as_of - timedelta(days=60)
    t90 = as_of - timedelta(days=90)

    def W(start, end=None, cat=None, status=None, debit=None, credit=None):
        """Filter transactions by window and optional criteria."""
        end = end or as_of
        r = [t for t in txns if start < t["ts"] <= end]
        if cat:
            cats = [cat] if isinstance(cat, str) else cat
            r = [t for t in r if t["category"] in cats]
        if status:
            r = [t for t in r if t["status"] == status]
        if debit  is not None: r = [t for t in r if t["is_debit"]  == debit]
        if credit is not None: r = [t for t in r if t["is_credit"] == credit]
        return r

    # ── GROUP 1: Balance & Liquidity ──────────────────────────────────────
    b7  = [t["balance_after"] for t in W(t7)       if t["balance_after"] is not None]
    bp7 = [t["balance_after"] for t in W(t14, t7)  if t["balance_after"] is not None]
    b30 = [t["balance_after"] for t in W(t30)      if t["balance_after"] is not None]
    bp30= [t["balance_after"] for t in W(t60, t30) if t["balance_after"] is not None]

    ba7  = float(np.mean(b7))   if b7  else 0.0
    bp7a = float(np.mean(bp7))  if bp7 else ba7
    ba30 = float(np.mean(b30))  if b30 else ba7
    bp30a= float(np.mean(bp30)) if bp30 else ba30

    balance_7d_avg           = round(ba7, 2)
    balance_wow_change_pct   = round(_safe_div((ba7 - bp7a),   abs(bp7a)  + 1) * 100, 2)
    balance_mom_change_pct   = round(_safe_div((ba30 - bp30a), abs(bp30a) + 1) * 100, 2)

    cr7 = sum(t["amount"] for t in W(t7, status="success", credit=True))
    db7 = sum(t["amount"] for t in W(t7, status="success", debit=True))
    net_cash_flow_7d         = round(cr7 - db7, 2)

    db30_all  = W(t30, status="success", debit=True)
    avg_daily = _safe_div(sum(t["amount"] for t in db30_all), 30, default=1)
    liquidity_buffer_days    = round(_safe_div(ba7, avg_daily), 2)

    bal_slope = 0.0
    if len(b30) >= 2:
        bal_slope = _safe_div(b30[0] - b30[-1], max(monthly_income, 1))
    balance_depletion_rate   = round(max(0.0, bal_slope), 4)

    # ── GROUP 2: Income / Salary ───────────────────────────────────────────
    sal90 = W(t90, cat="SALARY_CREDIT", status="success")
    salary_credit_count_90d  = float(len(sal90))

    salary_delay_days = 0.0
    if sal90:
        latest = sal90[-1]
        delay  = latest["ts"].day - expected_sal_day
        if delay < -15: delay += 30
        salary_delay_days = float(max(0, delay))

    sal_amts = [t["amount"] for t in sal90]
    salary_amount_deviation_pct = 0.0
    if len(sal_amts) >= 2:
        avg_s = float(np.mean(sal_amts[:-1]))
        salary_amount_deviation_pct = round(_safe_div(sal_amts[-1] - avg_s, avg_s) * 100, 2)

    income_irregularity = 0.0
    if len(sal90) >= 3:
        days = sorted([t["ts"].day for t in sal90])
        gaps = [days[i+1] - days[i] for i in range(len(days)-1)]
        gaps = [g + 30 if g < 0 else g for g in gaps]
        income_irregularity = round(_safe_div(float(np.std(gaps)), float(np.mean(gaps)) + 1), 4)

    partial_salary_flag = 0.0
    if len(sal_amts) >= 2:
        avg_s = float(np.mean(sal_amts[:-1]))
        partial_salary_flag = 1.0 if sal_amts[-1] < 0.80 * avg_s else 0.0

    # ── GROUP 3: EMI / NACH ────────────────────────────────────────────────
    nach_all    = W(t30, cat=["EMI_DEBIT", "FAILED_EMI_DEBIT"])
    nach_failed = [t for t in nach_all if t["category"] == "FAILED_EMI_DEBIT"]
    nach_ok     = [t for t in nach_all if t["category"] == "EMI_DEBIT"]

    failed_nach_count_30d = float(len(nach_failed))
    total_nach_count_30d  = float(len(nach_all))
    nach_failure_rate     = round(_safe_div(failed_nach_count_30d, total_nach_count_30d), 4)

    emi_payment_delay_days = 0.0
    if nach_ok:
        due_cands = [5, 10, 15, 20, 25, 28]
        delays = []
        for t in nach_ok:
            nd = min(due_cands, key=lambda d: abs(d - t["ts"].day))
            dl = t["ts"].day - nd
            if dl < -15: dl += 30
            delays.append(max(0, dl))
        emi_payment_delay_days = round(float(np.mean(delays)), 2) if delays else 0.0

    consecutive_failed_nach = 0.0
    if nach_all:
        streak = max_s = 0
        for t in sorted(nach_all, key=lambda x: x["ts"]):
            if t["category"] == "FAILED_EMI_DEBIT":
                streak += 1; max_s = max(max_s, streak)
            else:
                streak = 0
        consecutive_failed_nach = float(max_s)

    bounce_count_30d = float(len([t for t in W(t30) if t["status"] == "failed"]))

    # ── GROUP 4: ATM / Cash ────────────────────────────────────────────────
    atm7    = W(t7,  cat="ATM_WITHDRAWAL", status="success")
    atm30   = W(t30, cat="ATM_WITHDRAWAL", status="success")
    atm15r  = W(t15, cat="ATM_WITHDRAWAL", status="success")
    atm15p  = W(t30, t15, cat="ATM_WITHDRAWAL", status="success")

    atm_withdrawal_amount_7d = round(sum(t["amount"] for t in atm7), 2)
    atm_withdrawal_count_7d  = float(len(atm7))
    atm_amount_30d           = round(sum(t["amount"] for t in atm30), 2)
    atm_frequency_trend      = round(_safe_div(len(atm15r) - len(atm15p), len(atm15p) + 1), 4)

    # ── GROUP 5: Lending App ───────────────────────────────────────────────
    lend_d = W(t30, cat="LENDING_APP_DEBIT",  status="success")
    lend_c = W(t30, cat="LENDING_APP_CREDIT", status="success")

    lending_app_transfer_count_30d  = float(len(lend_d))
    lending_app_transfer_amount_30d = round(sum(t["amount"] for t in lend_d), 2)
    lending_disbursement_count_30d  = float(len(lend_c))
    lending_app_dependency_score    = round(_safe_div(lending_app_transfer_amount_30d, monthly_income), 4)

    # ── GROUP 5b: Investment Activity ──────────────────────────────────────
    inv_d = W(t30, cat="INVESTMENT_DEBIT", status="success")
    investment_debit_count_30d  = float(len(inv_d))
    investment_debit_amount_30d = round(sum(t["amount"] for t in inv_d), 2)

    # ── GROUP 6: Spending ──────────────────────────────────────────────────
    disc_cats = ["FOOD_DELIVERY", "ECOMMERCE", "OTT"]
    disc7  = W(t7,  cat=disc_cats, status="success")
    discp7 = W(t14, t7, cat=disc_cats, status="success")
    groc7  = W(t7,  cat="GROCERY",       status="success")
    food7  = W(t7,  cat="FOOD_DELIVERY", status="success")
    onl7   = W(t7,  status="success", debit=True)

    discretionary_spend_7d       = round(sum(t["amount"] for t in disc7), 2)
    grocery_spend_7d             = round(sum(t["amount"] for t in groc7), 2)
    food_delivery_spend_7d       = round(sum(t["amount"] for t in food7), 2)
    online_spend_7d              = round(sum(t["amount"] for t in onl7), 2)
    disc_prev                    = sum(t["amount"] for t in discp7)
    discretionary_wow_change_pct = round(_safe_div(discretionary_spend_7d - disc_prev, disc_prev + 1) * 100, 2)
    total_debit_30d              = round(sum(t["amount"] for t in db30_all), 2)
    spending_velocity_7d         = round(_safe_div(len(W(t7)), 7), 4)

    large_debit_flag = 0.0
    if avg_daily > 0:
        for t in W(t7, status="success", debit=True):
            if t["amount"] > 2 * avg_daily:
                large_debit_flag = 1.0
                break

    # ── GROUP 7: Cross-product & Context (from pre-fetched aggregates) ────
    total_outstanding_debt = float(loans_agg.get("debt") or 0)
    total_emi              = float(loans_agg.get("emi")  or 0)
    active_loan_count      = int(loans_agg.get("loans")  or 0)

    credit_utilization_pct = float(cards_agg.get("util")  or 0)
    active_card_count      = int(cards_agg.get("cards")   or 0)

    debt_to_income_ratio   = round(_safe_div(total_outstanding_debt, monthly_income * 12), 4)
    emi_to_income_ratio    = round(_safe_div(total_emi, monthly_income), 4)
    active_product_count   = float(active_loan_count + active_card_count)

    cr30  = sum(t["amount"] for t in W(t30, status="success", credit=True))
    db30a = sum(t["amount"] for t in W(t30, status="success", debit=True))
    inflow_outflow_ratio_30d = round(_safe_div(cr30, db30a + 1), 4)

    features = {
        "balance_7d_avg": balance_7d_avg,
        "balance_wow_change_pct": balance_wow_change_pct,
        "balance_mom_change_pct": balance_mom_change_pct,
        "net_cash_flow_7d": net_cash_flow_7d,
        "liquidity_buffer_days": liquidity_buffer_days,
        "balance_depletion_rate": balance_depletion_rate,
        "salary_credit_count_90d": salary_credit_count_90d,
        "salary_delay_days": salary_delay_days,
        "salary_amount_deviation_pct": salary_amount_deviation_pct,
        "income_irregularity": income_irregularity,
        "partial_salary_flag": partial_salary_flag,
        "failed_nach_count_30d": failed_nach_count_30d,
        "total_nach_count_30d": total_nach_count_30d,
        "nach_failure_rate": nach_failure_rate,
        "emi_payment_delay_days": emi_payment_delay_days,
        "consecutive_failed_nach": consecutive_failed_nach,
        "bounce_count_30d": bounce_count_30d,
        "atm_withdrawal_amount_7d": atm_withdrawal_amount_7d,
        "atm_withdrawal_count_7d": atm_withdrawal_count_7d,
        "atm_amount_30d": atm_amount_30d,
        "atm_frequency_trend": atm_frequency_trend,
        "lending_app_transfer_count_30d": lending_app_transfer_count_30d,
        "lending_app_transfer_amount_30d": lending_app_transfer_amount_30d,
        "lending_disbursement_count_30d": lending_disbursement_count_30d,
        "lending_app_dependency_score": lending_app_dependency_score,
        "investment_debit_count_30d": investment_debit_count_30d,
        "investment_debit_amount_30d": investment_debit_amount_30d,
        "discretionary_spend_7d": discretionary_spend_7d,
        "grocery_spend_7d": grocery_spend_7d,
        "discretionary_wow_change_pct": discretionary_wow_change_pct,
        "food_delivery_spend_7d": food_delivery_spend_7d,
        "online_spend_7d": online_spend_7d,
        "total_debit_30d": total_debit_30d,
        "spending_velocity_7d": spending_velocity_7d,
        "large_debit_flag": large_debit_flag,
        "total_outstanding_debt": round(total_outstanding_debt, 2),
        "debt_to_income_ratio": debt_to_income_ratio,
        "emi_to_income_ratio": emi_to_income_ratio,
        "credit_utilization_pct": round(credit_utilization_pct, 2),
        "active_product_count": active_product_count,
        "historical_delinquency_count": float(customer_info.get("historical_delinquency_count") or 0),
        "customer_vintage_months": float(customer_info.get("customer_vintage_months") or 0),
        "geography_risk_tier": float(customer_info.get("geography_risk_tier") or 2),
        "inflow_outflow_ratio_30d": inflow_outflow_ratio_30d,
    }

    # Sanitise: replace any NaN/Inf with 0.0
    return {
        k: 0.0 if (v is None or not math.isfinite(float(v))) else round(float(v), 6)
        for k, v in features.items()
    }