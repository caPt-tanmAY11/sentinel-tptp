"""
data_generator/raw_transaction_generator.py
─────────────────────────────────────────────────────────────────────────────
Generates 120-day raw-fact transaction history for a customer.
RAW FACTS ONLY — no transaction_type label on any row.
Purpose is encoded in sender_id / receiver_id / platform patterns.
Structure of the 120-day window:
  Days 1–90  (BASELINE WINDOW):
    - Normal, healthy patterns
    - Salary arrives on time
    - EMIs paid successfully via NACH
    - Steady balance, normal spending
  Days 91–120 (REAL-TIME WINDOW):
    - For ~28% of customers: gradually worsening patterns
      * Salary 2–7 days late (same sender, just delayed); for near-month-end
        customers the salary may not arrive at all that month — a strong signal
      * 1–2 failed NACH payments (payment_status = 'failed')
      * 1–3 transfers to lending app VPAs
      * Declining balance trajectory
    - For remaining ~72%: continued normal patterns
  STRESS SYNC CONTRACT:
    STRESS_PREVALENCE must be identical here and in customer_generator.py.
    The _develops_stress flag is rolled as the FIRST call on self.rng
    (which is seeded from hash(customer_id)).  customer_generator.py's
    _customer_will_develop_stress() replicates this exactly so that the
    loans table and the transaction stream are always in sync.
The model must DISCOVER which customers show stress.
Nothing is labeled. Nothing is flagged.
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
import random
import string
from datetime import datetime, timedelta, timezone, date
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from config.settings import (
    get_settings,
    UPI_LENDING_APP_VPAS,
    BBPS_UTILITY_VPAS,
)
from data_generator.indian_names import (
    generate_reference_number,
    get_payroll_vpa,
    generate_nach_vpa,
    PAYROLL_VPA_PATTERNS,
)
settings = get_settings()
# ── Stress prevalence — MUST match customer_generator.py exactly ─────────────
# ⚠️  SYNC RULE: If you change this constant you MUST change the identical
#     constant in data_generator/customer_generator.py simultaneously.
#     Raised from 0.15 → 0.28:
#       • 28 % stressed / 72 % healthy gives the model adequate positive
#         examples to learn from (≥ 50 per 200-customer batch typical).
#       • Consistent with RBI NPA rates in retail portfolios (~8–12 %
#         early-stage stress proxy at ×2–3× for stress detection purposes).
STRESS_PREVALENCE = 0.28
# ── Merchant VPA pools ────────────────────────────────────────────────────────
GROCERY_VPAS = [
    ("bigbasket@okaxis",     "BigBasket"),
    ("blinkit@icicibank",    "Blinkit"),
    ("dmartrewards@upi",     "DMart"),
    ("jiomart@upi",          "JioMart"),
    ("swiggyinstamart@ybl",  "Swiggy Instamart"),
]
FOOD_DELIVERY_VPAS = [
    ("swiggy@icicibank",     "Swiggy"),
    ("zomato@axl",           "Zomato"),
    ("eatsure@ybl",          "EatSure"),
    ("dunzo@okaxis",         "Dunzo"),
]
FUEL_VPAS = [
    ("hpcl@upi",             "HPCL Petrol Pump"),
    ("iocl@upi",             "IOCL Fuel Station"),
    ("bpcl@okaxis",          "BPCL Fuel"),
    ("reliancepetro@ybl",    "Reliance Petro"),
]
OTT_VPAS = [
    ("netflix@ybl",          "Netflix India"),
    ("primevideo@okaxis",    "Amazon Prime Video"),
    ("hotstar@icicibank",    "Disney+ Hotstar"),
    ("spotify@okicici",      "Spotify India"),
]
ATM_LOCATION_CODES = [
    "ATM_MUM_ANDHERI_001",  "ATM_MUM_BANDRA_002",  "ATM_MUM_THANE_003",
    "ATM_DEL_CONNAUGHT_001","ATM_BLR_KORAMANGALA_001","ATM_HYD_HITECH_001",
    "ATM_CHN_TNNAGAR_001",  "ATM_PUN_KOTHRUD_001", "ATM_KOL_SALTLAKE_001",
    "ATM_AHM_SATELLITE_001",
]
ECOMMERCE_VPAS = [
    ("flipkart@axisbank",    "Flipkart"),
    ("amazon@axisbank",      "Amazon India"),
    ("myntra@upi",           "Myntra"),
    ("meesho@okaxis",        "Meesho"),
    ("nykaa@ybl",            "Nykaa"),
]
HEALTHCARE_VPAS = [
    ("apollopharmacy@upi",   "Apollo Pharmacy"),
    ("medplus@okaxis",       "MedPlus"),
    ("1mghealth@ybl",        "1mg Health"),
    ("netmeds@icicibank",    "Netmeds"),
]
class RawTransactionGenerator:
    """
    Generates a realistic raw transaction stream for one customer
    over a 120-day window.
    All outputs are raw facts — sender/receiver VPAs, platform, amount,
    balance before/after. No transaction_type label anywhere.
    """
    def __init__(
        self,
        customer: Dict[str, Any],
        loans: List[Dict[str, Any]],
        credit_card: Optional[Dict[str, Any]],
        seed: Optional[int] = None,
    ):
        self.customer = customer
        self.loans = loans
        self.credit_card = credit_card
        self.customer_id = customer["customer_id"]
        self.account_number = customer["account_number"]
        self.upi_vpa = customer["upi_vpa"]
        self.monthly_income = customer["monthly_income"]
        self.employment_type = customer["employment_type"]
        self.employer_name = customer.get("employer_name")
        self.expected_salary_day = customer.get("expected_salary_day", 1)
        self.segment = customer["customer_segment"]
        # Seeded RNG for reproducibility
        self.rng = random.Random(seed or hash(self.customer_id) % (2**31))
        self.np_rng = np.random.default_rng(seed or hash(self.customer_id) % (2**31))
        # Running balance state — starts at opening_balance
        self.current_balance = float(customer.get("opening_balance", self.monthly_income * 3))
        # ── FIX: Stress flag uses STRESS_PREVALENCE constant (was hardcoded 0.15).
        #
        #   CRITICAL ORDERING CONSTRAINT:
        #   This must be the FIRST call on self.rng after __init__ so that
        #   customer_generator._customer_will_develop_stress(), which creates a
        #   fresh random.Random(same_seed) and calls .random() once, produces the
        #   IDENTICAL boolean.  Never insert any other self.rng call above this line.
        self._develops_stress = self.rng.random() < STRESS_PREVALENCE

        # ── Noise flags for realistic data (anti-overfitting) ─────────────────
        # ~8% of healthy customers occasionally show stress-like behaviour
        # (e.g. one missed EMI, one lending app txn) — mimics real-world noise.
        self._noisy_normal = (
            not self._develops_stress
            and self.rng.random() < 0.08
        )
        # ~15% of stressed customers are "partial" — they skip some stress
        # signals (no lending app usage OR normal ATM patterns).  This prevents
        # the model from trivially separating classes by requiring ALL signals.
        self._partial_stress = (
            self._develops_stress
            and self.rng.random() < 0.15
        )
        # Partial-stress customers randomly drop some signal categories
        if self._partial_stress:
            self._skip_lending = self.rng.random() < 0.5
            self._skip_atm_spike = self.rng.random() < 0.5
            self._skip_salary_delay = self.rng.random() < 0.3
        else:
            self._skip_lending = False
            self._skip_atm_spike = False
            self._skip_salary_delay = False

    # ── Public API ────────────────────────────────────────────────────────────
    def generate(self, days_back: int = 120) -> List[Dict[str, Any]]:
        """
        Generate all transactions for the full history window.
        Returns:
            List of transaction dicts ready for DB insertion.
            Each dict maps directly to the transactions table columns.
        """
        transactions = []
        now = datetime.now(timezone.utc)
        start_dt = now - timedelta(days=days_back)
        # Baseline window: days 1–90
        baseline_end = days_back - 30
        for day_offset in range(days_back):
            current_dt = start_dt + timedelta(days=day_offset)
            day_of_month = current_dt.day
            # Is this in the stress window (last 30 days)?
            in_stress_window = (
                self._develops_stress
                and day_offset >= baseline_end
            )
            # ── FIX: Stress intensity floor at 0.25 (was 0.0).
            #
            #   BEFORE (broken): intensity = ramp (0.0 → 1.0 over 30 days).
            #   With thresholds like > 0.5 for NACH failures, the first 15 days
            #   of the stress window produced zero distinguishable signals —
            #   making 50 % of stress-window transactions indistinguishable from
            #   healthy ones.
            #
            #   AFTER (fixed): intensity = 0.25 + 0.75 × ramp (0.25 → 1.0).
            #   Stress signals are visible from day 1 of the window; the model
            #   gets clean positive examples across the full 30-day window.
            stress_intensity = 0.0
            if in_stress_window:
                ramp = (day_offset - baseline_end) / 30.0
                stress_intensity = 0.25 + 0.75 * ramp   # floor: 0.25, ceiling: 1.0
            # ── Salary / income credit ──────────────────────────────────────
            salary_txns = self._generate_income_credit(
                current_dt, day_of_month, stress_intensity
            )
            transactions.extend(salary_txns)
            # ── EMI / NACH auto-debits ──────────────────────────────────────
            for loan in self.loans:
                emi_txns = self._generate_emi_debit(
                    current_dt, day_of_month, loan, stress_intensity
                )
                transactions.extend(emi_txns)
            # ── Utility bill payments ───────────────────────────────────────
            if day_of_month in (1, 2, 3, 4, 5):
                utility_txns = self._generate_utility_payment(current_dt)
                transactions.extend(utility_txns)
            # ── Daily spending ──────────────────────────────────────────────
            spending_txns = self._generate_daily_spending(
                current_dt, stress_intensity
            )
            transactions.extend(spending_txns)
            # ── ATM withdrawals ─────────────────────────────────────────────
            # For partial-stress customers who skip ATM spikes, pass 0 intensity
            atm_intensity = stress_intensity
            if self._skip_atm_spike and in_stress_window:
                atm_intensity = 0.0
            atm_txns = self._generate_atm_withdrawal(
                current_dt, atm_intensity
            )
            transactions.extend(atm_txns)
            # ── Lending app transfers (stress signal, last 30 days only) ────
            # FIX: Threshold lowered from > 0.2 to > 0.10 so transfers appear
            # earlier in the stress window (from day 1, not day 6).
            # Partial-stress customers who skip lending: no transfers
            if (in_stress_window and stress_intensity > 0.10
                    and not self._skip_lending):
                lending_txns = self._generate_lending_app_transfer(
                    current_dt, stress_intensity
                )
                transactions.extend(lending_txns)
            # ── Noisy normal: occasional stress-like signals for healthy customers
            # ~8% of healthy customers produce sporadic stress signals — mimics
            # real-world noise where healthy people occasionally miss an EMI
            # or use a lending app once.
            if (self._noisy_normal and not in_stress_window
                    and day_offset >= baseline_end):
                # One-off lending app transfer (rare: ~5% of days)
                if self.rng.random() < 0.05:
                    lending_txns = self._generate_lending_app_transfer(
                        current_dt, 0.2  # low intensity
                    )
                    transactions.extend(lending_txns)
        return transactions
    # ── Income / Salary Credit ────────────────────────────────────────────────
    def _generate_income_credit(
        self,
        current_dt: datetime,
        day_of_month: int,
        stress_intensity: float,
    ) -> List[Dict]:
        """
        Generate salary or business income credit.
        Salaried: NEFT from employer payroll VPA on expected_salary_day.
        Self-employed / business: irregular IMPS credits throughout month.
        Retired: pension credit on day 5 via NEFT.
        Stress signal: salary arrives late (same sender, just later day).
        FIX (Bug 6 — Salary wrap for near-month-end customers):
          BEFORE: actual_salary_day > 28 was clamped to 28, meaning a customer
          with expected_salary_day=28 and delay=3 would get salary on day 28 —
          hiding the lateness entirely.
          AFTER: if the delayed day exceeds 28 (i.e., salary would fall in the
          next calendar month), we simply do NOT generate the salary this month.
          A missed salary is a far stronger stress signal than a masked-late one.
        """
        txns = []
        if self.employment_type == "SALARIED":
            # Base salary day; under stress, arrives 2–7 days late
            delay = 0
            if stress_intensity > 0.3 and not self._skip_salary_delay:
                delay = self.rng.randint(2, min(7, int(stress_intensity * 10)))
            actual_salary_day = self.expected_salary_day + delay
            # FIX: If stress pushes salary past month end, it doesn't arrive
            # this month — the missing credit is itself a detectable stress signal.
            # Previously this was clamped to 28, masking the lateness for
            # customers whose expected_salary_day >= 22.
            if actual_salary_day > 28:
                return txns   # salary missed this month (stress signal)
            if day_of_month != actual_salary_day:
                return txns
            payroll_vpa = get_payroll_vpa(self.employer_name or "Unknown Employer")
            employer_display = self.employer_name or "Employer Payroll"
            # Salary amount: 95–105% of monthly income (small variation)
            salary_amount = round(
                self.monthly_income * self.np_rng.uniform(0.95, 1.05)
            )
            # Under high stress: partial salary (80–95%)
            if stress_intensity > 0.7 and self.rng.random() < 0.3:
                salary_amount = round(self.monthly_income * self.np_rng.uniform(0.80, 0.95))
            ref = generate_reference_number("NEFT", self.rng)
            txns.append(self._build_txn(
                current_dt=current_dt,
                sender_id=payroll_vpa,
                sender_name=f"{employer_display} Payroll",
                receiver_id=self.account_number,
                receiver_name=f"{self.customer['first_name']} {self.customer['last_name']}",
                amount=salary_amount,
                platform="NEFT",
                payment_status="success",
                reference_number=ref,
                is_credit=True,
            ))
        elif self.employment_type == "RETIRED":
            if day_of_month != self.expected_salary_day:
                return txns
            pension_amount = round(self.monthly_income * self.np_rng.uniform(0.97, 1.03))
            txns.append(self._build_txn(
                current_dt=current_dt,
                sender_id="cgg_pension@neft",
                sender_name="Government Pension Cell",
                receiver_id=self.account_number,
                receiver_name=f"{self.customer['first_name']} {self.customer['last_name']}",
                amount=pension_amount,
                platform="NEFT",
                payment_status="success",
                reference_number=generate_reference_number("NEFT", self.rng),
                is_credit=True,
            ))
        else:
            # SELF_EMPLOYED / BUSINESS_OWNER: 3–5 income credits spread through month
            # Appears on days 3, 8, 15, 22, 28 roughly
            income_days = [3, 8, 15, 22, 28]
            if day_of_month not in income_days:
                return txns
            if self.rng.random() > 0.6:  # not every business income day has a credit
                return txns
            chunk = round(
                (self.monthly_income / len(income_days)) * self.np_rng.uniform(0.6, 1.4)
            )
            txns.append(self._build_txn(
                current_dt=current_dt,
                sender_id=f"client_{self.rng.randint(100,999)}@okaxis",
                sender_name="Business Client Payment",
                receiver_id=self.account_number,
                receiver_name=f"{self.customer['first_name']} {self.customer['last_name']}",
                amount=max(chunk, 1000),
                platform="IMPS",
                payment_status="success",
                reference_number=generate_reference_number("IMPS", self.rng),
                is_credit=True,
            ))
        return txns
    # ── EMI / NACH Auto-debit ─────────────────────────────────────────────────
    def _generate_emi_debit(
        self,
        current_dt: datetime,
        day_of_month: int,
        loan: Dict,
        stress_intensity: float,
    ) -> List[Dict]:
        """
        Generate EMI auto-debit via NACH.
        Stress signal: payment_status = 'failed' under high stress.
        The receiver_id is the loan's NACH VPA — classifiable by the classifier.
        FIX (Bug 5 — NACH failure window too narrow):
          BEFORE: failed = stress_intensity > 0.5 and rng < (intensity * 0.6)
          At intensity=0.25 (day 1 of stress window), this NEVER fired.
          At intensity=0.5 (day 15), it fired with probability 0.
          Only in the final ~10 days were failures possible.
          AFTER: threshold lowered to > 0.15, probability formula raised to
          min(0.90, intensity * 0.85 + 0.10).
          At intensity=0.25 (day 1): fires with p ≈ 0.31.
          At intensity=1.0 (day 30): fires with p ≈ 0.90.
          The full 30-day stress window now produces detectable NACH failures.
        """
        txns = []
        emi_due_date = loan.get("emi_due_date", 5)
        if day_of_month != emi_due_date:
            return txns
        emi_amount = float(loan["emi_amount"])
        nach_vpa = loan.get("nach_vpa", f"NACH_EMI_{loan['loan_id'][:8]}@nach")
        loan_ref = loan.get("loan_account_number", loan["loan_id"][:12])
        # FIX: NACH failure threshold lowered from > 0.5 to > 0.15
        # Probability raised from (intensity * 0.6) to min(0.90, intensity * 0.85 + 0.10)
        failed = (
            stress_intensity > 0.15
            and self.rng.random() < min(0.90, stress_intensity * 0.85 + 0.10)
        )
        # Noisy normal: ~10% chance of a single EMI failure in RT window
        # (mimics real-world occasional bounce for healthy customers)
        if self._noisy_normal and stress_intensity == 0.0 and self.rng.random() < 0.10:
            failed = True
        status = "failed" if failed else "success"
        ref = generate_reference_number("NACH", self.rng)
        txn = self._build_txn(
            current_dt=current_dt,
            sender_id=self.account_number,
            sender_name=f"{self.customer['first_name']} {self.customer['last_name']}",
            receiver_id=nach_vpa,
            receiver_name=f"EMI Auto-debit {loan_ref}",
            amount=emi_amount,
            platform="NACH",
            payment_status=status,
            reference_number=ref,
            is_credit=False,
            force_failed=(status == "failed"),
        )
        txns.append(txn)
        # If failed, a retry may happen 2–3 days later (sometimes succeeds)
        if failed and self.rng.random() < 0.4:
            retry_dt = current_dt + timedelta(days=self.rng.randint(2, 3))
            retry_status = "success" if self.rng.random() < 0.5 else "failed"
            retry_txn = self._build_txn(
                current_dt=retry_dt,
                sender_id=self.account_number,
                sender_name=f"{self.customer['first_name']} {self.customer['last_name']}",
                receiver_id=nach_vpa,
                receiver_name=f"EMI Retry {loan_ref}",
                amount=emi_amount,
                platform="NACH",
                payment_status=retry_status,
                reference_number=generate_reference_number("NACH", self.rng),
                is_credit=False,
                force_failed=(retry_status == "failed"),
            )
            txns.append(retry_txn)
        return txns
    # ── Utility Payments ──────────────────────────────────────────────────────
    def _generate_utility_payment(self, current_dt: datetime) -> List[Dict]:
        """
        Generate utility bill payments via BBPS.
        Receiver VPA is a BBPS biller (bescom@bbps, tatapower@bbps, etc.).
        """
        txns = []
        # 70% chance of a utility payment in the first 5 days of month
        if self.rng.random() > 0.70:
            return txns
        biller_vpa, biller_name = self.rng.choice(BBPS_UTILITY_VPAS), ""
        # Find display name for the biller
        biller_display_map = {
            "bescom@bbps": "BESCOM Electricity",
            "tatapower@bbps": "Tata Power",
            "adanigas@bbps": "Adani Gas",
            "bsnl@bbps": "BSNL Broadband",
            "airtel@bbps": "Airtel",
            "jio@bbps": "Jio",
            "mahanagar@bbps": "Mahanagar Gas",
            "torrentpower@bbps": "Torrent Power",
            "mseb@bbps": "MSEB Electricity",
            "tneb@bbps": "TNEB Electricity",
            "cesc@bbps": "CESC Power",
            "dgvcl@bbps": "DGVCL",
            "pgvcl@bbps": "PGVCL",
        }
        biller_name = biller_display_map.get(biller_vpa, biller_vpa)
        # Utility amount: ₹500 – ₹5,000 depending on segment
        base_amount = {
            "RETAIL": (500, 2500),
            "HNI": (2000, 8000),
            "SME": (1000, 6000),
            "MICROFINANCE": (200, 1200),
        }
        lo, hi = base_amount.get(self.segment, (500, 2500))
        amount = round(float(self.np_rng.uniform(lo, hi)) / 10) * 10
        txns.append(self._build_txn(
            current_dt=current_dt,
            sender_id=self.upi_vpa,
            sender_name=f"{self.customer['first_name']} {self.customer['last_name']}",
            receiver_id=biller_vpa,
            receiver_name=biller_name,
            amount=amount,
            platform="BBPS",
            payment_status="success",
            reference_number=generate_reference_number("UPI", self.rng),
            is_credit=False,
        ))
        return txns
    # ── Daily Spending ────────────────────────────────────────────────────────
    def _generate_daily_spending(
        self,
        current_dt: datetime,
        stress_intensity: float,
    ) -> List[Dict]:
        """
        Generate 0–4 daily UPI / POS spending transactions.
        Categories: grocery, food delivery, e-commerce, fuel, OTT, healthcare.
        Stress signal: discretionary spending (food delivery, e-commerce) increases
        while grocery spend decreases — behavioral shift the model should detect.
        """
        txns = []
        # Base number of transactions per day by segment
        base_txn_counts = {
            "RETAIL":       (1, 3),
            "HNI":          (2, 5),
            "SME":          (1, 4),
            "MICROFINANCE": (0, 2),
        }
        lo, hi = base_txn_counts.get(self.segment, (1, 3))
        n_txns = self.rng.randint(lo, hi)
        for _ in range(n_txns):
            category = self._choose_spending_category(stress_intensity)
            if category == "grocery":
                vpa, name = self.rng.choice(GROCERY_VPAS)
                amount = round(float(self.np_rng.uniform(200, 1500)))
            elif category == "food_delivery":
                vpa, name = self.rng.choice(FOOD_DELIVERY_VPAS)
                amount = round(float(self.np_rng.uniform(150, 800)))
            elif category == "fuel":
                vpa, name = self.rng.choice(FUEL_VPAS)
                amount = round(float(self.np_rng.uniform(500, 3000)) / 10) * 10
            elif category == "ecommerce":
                vpa, name = self.rng.choice(ECOMMERCE_VPAS)
                amount = round(float(self.np_rng.uniform(300, 5000)))
            elif category == "ott":
                vpa, name = self.rng.choice(OTT_VPAS)
                # OTT subscriptions: fixed monthly amounts (₹149–₹1499)
                amount = self.rng.choice([149, 199, 299, 499, 649, 999, 1499])
            elif category == "healthcare":
                vpa, name = self.rng.choice(HEALTHCARE_VPAS)
                amount = round(float(self.np_rng.uniform(100, 2000)))
            else:
                # Generic UPI transfer
                vpa = f"merchant{self.rng.randint(100,9999)}@upi"
                name = "Merchant Payment"
                amount = round(float(self.np_rng.uniform(100, 2000)))
            platform = self.rng.choice(["UPI", "UPI", "UPI", "POS"])
            txns.append(self._build_txn(
                current_dt=current_dt + timedelta(
                    hours=self.rng.randint(8, 22),
                    minutes=self.rng.randint(0, 59),
                ),
                sender_id=self.upi_vpa,
                sender_name=f"{self.customer['first_name']} {self.customer['last_name']}",
                receiver_id=vpa,
                receiver_name=name,
                amount=amount,
                platform=platform,
                payment_status="success",
                reference_number=generate_reference_number("UPI", self.rng),
                is_credit=False,
            ))
        return txns
    def _choose_spending_category(self, stress_intensity: float) -> str:
        """
        Category distribution shifts under stress:
        Normal:  grocery 40%, food_delivery 20%, fuel 10%, ecommerce 15%, ott 5%, healthcare 10%
        Stressed: grocery 20%, food_delivery 35%, fuel 8%, ecommerce 22%, ott 5%, healthcare 10%
        """
        if stress_intensity < 0.3:
            weights = [40, 20, 10, 15, 5, 10]
        else:
            # Discretionary spending increases, grocery decreases
            shift = stress_intensity
            weights = [
                max(5,  int(40 - shift * 20)),  # grocery: drops
                min(45, int(20 + shift * 15)),  # food_delivery: rises
                10,                              # fuel: stable
                min(30, int(15 + shift * 10)),  # ecommerce: rises
                5,                               # ott: stable
                10,                              # healthcare: stable
            ]
        categories = ["grocery", "food_delivery", "fuel", "ecommerce", "ott", "healthcare"]
        return self.rng.choices(categories, weights=weights, k=1)[0]
    # ── ATM Withdrawals ───────────────────────────────────────────────────────
    def _generate_atm_withdrawal(
        self,
        current_dt: datetime,
        stress_intensity: float,
    ) -> List[Dict]:
        """
        Generate ATM cash withdrawals.
        Stress signal: frequency and amount increase under stress
        (cash preferred when credit is tight / trying to avoid digital trail).
        """
        txns = []
        # Base probability of ATM withdrawal on any given day
        base_prob = {"RETAIL": 0.08, "HNI": 0.05, "SME": 0.06, "MICROFINANCE": 0.12}
        prob = base_prob.get(self.segment, 0.08)
        # Stress increases ATM usage
        prob = min(0.40, prob + stress_intensity * 0.20)
        if self.rng.random() > prob:
            return txns
        atm_location = self.rng.choice(ATM_LOCATION_CODES)
        base_amounts = {
            "RETAIL":       (500,  5000),
            "HNI":          (2000, 20000),
            "SME":          (1000, 10000),
            "MICROFINANCE": (200,  2000),
        }
        lo, hi = base_amounts.get(self.segment, (500, 5000))
        # Stress: larger withdrawals (urgency)
        if stress_intensity > 0.5:
            hi = min(int(hi * 1.3), 50000)  # Reduced from 2x to 1.3x amplification
        amount = round(float(self.np_rng.uniform(lo, hi)) / 100) * 100
        txns.append(self._build_txn(
            current_dt=current_dt + timedelta(
                hours=self.rng.randint(9, 21),
                minutes=self.rng.randint(0, 59),
            ),
            sender_id=atm_location,
            sender_name=f"ATM Withdrawal {atm_location}",
            receiver_id=self.account_number,
            receiver_name=f"{self.customer['first_name']} {self.customer['last_name']}",
            amount=amount,
            platform="ATM",
            payment_status="success",
            reference_number=generate_reference_number("ATM", self.rng),
            is_credit=False,   # ATM withdrawal reduces balance
        ))
        return txns
    # ── Lending App Transfers (Stress Signal) ─────────────────────────────────
    def _generate_lending_app_transfer(
        self,
        current_dt: datetime,
        stress_intensity: float,
    ) -> List[Dict]:
        """
        Generate UPI transfers to known lending app VPAs.
        This is the strongest stress signal.
        Only generated in the last 30 days for stressed customers.
        The receiver_id matches patterns in UPI_LENDING_APP_VPAS.
        The transaction classifier will detect this from the VPA pattern alone.
        FIX: Probability formula raised from (intensity * 0.25) to
        min(0.55, intensity * 0.50 + 0.05) so transfers appear meaningfully
        often from early in the stress window, not just in the final days.
        """
        txns = []
        # FIX: Probability raised — previously intensity * 0.25 meant only
        # ~6% chance at the start of the stress window (intensity ≈ 0.25).
        # Now: min(0.55, intensity * 0.50 + 0.05)
        #   intensity=0.25 → p ≈ 0.175
        #   intensity=1.00 → p ≈ 0.550
        prob = min(0.55, stress_intensity * 0.50 + 0.05)
        if self.rng.random() > prob:
            return txns
        # Pick a lending app VPA from config
        app_patterns = UPI_LENDING_APP_VPAS
        pattern = self.rng.choice(app_patterns)
        # Build full VPA from partial pattern
        vpa_map = {
            "slice@":        ("slice@upi",         "Slice Fintech Pvt Ltd"),
            "lazypay@":      ("lazypay@upi",        "LazyPay (PayU Finance)"),
            "simpl@":        ("simpl@upi",          "Simpl Technologies"),
            "postpe@":       ("postpe@icicibank",   "PostPe (BharatPe)"),
            "kissht@":       ("kissht@upi",         "Kissht (OnEMi)"),
            "zestmoney@":    ("zestmoney@okaxis",   "ZestMoney Pvt Ltd"),
            "flexmoney@":    ("flexmoney@upi",      "FlexMoney"),
            "earlysalary@":  ("earlysalary@upi",    "EarlySalary (Fibe)"),
            "moneyview@":    ("moneyview@ybl",      "MoneyView Loans"),
            "navi@":         ("navi@hdfcbank",      "Navi Technologies"),
            "fibe@":         ("fibe@ybl",           "Fibe (EarlySalary)"),
            "cashe@":        ("cashe@upi",          "CASHe (Bhanix Finance)"),
            "kreditbee@":    ("kreditbee@upi",      "KreditBee"),
            "mpokket@":      ("mpokket@upi",        "mPokket"),
            "payrupik@":     ("payrupik@upi",       "PayRupik"),
            "stashfin@":     ("stashfin@icicibank", "Stashfin"),
            "ringplus@":     ("ringplus@upi",       "RingPlus Credit"),
            "smytten@":      ("smytten@okaxis",     "Smytten"),
        }
        # Fall back to building a VPA if pattern not in map
        if pattern in vpa_map:
            receiver_vpa, receiver_name = vpa_map[pattern]
        else:
            receiver_vpa = pattern + "upi"
            receiver_name = "Digital Lending App"
        # Transfer amounts: small to medium (₹2,000–₹25,000)
        # These are repayment transfers TO the app (paying back borrowed money)
        # OR receiving a loan disbursement FROM the app
        if self.rng.random() < 0.6:
            # Repayment (debit)
            amount = round(float(self.np_rng.uniform(2000, 15000)) / 100) * 100
            txns.append(self._build_txn(
                current_dt=current_dt + timedelta(
                    hours=self.rng.randint(10, 20),
                    minutes=self.rng.randint(0, 59),
                ),
                sender_id=self.upi_vpa,
                sender_name=f"{self.customer['first_name']} {self.customer['last_name']}",
                receiver_id=receiver_vpa,
                receiver_name=receiver_name,
                amount=amount,
                platform="UPI",
                payment_status="success",
                reference_number=generate_reference_number("UPI", self.rng),
                is_credit=False,
            ))
        else:
            # Loan disbursement (credit to customer)
            amount = round(float(self.np_rng.uniform(5000, 25000)) / 100) * 100
            txns.append(self._build_txn(
                current_dt=current_dt + timedelta(
                    hours=self.rng.randint(10, 20),
                    minutes=self.rng.randint(0, 59),
                ),
                sender_id=receiver_vpa,
                sender_name=receiver_name,
                receiver_id=self.upi_vpa,
                receiver_name=f"{self.customer['first_name']} {self.customer['last_name']}",
                amount=amount,
                platform="UPI",
                payment_status="success",
                reference_number=generate_reference_number("UPI", self.rng),
                is_credit=True,
            ))
        return txns
    # ── Core Transaction Builder ──────────────────────────────────────────────
    def _build_txn(
        self,
        current_dt: datetime,
        sender_id: str,
        sender_name: str,
        receiver_id: str,
        receiver_name: str,
        amount: float,
        platform: str,
        payment_status: str,
        reference_number: str,
        is_credit: bool,
        force_failed: bool = False,
    ) -> Dict[str, Any]:
        """
        Build a transaction dict with balance tracking.
        Updates self.current_balance in place.
        """
        amount = max(1.0, round(float(amount), 2))
        balance_before = round(self.current_balance, 2)
        if force_failed or payment_status in ("failed", "reversed"):
            # Failed transactions do not change balance
            balance_after = balance_before
        elif is_credit:
            balance_after = round(balance_before + amount, 2)
            self.current_balance = balance_after
        else:
            # Debit: ensure balance doesn't go below 0
            # (in real banking it can go below via overdraft, but keep simple)
            balance_after = round(max(0.0, balance_before - amount), 2)
            self.current_balance = balance_after
        return {
            "transaction_id":  str(uuid.uuid4()),
            "customer_id":     self.customer_id,
            "account_number":  self.account_number,
            "sender_id":       sender_id[:150] if sender_id else None,
            "sender_name":     sender_name[:200] if sender_name else None,
            "receiver_id":     receiver_id[:150] if receiver_id else None,
            "receiver_name":   receiver_name[:200] if receiver_name else None,
            "amount":          amount,
            "platform":        platform,
            "payment_status":  payment_status,
            "reference_number": reference_number[:60] if reference_number else None,
            "balance_before":  balance_before,
            "balance_after":   balance_after,
            "txn_timestamp":   current_dt.isoformat(),
        }