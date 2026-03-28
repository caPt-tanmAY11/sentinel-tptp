"""
gig_worker/gig_realtime_injector.py
─────────────────────────────────────────────────────────────────────────────
Standalone real-time injector for gig worker profiles.

Completely independent of the main data_generator/realtime_injector.py.
Does NOT touch Kafka, existing customers, or any existing pipeline code.

What it does per worker
────────────────────────
  1. Generates a synthetic Indian gig worker profile filtered by worker_type.
  2. Inserts the profile into the `customers` table (employment_type=GIG_WORKER).
  3. Simulates 16 weeks of weekly platform payouts + daily spending transactions.
  4. Inserts all transactions into the `transactions` table.
  5. Extracts income features from the transaction history.
  6. Runs the GigStressClassifier to decide STRESSED / NOT_STRESSED.
  7. Persists the full assessment to `gig_worker_stress_assessments`.
  8. Prints a live status line per worker.

Prerequisites
─────────────
  • PostgreSQL running and `init.sql` applied.
  • `database/gig_worker_migration.sql` applied (creates assessment table).
  • pip install lightgbm scikit-learn psycopg2-binary  (or psycopg2)

Usage
─────
  # Inject 5 food delivery workers:
  python -m gig_worker.gig_realtime_injector --worker-type FOOD_DELIVERY --count 5

  # Inject 20 workers of random types:
  python -m gig_worker.gig_realtime_injector --worker-type all --count 20

  # Inject with 0.5-second pause between workers:
  python -m gig_worker.gig_realtime_injector --worker-type RIDE_SHARE --count 10 --tps 2

Valid --worker-type values:
  all  RIDE_SHARE  FOOD_DELIVERY  QUICK_COMMERCE
  HOME_SERVICES  LOGISTICS  FIELD_SERVICES  GENERAL_GIG  ECOMMERCE_RESELLER
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import os
import random
import string
import time
import uuid
from datetime import datetime, timezone, timedelta, date
from typing import List, Dict, Any, Optional, Tuple

import psycopg2
import psycopg2.extras

from config.settings import get_settings
from gig_worker.gig_worker_simulator import (
    GIG_PLATFORMS,
    WEEKLY_INCOME_BY_CATEGORY,
    FIRST_NAMES_MALE,
    FIRST_NAMES_FEMALE,
    LAST_NAMES,
    INDIAN_CITIES,
    GigWorkerProfile,
    WeeklyPayoutRecord,
    _generate_profile,
    _simulate_weekly_payouts,
    profiles_to_feature_records,
)
from gig_worker.gig_stress_classifier import GigStressClassifier, MODEL_PATH

settings = get_settings()

# ── Valid worker types ────────────────────────────────────────────────────────
VALID_WORKER_TYPES = [
    "all",
    "RIDE_SHARE",
    "FOOD_DELIVERY",
    "QUICK_COMMERCE",
    "HOME_SERVICES",
    "LOGISTICS",
    "FIELD_SERVICES",
    "GENERAL_GIG",
    "ECOMMERCE_RESELLER",
]

# ── Spending merchants (simple pool for gig worker daily transactions) ────────
# (receiver_id, receiver_name, amount_range, platform)
_SPEND_POOL: List[Tuple[str, str, Tuple[float, float], str]] = [
    ("zomato@axl",             "Zomato",                 (80,   600),  "UPI"),
    ("swiggy@icicibank",       "Swiggy",                 (80,   500),  "UPI"),
    ("bigbasket@okaxis",       "BigBasket",              (200, 1500),  "UPI"),
    ("blinkit@icicibank",      "Blinkit",                (100, 1000),  "UPI"),
    ("kirana_store@okaxis",    "Local Kirana Store",     (50,   400),  "UPI"),
    ("hpcl@upi",               "HPCL Petrol Pump",       (300, 1500),  "UPI"),
    ("iocl@upi",               "IOCL Fuel Station",      (300, 1500),  "UPI"),
    ("airtel@bbps",            "Airtel Recharge",        (149,  399), "BBPS"),
    ("jio@bbps",               "Jio Recharge",           (149,  299), "BBPS"),
    ("apollopharmacy@upi",     "Apollo Pharmacy",        (80,   800),  "UPI"),
    ("oladriver@upi",          "Ola Cab",                (60,   400),  "UPI"),
    ("uber@razorpay",          "Uber India",             (60,   450),  "UPI"),
    ("rapido@upi",             "Rapido Bike",            (25,   150),  "UPI"),
    ("amazon@axisbank",        "Amazon India",           (200, 2000),  "UPI"),
    ("flipkart@axisbank",      "Flipkart",               (200, 1500),  "UPI"),
    ("dmartrewards@upi",       "DMart",                  (300, 2000),  "UPI"),
    ("netflix@ybl",            "Netflix India",          (149,  499),  "UPI"),
    ("hotstar@icicibank",      "Disney+ Hotstar",        (149,  299),  "UPI"),
    ("1mghealth@ybl",          "1mg Health",             (100, 1000),  "UPI"),
    ("bescom@bbps",            "BESCOM Electricity",     (300, 1500), "BBPS"),
]
_SPEND_WEIGHTS = [4, 4, 5, 4, 6, 5, 4, 4, 4, 3, 5, 4, 5, 3, 3, 4, 2, 2, 2, 2]


def _db_connect() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )


def _apply_migration(conn: psycopg2.extensions.connection) -> None:
    """Create gig_worker_stress_assessments table if it doesn't exist."""
    migration_path = os.path.join(
        os.path.dirname(__file__), "..", "database", "gig_worker_migration.sql"
    )
    migration_path = os.path.normpath(migration_path)
    if not os.path.exists(migration_path):
        raise FileNotFoundError(f"Migration file not found: {migration_path}")
    with open(migration_path, encoding="utf-8") as f:
        sql = f.read()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


# ── Profile → DB row helpers ──────────────────────────────────────────────────

def _profile_to_customer_row(
    profile: GigWorkerProfile,
    rng: random.Random,
    sequence_id: int,
) -> Dict[str, Any]:
    """Convert a GigWorkerProfile to a customers table insert dict."""
    today = date.today()
    age_days = rng.randint(20 * 365, 45 * 365)
    dob      = today - timedelta(days=age_days)

    vintage_days   = rng.randint(90, min(age_days - 18 * 365, 5 * 365))
    account_open_dt = today - timedelta(days=vintage_days)

    monthly_income = round(profile.baseline_weekly_income * 4 / 500) * 500

    # Account number (16 digits)
    account_number = "".join(rng.choices(string.digits, k=16))
    account_id     = f"GIG{sequence_id:07d}"

    bank_codes  = ["HDFC0001234", "ICIC0001234", "SBIN0001234", "UTIB0001234", "KKBK0001234"]
    ifsc_code   = rng.choice(bank_codes)
    bank_suffix = rng.choice(["oksbi", "okaxis", "ybl", "icicibank", "upi"])
    first_slug  = profile.first_name.lower().replace(" ", "")
    last_slug   = profile.last_name.lower().replace(" ", "")
    upi_vpa     = f"{first_slug}.{last_slug}{rng.randint(1,99)}@{bank_suffix}"

    import hashlib
    fake_aadhaar = "".join(rng.choices(string.digits, k=12))
    aadhaar_hash = hashlib.sha256(fake_aadhaar.encode()).hexdigest()

    # PAN: ABCDE1234F pattern
    pan = (
        "".join(rng.choices(string.ascii_uppercase, k=5))
        + "".join(rng.choices(string.digits, k=4))
        + rng.choice(string.ascii_uppercase)
    )

    # geography_risk_tier from city/state
    from config.settings import STATE_TO_RISK_TIER
    risk_tier = STATE_TO_RISK_TIER.get(profile.state, 2)

    from config.settings import GIG_PLATFORM_VPA_PATTERNS  # noqa: F401 (imported for validation)

    return {
        "customer_id":                  profile.worker_id,
        "first_name":                   profile.first_name,
        "last_name":                    profile.last_name,
        "email":                        f"{first_slug}.{last_slug}{rng.randint(1,99)}@gmail.com",
        "phone":                        profile.phone,
        "date_of_birth":                dob.isoformat(),
        "gender":                       profile.gender,
        "pan_number":                   pan,
        "aadhaar_hash":                 aadhaar_hash,
        "employment_type":              "GIG_WORKER",
        "employer_id":                  f"GIG_{profile.platform_vpa[:6].upper().replace('@','_')}_{rng.randint(1000,9999)}",
        "employer_name":                profile.platform_name,
        "monthly_income":               float(monthly_income),
        "expected_salary_day":          7,
        "state":                        profile.state,
        "city":                         profile.city,
        "pincode":                      "".join(rng.choices(string.digits, k=6)),
        "geography_risk_tier":          risk_tier,
        "customer_segment":             "RETAIL",
        "account_id":                   account_id,
        "account_number":               account_number,
        "account_type":                 "SAVINGS",
        "account_open_date":            account_open_dt.isoformat(),
        "customer_vintage_months":      vintage_days // 30,
        "upi_vpa":                      upi_vpa,
        "ifsc_code":                    ifsc_code,
        "opening_balance":              float(monthly_income * rng.uniform(1.5, 4.0)),
        "historical_delinquency_count": rng.choices([0, 1, 2], weights=[0.78, 0.16, 0.06])[0],
        "credit_bureau_score":          rng.randint(620, 780),
        # Internal ref — not stored
        "_account_number":              account_number,
        "_upi_vpa":                     upi_vpa,
    }


# ── Transaction builders ──────────────────────────────────────────────────────

def _generate_payout_txn(
    week_record: WeeklyPayoutRecord,
    customer_row: Dict[str, Any],
    base_date: datetime,
    rng: random.Random,
) -> Dict[str, Any]:
    """Build a platform weekly payout transaction dict (credit to worker)."""
    week_dt = base_date + timedelta(weeks=week_record.week_num - 1)
    week_dt = week_dt.replace(
        hour=rng.randint(9, 18),
        minute=rng.randint(0, 59),
        second=rng.randint(0, 59),
        tzinfo=timezone.utc,
    )
    return {
        "transaction_id":   str(uuid.uuid4()),
        "customer_id":      customer_row["customer_id"],
        "account_number":   customer_row["_account_number"],
        "sender_id":        week_record.platform_vpa,
        "sender_name":      week_record.platform_name,
        "receiver_id":      customer_row["_account_number"],
        "receiver_name":    f"{customer_row['first_name']} {customer_row['last_name']}",
        "amount":           round(week_record.payout_amount, 2),
        "platform":         "UPI",
        "payment_status":   "success",
        "reference_number": f"UPI{rng.randint(10**11, 10**12 - 1)}",
        "balance_before":   0.0,     # placeholder — updated in _attach_balances
        "balance_after":    0.0,
        "txn_timestamp":    week_dt.isoformat(),
    }


def _generate_spend_txn(
    customer_row: Dict[str, Any],
    day_dt: datetime,
    monthly_income: float,
    rng: random.Random,
) -> Dict[str, Any]:
    """Build one daily spending transaction dict (debit from worker)."""
    recv_id, recv_name, (lo, hi), platform = random.choices(
        _SPEND_POOL, weights=_SPEND_WEIGHTS, k=1
    )[0]
    income_scale = min(monthly_income / 30_000, 2.0)
    amount = round(rng.uniform(lo, min(hi, hi * income_scale)) / 10) * 10
    amount = max(10.0, float(amount))

    txn_dt = day_dt.replace(
        hour=rng.randint(8, 22),
        minute=rng.randint(0, 59),
        second=rng.randint(0, 59),
        tzinfo=timezone.utc,
    )
    return {
        "transaction_id":   str(uuid.uuid4()),
        "customer_id":      customer_row["customer_id"],
        "account_number":   customer_row["_account_number"],
        "sender_id":        customer_row["_upi_vpa"],
        "sender_name":      f"{customer_row['first_name']} {customer_row['last_name']}",
        "receiver_id":      recv_id,
        "receiver_name":    recv_name,
        "amount":           amount,
        "platform":         platform,
        "payment_status":   "success",
        "reference_number": f"UPI{rng.randint(10**11, 10**12 - 1)}",
        "balance_before":   0.0,
        "balance_after":    0.0,
        "txn_timestamp":    txn_dt.isoformat(),
    }


def _attach_balances(
    txns: List[Dict],
    opening_balance: float,
) -> List[Dict]:
    """
    Walk transactions in chronological order and compute running balance.
    Modifies txns in place; returns the same list.
    """
    txns.sort(key=lambda t: t["txn_timestamp"])
    balance = opening_balance
    for t in txns:
        t["balance_before"] = round(balance, 2)
        # Determine credit vs debit by checking sender_id
        is_credit = (
            t["sender_id"] != t["account_number"]
            and t.get("platform") == "UPI"
            and t["receiver_id"] == t["account_number"]
        )
        # More reliable: payout transactions have receiver_id == account_number
        is_payout = t["receiver_id"] == t["account_number"]
        if is_payout:
            balance += t["amount"]
        else:
            balance = max(0.0, balance - t["amount"])
        t["balance_after"] = round(balance, 2)
    return txns


# ── DB insert helpers ─────────────────────────────────────────────────────────

def _insert_customer(
    conn: psycopg2.extensions.connection,
    row: Dict[str, Any],
) -> str:
    """Insert gig worker into customers table. Returns customer_id."""
    sql = """
        INSERT INTO customers (
            customer_id, first_name, last_name, email, phone,
            date_of_birth, gender, pan_number, aadhaar_hash,
            employment_type, employer_id, employer_name,
            monthly_income, expected_salary_day,
            state, city, pincode, geography_risk_tier, customer_segment,
            account_id, account_number, account_type,
            account_open_date, customer_vintage_months,
            upi_vpa, ifsc_code, opening_balance,
            historical_delinquency_count, credit_bureau_score
        ) VALUES (
            %(customer_id)s, %(first_name)s, %(last_name)s, %(email)s, %(phone)s,
            %(date_of_birth)s, %(gender)s, %(pan_number)s, %(aadhaar_hash)s,
            %(employment_type)s, %(employer_id)s, %(employer_name)s,
            %(monthly_income)s, %(expected_salary_day)s,
            %(state)s, %(city)s, %(pincode)s, %(geography_risk_tier)s, %(customer_segment)s,
            %(account_id)s, %(account_number)s, %(account_type)s,
            %(account_open_date)s, %(customer_vintage_months)s,
            %(upi_vpa)s, %(ifsc_code)s, %(opening_balance)s,
            %(historical_delinquency_count)s, %(credit_bureau_score)s
        )
        ON CONFLICT (account_number) DO NOTHING
        RETURNING customer_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, row)
        result = cur.fetchone()
    conn.commit()
    return row["customer_id"]


def _insert_transactions(
    conn: psycopg2.extensions.connection,
    txns: List[Dict],
) -> int:
    """Bulk-insert transactions. Returns count inserted."""
    if not txns:
        return 0
    sql = """
        INSERT INTO transactions (
            transaction_id, customer_id, account_number,
            sender_id, sender_name, receiver_id, receiver_name,
            amount, platform, payment_status, reference_number,
            balance_before, balance_after, txn_timestamp
        ) VALUES (
            %(transaction_id)s, %(customer_id)s, %(account_number)s,
            %(sender_id)s, %(sender_name)s, %(receiver_id)s, %(receiver_name)s,
            %(amount)s, %(platform)s, %(payment_status)s, %(reference_number)s,
            %(balance_before)s, %(balance_after)s, %(txn_timestamp)s
        )
        ON CONFLICT DO NOTHING
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, txns, page_size=200)
    conn.commit()
    return len(txns)


def _insert_assessment(
    conn: psycopg2.extensions.connection,
    customer_id: str,
    profile: GigWorkerProfile,
    prediction: Dict[str, Any],
    txn_count: int,
) -> None:
    """Insert stress assessment result into gig_worker_stress_assessments."""
    # Build weekly snapshots for the last 8 payouts
    recent_records = profile.weekly_payouts[-8:]
    income_snapshot = [
        {
            "week":           r.week_label,
            "amount":         r.payout_amount,
            "wow_change":     round(r.wow_change * 100, 2),   # store as percentage
            "is_stress_week": r.is_stress_week,
        }
        for r in recent_records
    ]
    wow_snapshot = [
        {"week": r.week_label, "wow_change_pct": round(r.wow_change * 100, 2)}
        for r in recent_records
        if r.week_num > 1
    ]

    # Find first stress trigger week
    trigger_week = None
    for r in profile.weekly_payouts:
        if r.week_num >= 13 and r.wow_change < -0.50:
            trigger_week = r.week_num
            break

    sql = """
        INSERT INTO gig_worker_stress_assessments (
            customer_id,
            platform_vpa, platform_name, platform_category,
            baseline_weekly_income, weeks_simulated,
            weekly_income_snapshot, wow_changes_snapshot,
            max_wow_drop_pct, stress_probability,
            is_stressed, stress_label, stress_trigger_week,
            model_version, injected_txn_count, assessed_at
        ) VALUES (
            %(customer_id)s,
            %(platform_vpa)s, %(platform_name)s, %(platform_category)s,
            %(baseline_weekly_income)s, %(weeks_simulated)s,
            %(weekly_income_snapshot)s, %(wow_changes_snapshot)s,
            %(max_wow_drop_pct)s, %(stress_probability)s,
            %(is_stressed)s, %(stress_label)s, %(stress_trigger_week)s,
            %(model_version)s, %(injected_txn_count)s, NOW()
        )
    """
    params = {
        "customer_id":            customer_id,
        "platform_vpa":           profile.platform_vpa,
        "platform_name":          profile.platform_name,
        "platform_category":      profile.platform_category,
        "baseline_weekly_income": float(profile.baseline_weekly_income),
        "weeks_simulated":        len(profile.weekly_payouts),
        "weekly_income_snapshot": json.dumps(income_snapshot),
        "wow_changes_snapshot":   json.dumps(wow_snapshot),
        "max_wow_drop_pct":       round(profile.max_wow_drop * 100, 4) if profile.max_wow_drop else None,
        "stress_probability":     float(prediction["stress_probability"]),
        "is_stressed":            bool(prediction["predicted_stressed"]),
        "stress_label":           prediction["stress_label"],
        "stress_trigger_week":    trigger_week,
        "model_version":          "gig_stress_v1",
        "injected_txn_count":     txn_count,
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


# ── Core injector class ───────────────────────────────────────────────────────

class GigWorkerRealtimeInjector:
    """
    Real-time injector for Indian gig workers.

    Per-worker pipeline:
      generate profile → insert customer → generate & insert transactions
      → classify stress → store assessment → print result

    Does NOT interact with Kafka or the existing RealTimeInjector.
    """

    def __init__(
        self,
        worker_type: str = "all",
        tps: float = 1.0,
        n_weeks: int = 16,
    ) -> None:
        if worker_type not in VALID_WORKER_TYPES:
            raise ValueError(
                f"Invalid worker_type '{worker_type}'. "
                f"Choose from: {', '.join(VALID_WORKER_TYPES)}"
            )
        self.worker_type = worker_type
        self.tps         = max(0.1, tps)
        self.n_weeks     = n_weeks
        self.rng         = random.Random(int.from_bytes(os.urandom(8), "big"))
        self._clf: Optional[GigStressClassifier] = None
        self._seq        = 0   # sequence counter for account_id generation

    # ── Setup ──────────────────────────────────────────────────────────────

    def _load_or_train_classifier(self) -> GigStressClassifier:
        """Load saved model if available, otherwise train from scratch."""
        clf = GigStressClassifier()
        if os.path.exists(MODEL_PATH):
            clf.load()
        else:
            print("[GigWorkerRealtimeInjector] No saved model found — training now (once)…")
            clf.train(n_workers=500, seed=42, save=True)
        return clf

    def _filter_platforms_for_type(self) -> List[Tuple[str, str, str]]:
        """Return the GIG_PLATFORMS subset matching self.worker_type."""
        if self.worker_type == "all":
            return GIG_PLATFORMS
        return [p for p in GIG_PLATFORMS if p[2] == self.worker_type]

    # ── Per-worker pipeline ────────────────────────────────────────────────

    def _generate_filtered_profile(self, platforms: List[Tuple]) -> GigWorkerProfile:
        """Generate a profile restricted to the chosen platform category."""
        import numpy as np

        # Generate base profile and override platform if needed
        profile = _generate_profile(self.rng, idx=self._seq)

        # Override to the target platform type
        vpa, name, category = self.rng.choice(platforms)
        lo, hi = WEEKLY_INCOME_BY_CATEGORY[category]
        profile.platform_vpa      = vpa
        profile.platform_name     = name
        profile.platform_category = category
        profile.baseline_weekly_income = round(self.rng.uniform(lo, hi) / 100) * 100

        # Simulate payouts
        payout_rng    = random.Random(self.rng.randint(0, 2 ** 31))
        payout_np_rng = np.random.default_rng(self.rng.randint(0, 2 ** 31))
        profile.weekly_payouts = _simulate_weekly_payouts(
            profile, n_weeks=self.n_weeks,
            rng=payout_rng, np_rng=payout_np_rng,
        )
        return profile

    def _generate_all_transactions(
        self,
        profile: GigWorkerProfile,
        customer_row: Dict[str, Any],
    ) -> List[Dict]:
        """Build all transactions for the 16-week simulation window."""
        now      = datetime.now(timezone.utc)
        base_dt  = now - timedelta(weeks=self.n_weeks)
        txns: List[Dict] = []

        # ── Weekly platform payouts ────────────────────────────────────────
        for record in profile.weekly_payouts:
            txns.append(_generate_payout_txn(record, customer_row, base_dt, self.rng))

        # ── Daily spending (2–4 transactions per day) ──────────────────────
        monthly = float(customer_row["monthly_income"])
        total_days = self.n_weeks * 7
        for day_offset in range(total_days):
            day_dt  = base_dt + timedelta(days=day_offset)
            n_spend = self.rng.randint(2, 4)
            for _ in range(n_spend):
                txns.append(_generate_spend_txn(customer_row, day_dt, monthly, self.rng))

        _attach_balances(txns, float(customer_row["opening_balance"]))
        return txns

    def _classify(self, profile: GigWorkerProfile) -> Dict[str, Any]:
        """Run gig stress classifier on the profile."""
        return self._clf.predict_profile(profile)

    # ── Main run method ────────────────────────────────────────────────────

    def run(self, n_workers: int = 10) -> List[Dict[str, Any]]:
        """
        Inject n_workers gig workers into the database and classify each.

        Returns list of assessment dicts for all injected workers.
        """
        # ── One-time setup ──────────────────────────────────────────────
        print("=" * 72)
        print("  SENTINEL V2 — Gig Worker Real-Time Injector")
        print(f"  Worker type : {self.worker_type}")
        print(f"  Count       : {n_workers} workers  |  {self.n_weeks} weeks each")
        print(f"  TPS         : {self.tps}")
        print("=" * 72)

        conn = _db_connect()
        _apply_migration(conn)

        self._clf = self._load_or_train_classifier()

        platforms = self._filter_platforms_for_type()
        if not platforms:
            raise ValueError(f"No platforms found for worker_type='{self.worker_type}'")

        print(
            f"\n  Matched {len(platforms)} platform(s) for type '{self.worker_type}'\n"
        )

        interval  = 1.0 / self.tps
        results: List[Dict] = []
        stressed_count = 0

        # ── Header ──────────────────────────────────────────────────────
        hdr = (
            f"  {'#':>3}  {'Name':<22} {'Platform Category':<20} "
            f"{'City':<12} {'Wkly Base':>10} {'WoW Drop':>9} "
            f"{'Prob':>6}  {'Verdict':<14} Txns"
        )
        print(hdr)
        print("  " + "-" * (len(hdr) - 2))

        for i in range(1, n_workers + 1):
            self._seq += 1
            try:
                # 1. Generate profile
                profile = self._generate_filtered_profile(platforms)

                # 2. Build customer row
                cust_row = _profile_to_customer_row(profile, self.rng, self._seq)

                # 3. Insert customer
                _insert_customer(conn, cust_row)

                # 4. Build + insert transactions
                txns     = self._generate_all_transactions(profile, cust_row)
                txn_cnt  = _insert_transactions(conn, txns)

                # 5. Classify stress
                prediction = self._classify(profile)

                # 6. Store assessment
                _insert_assessment(conn, profile.worker_id, profile, prediction, txn_cnt)

                # 7. Print result
                wow_str = (
                    f"{profile.max_wow_drop * 100:+.1f}%"
                    if profile.max_wow_drop > 0
                    else "  —  "
                )
                label   = prediction["stress_label"]
                marker  = " [!]" if prediction["predicted_stressed"] else "    "
                stressed_count += int(prediction["predicted_stressed"])

                print(
                    f"  {i:>3}  {profile.full_name:<22} {profile.platform_category:<20} "
                    f"{profile.city:<12} Rs{profile.baseline_weekly_income:>8,.0f}/wk "
                    f"  {wow_str:>8}  {prediction['stress_probability']:>5.2f}  "
                    f"{label:<14}{marker}  {txn_cnt}"
                )

                results.append({
                    "worker_id":          profile.worker_id,
                    "name":               profile.full_name,
                    "city":               profile.city,
                    "platform":           profile.platform_name,
                    "platform_category":  profile.platform_category,
                    "baseline_weekly_income": profile.baseline_weekly_income,
                    "max_wow_drop_pct":   round(profile.max_wow_drop * 100, 1),
                    "stress_probability": prediction["stress_probability"],
                    "stress_label":       label,
                    "is_stressed":        prediction["predicted_stressed"],
                    "injected_txn_count": txn_cnt,
                })

            except Exception as exc:
                print(f"  {i:>3}  ERROR: {exc}")

            if i < n_workers:
                time.sleep(interval)

        # ── Summary ──────────────────────────────────────────────────────
        print("\n" + "=" * 72)
        print(f"  Injection complete.")
        print(f"  Workers injected   : {len(results)}")
        print(
            f"  STRESSED           : {stressed_count}  "
            f"({stressed_count/max(len(results),1)*100:.1f}%)"
        )
        print(
            f"  NOT STRESSED       : {len(results)-stressed_count}  "
            f"({(len(results)-stressed_count)/max(len(results),1)*100:.1f}%)"
        )
        print(
            f"\n  Results stored in  : gig_worker_stress_assessments (PostgreSQL)"
        )
        print("=" * 72 + "\n")

        conn.close()
        return results


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Gig Worker Real-Time Injector — Sentinel V2",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--worker-type",
        choices=VALID_WORKER_TYPES,
        default="all",
        metavar="TYPE",
        help=(
            "Gig worker platform type to inject.\n"
            "Options: " + "  ".join(VALID_WORKER_TYPES)
        ),
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of gig workers to inject (default: 10)",
    )
    parser.add_argument(
        "--tps",
        type=float,
        default=1.0,
        help="Workers per second (default: 1.0, i.e. 1s between workers)",
    )
    parser.add_argument(
        "--weeks",
        type=int,
        default=16,
        help="Weeks of income history to simulate per worker (default: 16)",
    )

    args = parser.parse_args()

    GigWorkerRealtimeInjector(
        worker_type=args.worker_type,
        tps=args.tps,
        n_weeks=args.weeks,
    ).run(n_workers=args.count)
