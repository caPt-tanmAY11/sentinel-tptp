"""
enrichment/transaction_classifier.py
─────────────────────────────────────────────────────────────────────────────
Classifies a raw transaction into a category using VPA patterns and platform.

DESIGN RULE: Output is EPHEMERAL — never written back to the transactions
table. Used only for feature computation.

Classification priority order:
  1. ATM          — platform = 'ATM'
  2. FAILED_EMI   — NACH + failed + EMI VPA pattern
  3. EMI_DEBIT    — NACH + success + EMI VPA pattern
  4. SALARY       — NEFT/IMPS + payroll sender pattern + credit
  5. LENDING_APP  — receiver/sender matches lending app VPA
  6. UTILITY      — BBPS or utility biller VPA
  7. GROCERY      — grocery merchant VPA
  8. FOOD         — food delivery VPA
  9. FUEL         — fuel merchant VPA
  10. OTT         — streaming service VPA
  11. ECOMMERCE   — e-commerce platform VPA
  12. GENERAL     — everything else
─────────────────────────────────────────────────────────────────────────────
"""
from typing import Dict, Any, Optional
from enrichment.transaction_category import TransactionCategory, CATEGORY_STRESS_WEIGHTS
from config.settings import (
    UPI_LENDING_APP_VPAS,
    BBPS_UTILITY_VPAS,
    NACH_EMI_PATTERNS,
    PAYROLL_SENDER_PATTERNS,
)

# ── Pre-processed pattern lists ───────────────────────────────────────────────
_LENDING_PATTERNS = [p.lower().rstrip("@") for p in UPI_LENDING_APP_VPAS]
_BBPS_PATTERNS    = [v.lower() for v in BBPS_UTILITY_VPAS]
_NACH_PATTERNS    = [p.lower() for p in NACH_EMI_PATTERNS]
_PAYROLL_PATTERNS = [p.lower() for p in PAYROLL_SENDER_PATTERNS]

_GROCERY_PATTERNS    = ["bigbasket", "blinkit", "dmartrewards", "jiomart", "swiggyinstamart", "zepto", "grofers"]
_FOOD_PATTERNS       = ["swiggy@", "zomato@", "eatsure@", "dunzo@", "magicpin@"]
_FUEL_PATTERNS       = ["hpcl@", "iocl@", "bpcl@", "reliancepetro@", "indianoil@", "nayara@"]
_OTT_PATTERNS        = ["netflix@", "primevideo@", "hotstar@", "spotify@", "jiosaavn@", "gaana@", "sonyliv@", "zee5@"]
_ECOMMERCE_PATTERNS  = ["flipkart@", "amazon@", "myntra@", "meesho@", "nykaa@", "ajio@", "snapdeal@", "tatacliq@"]
_INVESTMENT_PATTERNS = [
    "zerodha@", "groww@", "smallcase@", "paytmmoney@", "coinzerodha@",
    "sbimf@", "hdfcmf@", "iciciprudmf@", "nipponmf@", "axismf@",
    "kuvera@", "etmoney@", "angelone@", "upstox@", "iifl@",
    "nps@", "licmf@", "kotakmf@", "dspim@", "mirae@",
    "fincart@", "fisdom@", "arthayantra@",
]


def _contains_any(text: str, patterns: list) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(p in t for p in patterns)


def _starts_with_any(text: str, patterns: list) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(t.startswith(p) for p in patterns)


class TransactionClassifier:

    def classify(
        self,
        platform: str,
        payment_status: str,
        sender_id: Optional[str],
        sender_name: Optional[str],
        receiver_id: Optional[str],
        receiver_name: Optional[str],
        amount: float,
        balance_before: Optional[float],
        balance_after: Optional[float],
        customer_account_number: Optional[str] = None,
    ) -> TransactionCategory:

        platform       = (platform or "").upper()
        payment_status = (payment_status or "success").lower()
        sender_id      = (sender_id   or "").strip()
        sender_name    = (sender_name or "").strip()
        receiver_id    = (receiver_id   or "").strip()
        receiver_name  = (receiver_name or "").strip()

        is_credit = self._is_credit(balance_before, balance_after, sender_id, receiver_id, customer_account_number)
        is_debit  = not is_credit

        category   = "UNKNOWN"
        confidence = 1.0

        # 1. ATM
        if platform == "ATM":
            category = "ATM_WITHDRAWAL"
            is_debit = True

        # 2/3. NACH / ECS — EMI auto-debit
        elif platform in ("NACH", "ECS"):
            is_emi = (
                _contains_any(receiver_id,   _NACH_PATTERNS)
                or _contains_any(receiver_name, ["emi", "loan", "nach", "autodebit"])
            )
            if is_emi:
                category = "FAILED_EMI_DEBIT" if payment_status == "failed" else "EMI_DEBIT"
                is_debit = True
            else:
                category   = "GENERAL_DEBIT" if is_debit else "GENERAL_CREDIT"
                confidence = 0.70

        # 4. Salary credit via NEFT/IMPS/RTGS
        elif platform in ("NEFT", "IMPS", "RTGS") and is_credit:
            if (
                _contains_any(sender_id,   _PAYROLL_PATTERNS)
                or _contains_any(sender_name, ["payroll", "salary", "wages", "pension", "stipend"])
            ):
                category   = "SALARY_CREDIT"
                confidence = 0.95
            else:
                category   = "GENERAL_CREDIT"
                confidence = 0.80

        elif platform in ("NEFT", "IMPS", "RTGS") and is_debit:
            # Investment via NEFT (mutual fund, NPS)
            if _contains_any(receiver_id, _INVESTMENT_PATTERNS) or _contains_any(receiver_name, ["mutual fund", "mf", "nps", "pension"]):
                category   = "INVESTMENT_DEBIT"
                confidence = 0.92
            else:
                category   = "GENERAL_DEBIT"
                confidence = 0.80

        # 5–11. UPI categorisation
        elif platform == "UPI":
            if is_debit and _contains_any(receiver_id, _INVESTMENT_PATTERNS):
                category = "INVESTMENT_DEBIT"
            elif is_debit and _contains_any(receiver_id, _LENDING_PATTERNS):
                category = "LENDING_APP_DEBIT"
            elif is_credit and _contains_any(sender_id, _LENDING_PATTERNS):
                category = "LENDING_APP_CREDIT"
            elif is_debit and _contains_any(receiver_id, _GROCERY_PATTERNS):
                category = "GROCERY"
            elif is_debit and _starts_with_any(receiver_id, _FOOD_PATTERNS):
                category = "FOOD_DELIVERY"
            elif is_debit and _starts_with_any(receiver_id, _FUEL_PATTERNS):
                category = "FUEL"
            elif is_debit and _starts_with_any(receiver_id, _OTT_PATTERNS):
                category = "OTT"
            elif is_debit and _starts_with_any(receiver_id, _ECOMMERCE_PATTERNS):
                category = "ECOMMERCE"
            else:
                category   = "GENERAL_DEBIT" if is_debit else "GENERAL_CREDIT"
                confidence = 0.70

        # 6. BBPS utility
        elif platform == "BBPS":
            category = "UTILITY_PAYMENT"
            is_debit = True

        # 7. POS
        elif platform == "POS":
            if _contains_any(receiver_id, _GROCERY_PATTERNS) or _contains_any(receiver_name, ["grocery", "supermarket", "retail"]):
                category = "GROCERY"
            elif _contains_any(receiver_id, _FUEL_PATTERNS):
                category = "FUEL"
            else:
                category   = "GENERAL_DEBIT"
                confidence = 0.75
            is_debit = True

        # 8. BRANCH / MOBILE
        elif platform in ("BRANCH", "MOBILE"):
            category   = "GENERAL_DEBIT" if is_debit else "GENERAL_CREDIT"
            confidence = 0.65

        # Cross-platform lending app override
        if category in ("GENERAL_DEBIT", "UNKNOWN") and _contains_any(receiver_id, _LENDING_PATTERNS):
            category   = "LENDING_APP_DEBIT"
            confidence = 0.85
        if category in ("GENERAL_CREDIT", "UNKNOWN") and _contains_any(sender_id, _LENDING_PATTERNS):
            category   = "LENDING_APP_CREDIT"
            confidence = 0.85

        is_stress    = category in ("FAILED_EMI_DEBIT", "LENDING_APP_DEBIT", "LENDING_APP_CREDIT")
        stress_weight = CATEGORY_STRESS_WEIGHTS.get(category, 0.05)

        return TransactionCategory(
            category=category,
            confidence=confidence,
            is_debit=is_debit,
            is_stress_signal=is_stress,
            stress_weight=stress_weight,
        )

    @staticmethod
    def _is_credit(balance_before, balance_after, sender_id, receiver_id, customer_account):
        # Primary: balance increased → credit
        if balance_before is not None and balance_after is not None:
            return balance_after > balance_before
        # Secondary: receiver matches customer account
        if customer_account:
            if receiver_id and customer_account in receiver_id:
                return True
            if sender_id and customer_account in sender_id:
                return False
        return False  # default: assume debit


# Module-level singleton
_classifier = TransactionClassifier()


def classify_transaction(txn: Dict[str, Any], customer_account_number: str = None) -> TransactionCategory:
    """
    Convenience function. Pass a transaction dict as returned from the
    transactions table or RawTransactionGenerator.
    """
    return _classifier.classify(
        platform=txn.get("platform", ""),
        payment_status=txn.get("payment_status", "success"),
        sender_id=txn.get("sender_id"),
        sender_name=txn.get("sender_name"),
        receiver_id=txn.get("receiver_id"),
        receiver_name=txn.get("receiver_name"),
        amount=float(txn.get("amount", 0)),
        balance_before=txn.get("balance_before"),
        balance_after=txn.get("balance_after"),
        customer_account_number=customer_account_number,
    )