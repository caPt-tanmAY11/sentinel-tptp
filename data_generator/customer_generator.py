"""
data_generator/customer_generator.py
─────────────────────────────────────────────────────────────────────────────
Generates synthetic Indian banking customer profiles.
CRITICAL:
  - NO is_stress_profile field — stress is NOT pre-assigned at generation.
  - Stress emerges from transaction patterns, discovered by the model.
  - All customers look the same at generation time.
  STRESS SYNC CONTRACT:
  - STRESS_PREVALENCE must be identical here and in raw_transaction_generator.py
  - _customer_will_develop_stress() uses the EXACT same seed formula as
    RawTransactionGenerator.__init__ so that the loans table and the
    transaction generator are ALWAYS in agreement about which customers
    are stressed.  Never change one without changing the other.
Outputs:
  - Customer profile dict (maps directly to customers table)
  - List of loan dicts per customer (maps to loans table)
  - Optional credit card dict (maps to credit_cards table)
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
import random
import hashlib
import string
import re as _re
from datetime import date, timedelta
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from config.settings import (
    get_settings,
    STATE_TO_RISK_TIER,
    CITIES_BY_STATE,
    GEO_RISK_TIERS,
)
from data_generator.indian_names import (
    generate_first_name,
    generate_last_name,
    generate_upi_vpa,
    generate_pan_number,
    generate_account_number,
    generate_loan_account_number,
    generate_ifsc_code,
    generate_nach_vpa,
    get_payroll_vpa,
    UPI_BANK_CODES,
    PAYROLL_VPA_PATTERNS,
)
settings = get_settings()
# ── Stress prevalence — MUST match raw_transaction_generator.py exactly ───────
# Raising from 0.15 → 0.28 gives the model enough positive examples to learn
# from, while keeping the dataset realistic for Indian lending portfolios.
# ⚠️  SYNC RULE: If you change this constant you MUST change the identical
#     constant in data_generator/raw_transaction_generator.py simultaneously.
STRESS_PREVALENCE = 0.28
# ── Income Distributions by Segment × Employment Type (Indian 2024) ──────────
INCOME_DISTRIBUTIONS: Dict[str, Dict[str, Dict[str, float]]] = {
    "SALARIED": {
        "RETAIL":       {"mean": 45_000,  "std": 15_000,  "min": 15_000,  "max": 200_000},
        "HNI":          {"mean": 250_000, "std": 100_000, "min": 150_000, "max": 1_000_000},
        "SME":          {"mean": 60_000,  "std": 25_000,  "min": 20_000,  "max": 300_000},
        "MICROFINANCE": {"mean": 12_000,  "std": 4_000,   "min": 5_000,   "max": 25_000},
    },
    "SELF_EMPLOYED": {
        "RETAIL":       {"mean": 55_000,  "std": 30_000,  "min": 10_000,  "max": 300_000},
        "HNI":          {"mean": 350_000, "std": 150_000, "min": 200_000, "max": 2_000_000},
        "SME":          {"mean": 80_000,  "std": 40_000,  "min": 15_000,  "max": 500_000},
        "MICROFINANCE": {"mean": 15_000,  "std": 6_000,   "min": 5_000,   "max": 35_000},
    },
    "BUSINESS_OWNER": {
        "RETAIL":       {"mean": 75_000,  "std": 40_000,  "min": 20_000,  "max": 400_000},
        "HNI":          {"mean": 500_000, "std": 200_000, "min": 300_000, "max": 3_000_000},
        "SME":          {"mean": 120_000, "std": 60_000,  "min": 30_000,  "max": 700_000},
        "MICROFINANCE": {"mean": 18_000,  "std": 7_000,   "min": 6_000,   "max": 40_000},
    },
    "RETIRED": {
        "RETAIL":       {"mean": 30_000,  "std": 12_000,  "min": 10_000,  "max": 100_000},
        "HNI":          {"mean": 150_000, "std": 70_000,  "min": 80_000,  "max": 500_000},
        "SME":          {"mean": 35_000,  "std": 15_000,  "min": 10_000,  "max": 80_000},
        "MICROFINANCE": {"mean": 8_000,   "std": 3_000,   "min": 3_000,   "max": 20_000},
    },
}
# Employer pools by sector
EMPLOYER_POOLS: Dict[str, List[str]] = {
    "IT":            ["TCS", "Infosys", "Wipro", "HCL Technologies", "Tech Mahindra",
                      "Cognizant", "Accenture India", "IBM India", "Capgemini India"],
    "BFSI":          ["HDFC Bank", "ICICI Bank", "Axis Bank", "Kotak Mahindra",
                      "Bajaj Finance", "LIC", "SBI Life"],
    "MANUFACTURING": ["Tata Steel", "L&T", "Mahindra & Mahindra", "Reliance Industries",
                      "Adani Group", "JSW Steel", "Hindustan Unilever"],
    "GOVERNMENT":    ["Central Government", "State Government", "Indian Railways",
                      "DRDO", "ISRO", "BSNL"],
    "HEALTHCARE":    ["Apollo Hospitals", "Fortis Healthcare", "Max Healthcare",
                      "Manipal Hospitals"],
    "EDUCATION":     ["IIT Delhi", "IIM Ahmedabad", "Amity University", "Manipal University"],
}
# Bank names used in account and loan generation
BANK_NAMES = [
    "HDFC Bank", "ICICI Bank", "SBI", "Axis Bank", "Kotak Mahindra",
    "IndusInd Bank", "Yes Bank", "PNB", "Bank of India", "Canara Bank",
]
# Short codes for bank names (for loan account numbers)
BANK_SHORT_CODES = {
    "HDFC Bank":      "HDFC",
    "ICICI Bank":     "ICIC",
    "SBI":            "SBI",
    "Axis Bank":      "AXIS",
    "Kotak Mahindra": "KKBK",
    "IndusInd Bank":  "INDB",
    "Yes Bank":       "YESB",
    "PNB":            "PNB",
    "Bank of India":  "BOI",
    "Canara Bank":    "CANR",
}
# Segment probabilities for customer mix
SEGMENT_WEIGHTS = {
    "RETAIL":       0.65,
    "SME":          0.20,
    "HNI":          0.08,
    "MICROFINANCE": 0.07,
}
# Employment type probabilities by segment
EMPLOYMENT_WEIGHTS = {
    "RETAIL":       {"SALARIED": 0.65, "SELF_EMPLOYED": 0.20, "BUSINESS_OWNER": 0.10, "RETIRED":
0.05},
    "HNI":          {"SALARIED": 0.40, "SELF_EMPLOYED": 0.25, "BUSINESS_OWNER": 0.30, "RETIRED":
0.05},
    "SME":          {"SALARIED": 0.30, "SELF_EMPLOYED": 0.35, "BUSINESS_OWNER": 0.30, "RETIRED":
0.05},
    "MICROFINANCE": {"SALARIED": 0.40, "SELF_EMPLOYED": 0.45, "BUSINESS_OWNER": 0.10, "RETIRED":
0.05},
}
# Loan probability and count by segment
LOAN_CONFIG = {
    "RETAIL":       {"prob_has_loan": 0.70, "max_loans": 2},
    "HNI":          {"prob_has_loan": 0.60, "max_loans": 3},
    "SME":          {"prob_has_loan": 0.80, "max_loans": 3},
    "MICROFINANCE": {"prob_has_loan": 0.75, "max_loans": 1},
}
LOAN_TYPE_WEIGHTS = {
    "RETAIL":       {"HOME": 0.25, "PERSONAL": 0.35, "AUTO": 0.20, "EDUCATION": 0.10,
"BUSINESS": 0.05, "CREDIT_CARD": 0.05},
    "HNI":          {"HOME": 0.40, "PERSONAL": 0.15, "AUTO": 0.25, "EDUCATION": 0.05,
"BUSINESS": 0.10, "CREDIT_CARD": 0.05},
    "SME":          {"HOME": 0.15, "PERSONAL": 0.20, "AUTO": 0.15, "EDUCATION": 0.05,
"BUSINESS": 0.40, "CREDIT_CARD": 0.05},
    "MICROFINANCE": {"HOME": 0.10, "PERSONAL": 0.50, "AUTO": 0.10, "EDUCATION": 0.20,
"BUSINESS": 0.10, "CREDIT_CARD": 0.00},
}
# Credit card probability by segment
CREDIT_CARD_PROB = {
    "RETAIL":       0.45,
    "HNI":          0.85,
    "SME":          0.60,
    "MICROFINANCE": 0.05,
}
# ── Helpers ───────────────────────────────────────────────────────────────────
def _email_slug(first_name: str, last_name: str, rng: random.Random) -> str:
    """Build an email-safe slug from first/last name."""
    fn = _re.sub(r"[^a-z]", "", first_name.lower())
    ln = _re.sub(r"[^a-z]", "", last_name.lower())
    suffix = rng.randint(1, 99) if rng.random() < 0.4 else ""
    return f"{fn}.{ln}{suffix}"
# ── Stress determinism helper ─────────────────────────────────────────────────
def _customer_will_develop_stress(customer_id: str) -> bool:
    """
    Deterministically decide whether a customer will develop stress patterns.
    CRITICAL DESIGN CONTRACT:
    This function uses the IDENTICAL seed formula as RawTransactionGenerator:
        seed = hash(customer_id) % (2**31)
        rng  = random.Random(seed)
        flag = rng.random() < STRESS_PREVALENCE   ← first call on that rng
    RawTransactionGenerator.__init__ does exactly this as its first rng call,
    so both the loans table AND the transaction stream will always agree on
    which customers are stressed — eliminating the label/feature disconnect
    that caused the model to learn from pure noise.
    Do NOT call any other rng methods before the stress check.
    Do NOT change the hash formula without updating RawTransactionGenerator.
    """
    seed = hash(customer_id) % (2 ** 31)
    rng = random.Random(seed)
    return rng.random() < STRESS_PREVALENCE
# ── Sequence counter (thread-unsafe — fine for single-process seeding) ────────
_LOAN_SEQUENCE = 0
def _next_loan_sequence() -> int:
    global _LOAN_SEQUENCE
    _LOAN_SEQUENCE += 1
    return _LOAN_SEQUENCE
def _reset_sequence() -> None:
    global _LOAN_SEQUENCE
    _LOAN_SEQUENCE = 0
# ── Customer Generator ────────────────────────────────────────────────────────
def generate_customer(
    rng: random.Random,
    np_rng: np.random.Generator,
    sequence_id: int,
) -> Dict[str, Any]:
    """
    Generate a single customer profile.
    Returns a dict that maps directly to the customers table columns.
    NO is_stress_profile — stress is never pre-assigned.
    """
    # ── Segment and employment
    segment = rng.choices(
        list(SEGMENT_WEIGHTS.keys()),
        weights=list(SEGMENT_WEIGHTS.values()),
        k=1,
    )[0]
    emp_weights = EMPLOYMENT_WEIGHTS[segment]
    employment_type = rng.choices(
        list(emp_weights.keys()),
        weights=list(emp_weights.values()),
        k=1,
    )[0]
    # ── Geography
    all_states = list(CITIES_BY_STATE.keys())
    state = rng.choice(all_states)
    city = rng.choice(CITIES_BY_STATE[state])
    pincode = "".join(rng.choices(string.digits, k=6))
    geo_risk_tier = STATE_TO_RISK_TIER.get(state, 2)
    # ── Identity
    gender = rng.choices(["Male", "Female"], weights=[0.55, 0.45], k=1)[0]
    first_name = generate_first_name(gender, rng)
    last_name = generate_last_name(state, rng)
    # ── Date of birth (18–65 years old)
    today = date.today()
    age_days = rng.randint(18 * 365, 65 * 365)
    dob = today - timedelta(days=age_days)
    # ── Income
    inc_params = INCOME_DISTRIBUTIONS[employment_type][segment]
    monthly_income = float(np.clip(
        np_rng.normal(inc_params["mean"], inc_params["std"]),
        inc_params["min"],
        inc_params["max"],
    ))
    monthly_income = round(monthly_income / 500) * 500  # round to nearest ₹500
    # ── Employment details
    employer_id = None
    employer_name = None
    if employment_type == "SALARIED":
        sector = rng.choice(list(EMPLOYER_POOLS.keys()))
        employer_name = rng.choice(EMPLOYER_POOLS[sector])
        employer_id = f"EMP_{employer_name[:4].upper()}_{rng.randint(1000, 9999)}"
    # ── Expected salary / pension day
    if employment_type == "SALARIED":
        expected_salary_day = rng.choice([1, 5, 7, 10, 25, 28, 30])
    elif employment_type == "SELF_EMPLOYED":
        expected_salary_day = rng.choice([1, 5, 10])
    elif employment_type == "BUSINESS_OWNER":
        expected_salary_day = rng.choice([1, 15])
    else:  # RETIRED — pension credited on 5th
        expected_salary_day = 5
    # ── Account open date (customer vintage)
    max_vintage_days = min(age_days - 18 * 365, 20 * 365)
    vintage_days = rng.randint(30, max(31, max_vintage_days))
    account_open_date = today - timedelta(days=vintage_days)
    customer_vintage_months = vintage_days // 30
    # ── Bank assignment
    bank_name = rng.choice(BANK_NAMES)
    bank_code = BANK_SHORT_CODES[bank_name]
    # ── Account identifiers
    account_number = generate_account_number(rng)
    account_id     = f"ACC{sequence_id:07d}"
    ifsc_code      = generate_ifsc_code(bank_name, rng)
    upi_vpa        = generate_upi_vpa(first_name, last_name, rng)
    pan_number     = generate_pan_number(first_name, rng)
    # ── Aadhaar hash (never store raw Aadhaar)
    fake_aadhaar = "".join(rng.choices(string.digits, k=12))
    aadhaar_hash = hashlib.sha256(fake_aadhaar.encode()).hexdigest()
    # ── Credit bureau score (600–850)
    credit_bureau_score = int(np.clip(
        np_rng.normal(720, 60),
        600, 850,
    ))
    # ── Historical delinquency count (most customers have 0)
    historical_delinquency_count = int(np_rng.choice(
        [0, 1, 2, 3],
        p=[0.78, 0.14, 0.06, 0.02],
    ))
    # ── Opening balance (1.5–8× monthly income)
    opening_balance = round(float(np_rng.uniform(
        monthly_income * 1.5,
        monthly_income * 8.0,
    )))
    # ── Phone number (Indian mobile: 10 digits starting with 6–9)
    phone = rng.choice("6789") + "".join(rng.choices(string.digits, k=9))
    # ── Email
    email_providers = ["gmail.com", "yahoo.co.in", "hotmail.com", "outlook.com"]
    slug  = _email_slug(first_name, last_name, rng)
    email = f"{slug}@{rng.choice(email_providers)}"
    return {
        "customer_id":                  str(uuid.uuid4()),
        "first_name":                   first_name,
        "last_name":                    last_name,
        "email":                        email,
        "phone":                        phone,
        "date_of_birth":                dob.isoformat(),
        "gender":                       gender,
        "pan_number":                   pan_number,
        "aadhaar_hash":                 aadhaar_hash,
        "employment_type":              employment_type,
        "employer_id":                  employer_id,
        "employer_name":                employer_name,
        "monthly_income":               monthly_income,
        "expected_salary_day":          expected_salary_day,
        "state":                        state,
        "city":                         city,
        "pincode":                      pincode,
        "geography_risk_tier":          geo_risk_tier,
        "customer_segment":             segment,
        "account_id":                   account_id,
        "account_number":               account_number,
        "account_type":                 "SAVINGS" if segment != "SME" else
rng.choice(["SAVINGS", "CURRENT"]),
        "account_open_date":            account_open_date.isoformat(),
        "customer_vintage_months":      customer_vintage_months,
        "upi_vpa":                      upi_vpa,
        "ifsc_code":                    ifsc_code,
        "opening_balance":              opening_balance,
        "historical_delinquency_count": historical_delinquency_count,
        "credit_bureau_score":          credit_bureau_score,
        # Internal metadata used by transaction generator — not stored in DB
        "_bank_name":                   bank_name,
        "_bank_code":                   bank_code,
    }
# ── Loan Generator ────────────────────────────────────────────────────────────
def generate_loans_for_customer(
    customer: Dict[str, Any],
    rng: random.Random,
    np_rng: np.random.Generator,
) -> List[Dict[str, Any]]:
    """
    Generate 0–3 active loans for a customer based on their segment.
    Returns a list of dicts mapping to the loans table.
    FIX (Critical): days_past_due and failed_auto_debit_count_30d are now
    derived from _customer_will_develop_stress(), which uses the same
    hash-seed as RawTransactionGenerator.  This ensures the loans table
    and the transaction stream always agree on who is stressed.
    """
    segment  = customer["customer_segment"]
    loan_cfg = LOAN_CONFIG[segment]
    if rng.random() > loan_cfg["prob_has_loan"]:
        return []
    n_loans = rng.randint(1, loan_cfg["max_loans"])
    loan_type_weights = LOAN_TYPE_WEIGHTS[segment]
    loan_types = rng.choices(
        list(loan_type_weights.keys()),
        weights=list(loan_type_weights.values()),
        k=n_loans,
    )
    # Deduplicate — a customer can't have two home loans
    loan_types = list(dict.fromkeys(loan_types))[:n_loans]
    loans          = []
    today          = date.today()
    bank_code      = customer["_bank_code"]
    monthly_income = customer["monthly_income"]
    # ── FIX: Determine stress ONCE per customer using the shared deterministic
    #         function.  All loans for this customer get consistent DPD and
    #         failed_auto_debit values that mirror the transaction generator.
    develops_stress = _customer_will_develop_stress(customer["customer_id"])
    for loan_type in loan_types:
        seq = _next_loan_sequence()
        # Disbursement date: 1–5 years ago
        disb_days_ago     = rng.randint(365, 5 * 365)
        disbursement_date = today - timedelta(days=disb_days_ago)
        # Loan amount based on type and income
        amount_multipliers = {
            "HOME":        (30, 60),
            "PERSONAL":    (3,  8),
            "AUTO":        (8,  18),
            "EDUCATION":   (5,  15),
            "BUSINESS":    (10, 30),
            "CREDIT_CARD": (1,  3),
        }
        lo, hi = amount_multipliers[loan_type]
        sanctioned_amount = round(float(np_rng.uniform(
            monthly_income * lo, monthly_income * hi
        )) / 1000) * 1000
        # Tenure (months)
        tenure_map = {
            "HOME":        rng.choice([120, 180, 240]),
            "PERSONAL":    rng.choice([12, 24, 36, 48, 60]),
            "AUTO":        rng.choice([36, 48, 60, 72]),
            "EDUCATION":   rng.choice([60, 84, 120]),
            "BUSINESS":    rng.choice([24, 36, 48, 60]),
            "CREDIT_CARD": rng.choice([6, 12, 18, 24]),
        }
        tenure_months = tenure_map[loan_type]
        # Interest rate (annual %)
        rate_map = {
            "HOME":        (8.5,  9.5),
            "PERSONAL":    (12.0, 18.0),
            "AUTO":        (8.0,  11.0),
            "EDUCATION":   (8.5,  11.0),
            "BUSINESS":    (11.0, 16.0),
            "CREDIT_CARD": (36.0, 42.0),
        }
        r_lo, r_hi    = rate_map[loan_type]
        interest_rate = round(float(np_rng.uniform(r_lo, r_hi)), 2)
        # EMI: M = P × r(1+r)^n / ((1+r)^n − 1)
        r_monthly = interest_rate / (12 * 100)
        if r_monthly > 0:
            emi  = sanctioned_amount * r_monthly * (1 + r_monthly) ** tenure_months
            emi /= ((1 + r_monthly) ** tenure_months - 1)
        else:
            emi = sanctioned_amount / tenure_months
        emi = round(emi)
        # Remaining tenure and outstanding principal
        months_elapsed        = disb_days_ago // 30
        remaining_tenure      = max(1, tenure_months - months_elapsed)
        pct_remaining         = remaining_tenure / tenure_months
        outstanding_principal = round(sanctioned_amount * pct_remaining * float(
            np_rng.uniform(0.85, 0.98)
        ))
        # ── FIX: DPD and failed_auto_debit_count_30d are now stress-conditioned.
        #
        #   BEFORE (broken): dpd was drawn from a global rng independent of the
        #   transaction generator.  failed_auto_debit_count_30d was always 0,
        #   making half the label formula dead code.
        #
        #   AFTER (fixed): both values reflect the customer's actual stress state
        #   as determined by _customer_will_develop_stress(), which uses the same
        #   hash-seed as RawTransactionGenerator._develops_stress.
        if develops_stress:
            # Stressed customers: DPD >= 1, failed debits >= 2
            # Distributions are realistic for early-delinquency detection
            dpd = int(np_rng.choice(
                [1, 5, 10, 15, 30],
                p=[0.40, 0.25, 0.20, 0.10, 0.05],
            ))
            failed_auto_debit = int(np_rng.choice(
                [2, 3, 4, 5],
                p=[0.50, 0.25, 0.15, 0.10],
            ))
        else:
            # Healthy customers: perfect payment history
            dpd = 0
            failed_auto_debit = 0
        emi_due_date        = rng.choice([1, 5, 7, 10, 15, 20, 25, 28])
        loan_account_number = generate_loan_account_number(
            bank_code, loan_type, disbursement_date.year, seq
        )
        nach_vpa = generate_nach_vpa(bank_code, loan_account_number)
        loans.append({
            "loan_id":                     str(uuid.uuid4()),
            "loan_account_number":         loan_account_number,
            "customer_id":                 customer["customer_id"],
            "loan_type":                   loan_type,
            "sanctioned_amount":           sanctioned_amount,
            "outstanding_principal":       outstanding_principal,
            "emi_amount":                  emi,
            "emi_due_date":                emi_due_date,
            "interest_rate":               interest_rate,
            "tenure_months":               tenure_months,
            "remaining_tenure":            remaining_tenure,
            "disbursement_date":           disbursement_date.isoformat(),
            "days_past_due":               dpd,
            "failed_auto_debit_count_30d": failed_auto_debit,
            "nach_vpa":                    nach_vpa,
            "nach_rrn_prefix":             f"NACH{bank_code}",
            "status":                      "ACTIVE",
        })
    return loans
# ── Credit Card Generator ─────────────────────────────────────────────────────
def generate_credit_card_for_customer(
    customer: Dict[str, Any],
    rng: random.Random,
    np_rng: np.random.Generator,
) -> Optional[Dict[str, Any]]:
    """
    Generate a credit card for a customer, or None if they don't qualify.
    Probability varies by segment.
    """
    segment = customer["customer_segment"]
    if rng.random() > CREDIT_CARD_PROB[segment]:
        return None
    seq            = _next_loan_sequence()
    bank_code      = customer["_bank_code"]
    today          = date.today()
    monthly_income = customer["monthly_income"]
    # Credit limit
    limit_multipliers = {
        "RETAIL":       (1.0, 4.0),
        "HNI":          (3.0, 10.0),
        "SME":          (2.0, 6.0),
        "MICROFINANCE": (0.5, 1.5),
    }
    lo, hi = limit_multipliers[segment]
    credit_limit = round(float(np_rng.uniform(
        monthly_income * lo, monthly_income * hi
    )) / 1000) * 1000
    # Current utilisation (beta distribution — skewed low)
    utilisation_pct        = float(np_rng.beta(2, 5)) * 100
    current_balance        = round(credit_limit * utilisation_pct / 100)
    credit_utilization_pct = round(utilisation_pct, 2)
    min_payment_due          = round(max(current_balance * 0.05, 200))
    min_payment_made         = rng.random() > 0.20  # 80% pay more than minimum
    bureau_enquiry_count_90d = int(np_rng.choice([0, 1, 2, 3], p=[0.60, 0.25, 0.10, 0.05]))
    card_account_number = generate_loan_account_number(
        bank_code, "CREDIT_CARD", today.year, seq
    )
    return {
        "card_id":                   str(uuid.uuid4()),
        "card_account_number":       card_account_number,
        "customer_id":               customer["customer_id"],
        "credit_limit":              credit_limit,
        "current_balance":           current_balance,
        "credit_utilization_pct":    credit_utilization_pct,
        "min_payment_due":           min_payment_due,
        "min_payment_made":          min_payment_made,
        "bureau_enquiry_count_90d":  bureau_enquiry_count_90d,
        "payment_due_date":          rng.choice([5, 10, 15, 20, 25]),
        "status":                    "ACTIVE",
    }
# ── Main Entry Point ──────────────────────────────────────────────────────────
def generate_all_customers(
    n: Optional[int] = None,
    seed: int = 42,
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """
    Generate N customers with their loans and credit cards.
    Args:
        n:    Number of customers. Defaults to settings.NUM_CUSTOMERS.
        seed: Random seed for reproducibility.
    Returns:
        (customers, all_loans, all_credit_cards)
    """
    if n is None:
        n = settings.NUM_CUSTOMERS
    rng    = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    _reset_sequence()
    customers        = []
    all_loans        = []
    all_credit_cards = []
    for i in range(n):
        customer    = generate_customer(rng, np_rng, sequence_id=i + 1)
        loans       = generate_loans_for_customer(customer, rng, np_rng)
        credit_card = generate_credit_card_for_customer(customer, rng, np_rng)
        customers.append(customer)
        all_loans.extend(loans)
        if credit_card:
            all_credit_cards.append(credit_card)
    return customers, all_loans, all_credit_cards