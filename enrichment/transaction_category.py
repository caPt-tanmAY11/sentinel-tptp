"""
enrichment/transaction_category.py
─────────────────────────────────────────────────────────────────────────────
Pydantic schema for transaction classifier output.
EPHEMERAL — never written back to the transactions table.
─────────────────────────────────────────────────────────────────────────────
"""
from pydantic import BaseModel, Field


class TransactionCategory(BaseModel):
    """
    Classifier output for a single transaction.
    Used for feature computation only — never persisted on the transaction row.

    Valid categories:
      SALARY_CREDIT      — NEFT/IMPS credit from employer payroll VPA
      EMI_DEBIT          — successful NACH auto-debit to loan VPA
      FAILED_EMI_DEBIT   — failed NACH auto-debit to loan VPA
      LENDING_APP_DEBIT  — UPI transfer TO a lending app (repayment)
      LENDING_APP_CREDIT — UPI/IMPS FROM a lending app (disbursement)
      UTILITY_PAYMENT    — BBPS payment to utility biller
      ATM_WITHDRAWAL     — ATM cash withdrawal
      GROCERY            — grocery merchant VPA
      FOOD_DELIVERY      — food delivery VPA
      FUEL               — fuel/petrol VPA
      ECOMMERCE          — e-commerce platform
      OTT                — streaming subscription
      GENERAL_DEBIT      — unclassified outflow
      GENERAL_CREDIT     — unclassified inflow
      UNKNOWN            — not enough information
    """

    category: str = "UNKNOWN"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_debit: bool = True             # True = money leaving customer account
    is_stress_signal: bool = False    # True = category is a known stress indicator
    stress_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    # stress_weight: relative stress contribution [0.0, 1.0]
    # FAILED_EMI_DEBIT → 0.90,  LENDING_APP_DEBIT → 0.85
    # ATM_WITHDRAWAL   → 0.30,  UTILITY_PAYMENT   → 0.05
    # SALARY_CREDIT    → 0.00 (negative stress = relief signal)


# Stress weight lookup — read by classifier and pulse accumulator
CATEGORY_STRESS_WEIGHTS: dict = {
    "SALARY_CREDIT":      0.00,
    "EMI_DEBIT":          0.00,
    "INVESTMENT_DEBIT":   0.00,   # SIP/MF/stock purchase → wealth building, relief
    "FAILED_EMI_DEBIT":   0.90,
    "LENDING_APP_DEBIT":  0.85,
    "LENDING_APP_CREDIT": 0.70,
    "UTILITY_PAYMENT":    0.05,
    "ATM_WITHDRAWAL":     0.30,
    "GROCERY":            0.00,
    "FOOD_DELIVERY":      0.10,
    "FUEL":               0.05,
    "ECOMMERCE":          0.10,
    "OTT":                0.00,
    "GENERAL_DEBIT":      0.05,
    "GENERAL_CREDIT":     0.00,
    "UNKNOWN":            0.00,
}