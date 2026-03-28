"""
fraud_detection/fraud_detector.py
─────────────────────────────────────────────────────────────────────────────
Probable Fault Detection (PFD) engine.

Analyses a single incoming TransactionEvent against three independent signals:

  Signal 1 — INTERNATIONAL
      Fires when currency != 'INR' OR receiver_country != 'IN'.
      Weight: 0.35

  Signal 2 — AMOUNT SPIKE
      Computes Z-score of txn_amount against the customer's 30-day
      transaction history (mean + std dev from DB).
      Fires when Z-score > AMOUNT_ZSCORE_THRESHOLD (default 3.0).
      Weight: 0.40

  Signal 3 — FREQUENCY SPIKE
      Counts how many transactions the customer made in the last 60
      minutes, compared to their baseline hourly rate (30-day avg).
      Fires when current_hour_count > baseline_hourly_avg * FREQ_MULTIPLIER
      AND current_hour_count >= FREQ_MIN_COUNT.
      Weight: 0.25

Composite fraud score = sum of weights of fired signals (0.0 – 1.0).
Alert is raised when composite score >= FRAUD_SCORE_THRESHOLD (default 0.35,
meaning even a single signal firing is enough to flag).

If an alert is raised:
  - The result carries is_fraud=True.
  - Caller (PulseEngine) must skip the pulse score update for this txn.
  - Caller must persist a row to fraud_alerts and trigger the alert email.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from config.settings import get_settings
from schemas.transaction_event import TransactionEvent

settings = get_settings()


# ── Thresholds (tune here, not buried in logic) ───────────────────────────

AMOUNT_ZSCORE_THRESHOLD: float = 3.0   # σ above 30d mean → amount spike
FREQ_MULTIPLIER:         float = 3.0   # x times baseline hourly rate → freq spike
FREQ_MIN_COUNT:          int   = 5     # absolute floor — don't fire on 1 vs 0.3 avg
FRAUD_SCORE_THRESHOLD:   float = 0.35  # minimum composite score to raise an alert

# Signal weights — must sum to 1.0
W_INTERNATIONAL: float = 0.35
W_AMOUNT_SPIKE:  float = 0.40
W_FREQ_SPIKE:    float = 0.25

# Lookback windows
AMOUNT_LOOKBACK_DAYS:  int = 30   # days of history for mean/std computation
FREQ_LOOKBACK_MINUTES: int = 60   # rolling window for frequency check
FREQ_BASELINE_DAYS:    int = 30   # days used to compute baseline hourly rate

# Minimum sample size — don't compute Z-score on tiny history
AMOUNT_MIN_SAMPLES: int = 5


# ── Result dataclass ─────────────────────────────────────────────────────

@dataclass
class FraudCheckResult:
    """
    Returned by FraudDetector.check() for every transaction.
    If is_fraud=False, all other fields are informational only.
    """
    is_fraud:               bool
    fraud_score:            float           # 0.0 – 1.0

    # Which signals fired
    signal_international:   bool = False
    signal_amount_spike:    bool = False
    signal_freq_spike:      bool = False

    # Audit trail numbers
    amount_zscore:          Optional[float] = None
    baseline_amount_avg:    Optional[float] = None
    baseline_amount_std:    Optional[float] = None
    hourly_txn_count:       Optional[int]   = None
    baseline_hourly_avg:    Optional[float] = None

    # Human-readable explanation
    fraud_reason:           str = ""

    # EMI context — populated by _check_upcoming_emi()
    next_emi_due_date:      Optional[datetime] = None
    emi_amount:             Optional[float]    = None
    payment_holiday_suggested: bool            = False


# ── Main engine ──────────────────────────────────────────────────────────

class FraudDetector:
    """
    Stateless detector — one instance per process is fine.
    Every public method takes a DB connection to avoid opening new
    connections per transaction.
    """

    # ── Public entry point ────────────────────────────────────────

    def check(
        self,
        event:  TransactionEvent,
        conn:   psycopg2.extensions.connection,
    ) -> FraudCheckResult:
        """
        Run all three fraud signals against `event`.
        Returns a FraudCheckResult. Caller decides what to do with it.
        """
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        sig_intl,   reason_intl   = self._check_international(event)
        sig_amount, reason_amount, amount_meta = self._check_amount_spike(event, cursor)
        sig_freq,   reason_freq,   freq_meta   = self._check_freq_spike(event, cursor)

        # Composite score
        score = (
            (W_INTERNATIONAL if sig_intl   else 0.0) +
            (W_AMOUNT_SPIKE  if sig_amount else 0.0) +
            (W_FREQ_SPIKE    if sig_freq   else 0.0)
        )

        is_fraud = score >= FRAUD_SCORE_THRESHOLD

        # Build human-readable reason string
        fired_reasons = [r for r in [reason_intl, reason_amount, reason_freq] if r]
        fraud_reason  = "; ".join(fired_reasons) if fired_reasons else "No anomaly detected"

        result = FraudCheckResult(
            is_fraud             = is_fraud,
            fraud_score          = round(score, 4),
            signal_international = sig_intl,
            signal_amount_spike  = sig_amount,
            signal_freq_spike    = sig_freq,
            fraud_reason         = fraud_reason,
            **amount_meta,
            **freq_meta,
        )

        # If it's fraud, check whether an EMI is due soon
        if is_fraud:
            self._check_upcoming_emi(event.customer_id, cursor, result)

        return result


    # ── Signal 1: International transaction ───────────────────────

    def _check_international(
        self,
        event: TransactionEvent,
    ) -> tuple[bool, str]:
        """
        Fires if the transaction is in a foreign currency OR
        the receiver is in a country other than India.
        """
        foreign_currency = (event.currency or "INR").upper() != "INR"
        foreign_country  = (event.receiver_country or "IN").upper() != "IN"

        if not (foreign_currency or foreign_country):
            return False, ""

        parts = []
        if foreign_currency:
            parts.append(f"currency={event.currency}")
        if foreign_country:
            parts.append(f"receiver_country={event.receiver_country}")

        vpa_str = f" to {event.receiver_vpa}" if event.receiver_vpa else ""
        reason  = (
            f"International transaction{vpa_str} "
            f"({', '.join(parts)})"
        )
        return True, reason


    # ── Signal 2: Amount spike ─────────────────────────────────────

    def _check_amount_spike(
        self,
        event:  TransactionEvent,
        cursor: RealDictCursor,
    ) -> tuple[bool, str, dict]:
        """
        Computes Z-score of this transaction's amount vs the customer's
        last 30 days of successful transactions.

        Returns (fired, reason, meta_dict).
        meta_dict keys match FraudCheckResult field names.
        """
        meta = {
            "amount_zscore":       None,
            "baseline_amount_avg": None,
            "baseline_amount_std": None,
        }

        cursor.execute(
            """
            SELECT
                COUNT(*)            AS sample_count,
                AVG(amount)         AS mean_amount,
                STDDEV_POP(amount)  AS std_amount
            FROM transactions
            WHERE customer_id    = %s
              AND payment_status = 'success'
              AND txn_timestamp  >= NOW() - INTERVAL '%s days'
              AND transaction_id != %s
            """,
            (event.customer_id, AMOUNT_LOOKBACK_DAYS, event.event_id),
        )
        row = cursor.fetchone()

        if not row or (row["sample_count"] or 0) < AMOUNT_MIN_SAMPLES:
            # Not enough history — skip this signal conservatively
            return False, "", meta

        mean = float(row["mean_amount"] or 0)
        std  = float(row["std_amount"]  or 0)

        meta["baseline_amount_avg"] = round(mean, 2)
        meta["baseline_amount_std"] = round(std,  2)

        if std < 1.0:
            # Near-zero variance — customer has very consistent amounts.
            # Use a simpler multiplier check (5x mean) instead of Z-score.
            if event.amount > mean * 5 and event.amount > 10_000:
                meta["amount_zscore"] = None
                reason = (
                    f"Amount ₹{event.amount:,.0f} is >5× customer's "
                    f"typical ₹{mean:,.0f} (low-variance account)"
                )
                return True, reason, meta
            return False, "", meta

        zscore = (event.amount - mean) / std
        meta["amount_zscore"] = round(zscore, 4)

        if zscore <= AMOUNT_ZSCORE_THRESHOLD:
            return False, "", meta

        reason = (
            f"Amount ₹{event.amount:,.0f} is {zscore:.1f}σ above "
            f"30d baseline avg ₹{mean:,.0f} (σ=₹{std:,.0f})"
        )
        return True, reason, meta


    # ── Signal 3: Frequency spike ──────────────────────────────────

    def _check_freq_spike(
        self,
        event:  TransactionEvent,
        cursor: RealDictCursor,
    ) -> tuple[bool, str, dict]:
        """
        Compares how many transactions the customer made in the last 60
        minutes vs their average hourly rate over the last 30 days.

        Returns (fired, reason, meta_dict).
        meta_dict keys match FraudCheckResult field names.
        """
        meta = {
            "hourly_txn_count":   None,
            "baseline_hourly_avg": None,
        }

        # Current rolling-hour count
        cursor.execute(
            """
            SELECT COUNT(*) AS hour_count
            FROM transactions
            WHERE customer_id   = %s
              AND txn_timestamp >= %s - INTERVAL '%s minutes'
              AND txn_timestamp <= %s
            """,
            (
                event.customer_id,
                event.txn_timestamp,
                FREQ_LOOKBACK_MINUTES,
                event.txn_timestamp,
            ),
        )
        hour_row   = cursor.fetchone()
        hour_count = int(hour_row["hour_count"] or 0) if hour_row else 0
        meta["hourly_txn_count"] = hour_count

        # Baseline: total txns in last 30 days ÷ (30 * 24) hours
        cursor.execute(
            """
            SELECT COUNT(*) AS total_count
            FROM transactions
            WHERE customer_id   = %s
              AND txn_timestamp >= NOW() - INTERVAL '%s days'
            """,
            (event.customer_id, FREQ_BASELINE_DAYS),
        )
        baseline_row   = cursor.fetchone()
        total_30d      = int(baseline_row["total_count"] or 0) if baseline_row else 0
        baseline_hourly = round(total_30d / (FREQ_BASELINE_DAYS * 24), 4)
        meta["baseline_hourly_avg"] = baseline_hourly

        if hour_count < FREQ_MIN_COUNT:
            # Absolute floor — never flag on low absolute counts
            return False, "", meta

        if baseline_hourly < 0.01:
            # Customer barely transacts — any burst is suspicious,
            # but we need the absolute floor above as guard.
            reason = (
                f"{hour_count} transactions in the last hour "
                f"vs near-zero baseline rate"
            )
            return True, reason, meta

        if hour_count <= baseline_hourly * FREQ_MULTIPLIER:
            return False, "", meta

        reason = (
            f"{hour_count} transactions in last 60 min "
            f"vs baseline avg {baseline_hourly:.1f}/hr "
            f"({hour_count / baseline_hourly:.1f}× normal rate)"
        )
        return True, reason, meta


    # ── EMI context check ──────────────────────────────────────────

    def _check_upcoming_emi(
        self,
        customer_id: str,
        cursor:      RealDictCursor,
        result:      FraudCheckResult,
    ) -> None:
        """
        Checks if any active loan has an EMI due within 7 days.
        Populates result.next_emi_due_date, result.emi_amount,
        and result.payment_holiday_suggested in-place.
        """
        cursor.execute(
            """
            SELECT
                emi_due_date,
                emi_amount
            FROM loans
            WHERE customer_id  = %s
              AND status   = 'ACTIVE'
            """,
            (customer_id,),
        )
        
        today = datetime.now(timezone.utc)
        for row in cursor.fetchall():
            due_day = row.get("emi_due_date")
            if due_day:
                try:
                    due_day = min(int(due_day), 28) # simplify month-end
                    due_date = today.replace(day=due_day, hour=0, minute=0, second=0, microsecond=0)
                    if due_date < today:
                        if today.month == 12:
                            due_date = due_date.replace(year=today.year+1, month=1)
                        else:
                            due_date = due_date.replace(month=today.month+1)
                    
                    if (due_date - today).days <= 7:
                        result.next_emi_due_date       = due_date
                        result.emi_amount              = float(row["emi_amount"] or 0)
                        result.payment_holiday_suggested = True
                        break
                except ValueError:
                    pass