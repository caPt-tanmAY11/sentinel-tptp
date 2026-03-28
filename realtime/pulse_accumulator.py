"""
realtime/pulse_accumulator.py
─────────────────────────────────────────────────────────────────────────────
Maintains customer pulse score [0.0, 1.0] via bounded incremental updates.
All parameters from config/settings.py. Nothing hardcoded.

CATEGORY PHILOSOPHY:
  RELIEF (score decreases):
    SALARY_CREDIT  — money arrived from employer → financial health
    EMI_DEBIT      — EMI paid on time → obligations being met

  STRESS (score increases):
    FAILED_EMI_DEBIT   — missed payment obligation
    LENDING_APP_DEBIT  — borrowing from digital lender
    LENDING_APP_CREDIT — receiving loan from digital lender

  NEUTRAL (score unchanged — normal everyday life):
    GROCERY, UTILITY_PAYMENT, FOOD_DELIVERY, FUEL, ECOMMERCE, OTT,
    ATM_WITHDRAWAL, GENERAL_DEBIT, GENERAL_CREDIT, UNKNOWN
    P2P transfers between friends/family (GENERAL_DEBIT)
    Coffee, dining, medical, travel, entertainment

  WHY: Paying for groceries, utilities, dining, fuel is normal behaviour.
  The model should only react to things that deviate from the customer's
  own historical pattern — which is what the z-score delta features capture.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations
from config.settings import get_settings

settings = get_settings()

# Relief: strong financial health signals — score decreases
RELIEF_CATEGORIES = frozenset({
    "SALARY_CREDIT",   # money from employer → income confirmed
    "EMI_DEBIT",       # on-time EMI → obligations met
    "INVESTMENT_DEBIT", # SIP / mutual fund / stock purchase → wealth building
})

# Stress: financial distress signals — score increases
STRESS_CATEGORIES = frozenset({
    "FAILED_EMI_DEBIT",    # missed payment
    "LENDING_APP_DEBIT",   # sending money to digital lender (repayment / borrowing)
    "LENDING_APP_CREDIT",  # receiving loan from digital lender
})

# Everything else is NEUTRAL: normal everyday transactions
# (grocery, utilities, dining, fuel, P2P, ecommerce, OTT, ATM, etc.)


def compute_direction(category: str, severity: float) -> str:
    """
    Determine the direction of the pulse score change.

    Known STRESS/RELIEF categories bypass the noise floor entirely.
    All other categories require model severity >= noise floor to act.

    Returns: 'positive' (stress) | 'negative' (relief) | 'neutral'
    """
    # Known stress — always positive, no noise floor
    if category in STRESS_CATEGORIES:
        return "positive"

    # Known relief — always negative, no noise floor
    if category in RELIEF_CATEGORIES:
        return "negative"

    # Everything else: model must exceed noise floor to register
    if severity < settings.PULSE_DAMPING_NOISE_FLOOR:
        return "neutral"

    # Ambiguous categories with high model severity → stress
    if severity >= 0.60:
        return "positive"

    return "neutral"


def compute_delta(severity: float, direction: str, current_score: float) -> float:
    """
    Compute bounded delta for the customer's overall pulse score.

    Args:
        severity:      Model output [0.0, 1.0]
        direction:     'positive' | 'negative' | 'neutral'
        current_score: Current overall pulse score [0.0, 1.0]

    Returns:
        Signed delta. Positive = more stress. Bounded by config caps.
    """
    if direction == "neutral":
        return 0.0

    direction_sign = 1.0 if direction == "positive" else -1.0

    # Known categories with low stress_weight (e.g. SALARY=0.0, EMI=0.0):
    # use the noise floor as minimum effective severity so they produce a real delta
    effective_severity = max(severity, settings.PULSE_DAMPING_NOISE_FLOOR)

    # Cap selection
    max_delta = (
        settings.PULSE_MAX_HEINOUS_DELTA
        if effective_severity >= settings.PULSE_HEINOUS_THRESHOLD
        else settings.PULSE_MAX_SINGLE_DELTA
    )

    raw_delta = effective_severity * max_delta

    # High-score damping: score near critical → needs strong evidence to move further
    if (current_score > settings.PULSE_HIGH_SCORE_THRESHOLD
            and effective_severity < 0.50
            and direction == "positive"):
        raw_delta *= settings.PULSE_HIGH_SCORE_DAMPING

    # Recovery amplification: recovering customers get faster relief
    if (current_score < settings.PULSE_LOW_SCORE_THRESHOLD
            and direction == "negative"):
        raw_delta *= settings.PULSE_RECOVERY_AMPLIFICATION

    return round(direction_sign * min(abs(raw_delta), max_delta), 6)


def apply_delta(current_score: float, delta: float) -> float:
    """Apply delta, clipping to [0.0, 1.0]."""
    return round(max(0.0, min(1.0, current_score + delta)), 6)


def apply_cibil_modifier(
    severity: float,
    direction: str,
    cibil_score: int,
) -> tuple:
    """
    Adjust effective severity based on CIBIL score.
    High CIBIL → dampen stress, amplify recovery.
    Low CIBIL  → amplify stress.
    Returns (modified_severity, modified_direction).
    """
    if cibil_score is None:
        return severity, direction

    if cibil_score >= 750:
        if direction == "positive":
            severity = severity * 0.85          # dampen stress 15%
        elif direction == "negative":
            severity = severity * 1.15          # amplify recovery 15%
    elif cibil_score < 650:
        if direction == "positive":
            severity = severity * 1.15          # amplify stress 15%
        elif direction == "negative":
            severity = severity * 0.85          # dampen recovery

    return round(min(severity, 1.0), 6), direction


def assign_risk_tier(pulse_score: float, cibil_score: int = None) -> dict:
    """Map pulse score [0.0, 1.0] to risk tier. Thresholds from config.
    Optionally applies a CIBIL-based nudge: customers with very high CIBIL
    (750+) get one-tier leniency; very low CIBIL (<600) get one-tier penalty.
    """
    # Raw tier from score
    if pulse_score >= settings.RISK_TIER_CRITICAL:
        raw_tier, raw_label = 1, "CRITICAL"
    elif pulse_score >= settings.RISK_TIER_HIGH:
        raw_tier, raw_label = 2, "HIGH"
    elif pulse_score >= settings.RISK_TIER_MODERATE:
        raw_tier, raw_label = 3, "MODERATE"
    elif pulse_score >= settings.RISK_TIER_WATCH:
        raw_tier, raw_label = 4, "WATCH"
    else:
        raw_tier, raw_label = 5, "STABLE"

    if cibil_score is None:
        return {"tier": raw_tier, "label": raw_label}

    # CIBIL nudge — max one tier in either direction, never below CRITICAL
    if cibil_score >= 750 and raw_tier > 1:
        adjusted_tier = raw_tier + 1          # one tier more lenient (e.g. HIGH→MODERATE)
    elif cibil_score < 600 and raw_tier < 5:
        adjusted_tier = raw_tier - 1          # one tier harsher (e.g. WATCH→MODERATE)
    else:
        adjusted_tier = raw_tier

    adjusted_tier = max(1, min(5, adjusted_tier))

    _TIER_LABELS = {1: "CRITICAL", 2: "HIGH", 3: "MODERATE", 4: "WATCH", 5: "STABLE"}
    return {"tier": adjusted_tier, "label": _TIER_LABELS[adjusted_tier]}