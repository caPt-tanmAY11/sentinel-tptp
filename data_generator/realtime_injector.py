"""
data_generator/realtime_injector.py
─────────────────────────────────────────────────────────────────────────────
Injects synthetic real-time transactions into Kafka for testing.

Modes:
  random    — rich mix of everyday normal Indian transactions
  stress    — lending app transfers + failed EMI (stress signals)
  recovery  — salary credit + successful EMI (relief signals)

Normal transactions cover:
  P2P transfers, dining, groceries, coffee, medical, fuel, travel,
  OTT, e-commerce, utilities, kirana stores, movie tickets, etc.
  These should NOT change the pulse score (model returns low severity).
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import random
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor

from config.settings import get_settings
from schemas.transaction_event import TransactionEvent
from data_generator.indian_names import generate_reference_number

settings = get_settings()


def _get_db():
    import psycopg2
    return psycopg2.connect(
        host=settings.POSTGRES_HOST, port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB, user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )


def _get_producer():
    from confluent_kafka import Producer
    return Producer({
        "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
        "acks": "all",
    })


def _get_customers(n: int = 20) -> List[Dict]:
    conn = _get_db()
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT customer_id, account_number, upi_vpa, monthly_income,
               first_name, last_name
        FROM customers ORDER BY RANDOM() LIMIT %s
    """, (n,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ── Merchant pools ─────────────────────────────────────────────────────────
# (receiver_id, receiver_name, amount_range_inr, weight)

NORMAL_MERCHANTS: List[Tuple[str, str, Tuple[float, float], int]] = [

    # ── P2P transfers (most common UPI use case) ───────────────────────────
    # These use generic personal VPAs — should classify as GENERAL_DEBIT
    ("friend_rahul@ybl",       "Rahul Sharma",          (50,   2000),  12),
    ("priya.menon@hdfcbank",   "Priya Menon",           (50,   3000),  10),
    ("amit.kumar99@okaxis",    "Amit Kumar",            (100,  1500),  10),
    ("sneha.joshi@paytm",      "Sneha Joshi",           (50,   2000),   8),
    ("vikram1992@oksbi",       "Vikram Singh",          (200,  5000),   6),
    ("neha.gupta@ibl",         "Neha Gupta",            (50,   1000),   8),
    ("rohan.das@icicibank",    "Rohan Das",             (100,  3000),   6),
    ("sunita.patel@ybl",       "Sunita Patel",          (50,   2000),   6),

    # ── Dining & Restaurants ───────────────────────────────────────────────
    ("zomato@axl",             "Zomato",                (120,   800),  14),
    ("swiggy@icicibank",       "Swiggy",                (100,   700),  12),
    ("dominos@upi",            "Domino's Pizza",        (200,   600),   6),
    ("mcdonalds@hdfcbank",     "McDonald's India",      (150,   500),   5),
    ("kfc@ybl",                "KFC India",             (200,   600),   4),
    ("haldirams@okaxis",       "Haldiram's",            (80,    400),   5),
    ("barbeque_nation@upi",    "Barbeque Nation",       (500,  2000),   3),
    ("thebrewhouseblr@upi",    "The Brewhouse",         (300,  1500),   3),

    # ── Coffee & Snacks ────────────────────────────────────────────────────
    ("cafecoffe@upi",          "Café Coffee Day",       (80,    350),   8),
    ("starbucks@hdfcbank",     "Starbucks India",       (200,   600),   5),
    ("chaayos@upi",            "Chaayos",               (60,    200),   6),
    ("theobroma@okaxis",       "Theobroma",             (100,   400),   4),

    # ── Grocery & Daily Needs ─────────────────────────────────────────────
    ("bigbasket@okaxis",       "BigBasket",             (200,  2000),  14),
    ("blinkit@icicibank",      "Blinkit",               (100,  1500),  10),
    ("dmartrewards@upi",       "DMart",                 (500,  3000),   8),
    ("jiomart@upi",            "JioMart",               (200,  2500),   7),
    ("zepto@ybl",              "Zepto",                 (100,  1200),   6),
    ("kirana_store@okaxis",    "Local Kirana Store",    (50,    500),  10),
    ("milkbasket@upi",         "MilkBasket",            (50,    300),   5),

    # ── Medical & Pharmacy ─────────────────────────────────────────────────
    ("apollopharmacy@upi",     "Apollo Pharmacy",       (100,  2000),   8),
    ("medplus@okaxis",         "MedPlus",               (80,   1500),   6),
    ("1mghealth@ybl",          "1mg",                   (100,  3000),   5),
    ("netmeds@icicibank",      "Netmeds",               (150,  2500),   4),
    ("doctorondemand@upi",     "Doctor Consultation",   (200,  1000),   3),

    # ── Travel & Transport ─────────────────────────────────────────────────
    ("oladriver@upi",          "Ola Cab",               (80,    600),  10),
    ("uber@razorpay",          "Uber India",            (80,    700),   8),
    ("rapido@upi",             "Rapido Bike",           (30,    150),   8),
    ("nammametro@bbps",        "Namma Metro",           (20,    100),   6),
    ("delhimetro@bbps",        "Delhi Metro",           (20,    100),   6),
    ("irctc@upi",              "IRCTC Rail Booking",    (200,  3000),   5),
    ("redbus@upi",             "RedBus Travels",        (300,  1500),   4),

    # ── Entertainment ─────────────────────────────────────────────────────
    ("bookmyshow@hdfcbank",    "BookMyShow",            (200,   800),   6),
    ("pvr@upi",                "PVR Cinemas",           (200,   700),   5),
    ("netflix@ybl",            "Netflix India",         (149,   649),   6),
    ("primevideo@okaxis",      "Amazon Prime Video",    (179,   299),   5),
    ("hotstar@icicibank",      "Disney+ Hotstar",       (149,   299),   5),
    ("spotify@okicici",        "Spotify India",         (59,    179),   4),

    # ── E-commerce ────────────────────────────────────────────────────────
    ("amazon@axisbank",        "Amazon India",          (200,  5000),  10),
    ("flipkart@axisbank",      "Flipkart",              (200,  4000),   9),
    ("myntra@upi",             "Myntra",                (300,  3000),   6),
    ("meesho@okaxis",          "Meesho",                (100,  2000),   5),
    ("nykaa@ybl",              "Nykaa",                 (200,  2500),   4),
    ("ajio@upi",               "Ajio",                  (300,  3500),   3),

    # ── Fuel ──────────────────────────────────────────────────────────────
    ("hpcl@upi",               "HPCL Petrol Pump",      (500,  3000),   8),
    ("iocl@upi",               "IOCL Fuel Station",     (500,  3000),   7),
    ("bpcl@okaxis",            "BPCL Fuel",             (500,  3000),   6),

    # ── Utilities (via UPI, not just BBPS) ────────────────────────────────
    ("bescom@bbps",            "BESCOM Electricity",    (300,  2500),   5),
    ("tatapower@bbps",         "Tata Power",            (300,  2000),   5),
    ("airtel@bbps",            "Airtel Recharge",       (149,   599),   8),
    ("jio@bbps",               "Jio Recharge",          (149,   449),   8),
    ("bsnl@bbps",              "BSNL",                  (100,   500),   3),

    # ── Education & Professional ──────────────────────────────────────────
    ("udemy@upi",              "Udemy Online Course",   (200,  2000),   4),
    ("coursera@upi",           "Coursera",              (300,  3000),   3),
    ("byju@upi",               "BYJU'S",                (500,  5000),   3),

    # ── Fitness & Wellness ────────────────────────────────────────────────
    ("curefitapp@upi",         "Cult.fit Gym",          (500,  2000),   4),
    ("gympass@okaxis",         "Gym Membership",        (500,  3000),   3),
]

# Build weights list for sampling
_NORMAL_WEIGHTS = [m[3] for m in NORMAL_MERCHANTS]

# ── Stress scenarios ───────────────────────────────────────────────────────
STRESS_SCENARIOS: List[Tuple[str, str, str, Tuple[float, float]]] = [
    ("slice@upi",        "Slice Fintech Pvt Ltd",   "UPI",  (3000,  12000)),
    ("lazypay@upi",      "LazyPay",                 "UPI",  (2000,  10000)),
    ("fibe@ybl",         "Fibe EarlySalary",        "UPI",  (5000,  20000)),
    ("kreditbee@upi",    "KreditBee",               "UPI",  (4000,  15000)),
    ("navi@hdfcbank",    "Navi Technologies",       "UPI",  (5000,  25000)),
    ("cashe@upi",        "CASHe",                   "UPI",  (3000,  15000)),
    ("mpokket@upi",      "mPokket",                 "UPI",  (2000,  10000)),
    ("moneyview@ybl",    "MoneyView Loans",         "UPI",  (5000,  25000)),
]


class RealTimeInjector:
    """
    Injects synthetic real-time transactions into Kafka for pipeline testing.

    Mode 'random' generates realistic everyday Indian transactions that
    cover 60+ merchant types. These should score neutral/low severity
    and NOT move the customer's pulse score meaningfully.
    """

    def __init__(self, mode: str = "random", tps: float = 2.0):
        self.mode      = mode
        self.tps       = tps
        self.rng       = random.Random()
        self._producer = None

    def _prod(self):
        if self._producer is None:
            self._producer = _get_producer()
        return self._producer

    # ── Public API ────────────────────────────────────────────────────────

    def inject_transaction(
        self,
        customer: Dict[str, Any],
        override: Optional[Dict] = None,
    ) -> TransactionEvent:
        """Generate and publish one transaction for the given customer."""
        if override:
            txn = self._build_custom(customer, override)
        elif self.mode == "stress":
            txn = self._build_stress(customer)
        elif self.mode == "recovery":
            txn = self._build_recovery(customer)
        else:
            txn = self._build_random(customer)

        self._prod().produce(
            topic=settings.TOPIC_RAW_TRANSACTIONS,
            key=txn.customer_id.encode("utf-8"),
            value=txn.to_kafka_payload(),
        )
        self._prod().poll(0)
        return txn

    def run_continuous(
        self,
        n_customers: int = 20,
        total: Optional[int] = None,
    ):
        """Continuously inject transactions at self.tps rate."""
        customers = _get_customers(n_customers)
        if not customers:
            print("No customers found in DB. Run --step seed first.")
            return

        print(f"Injecting at {self.tps} TPS | mode={self.mode} | customers={len(customers)}")
        count    = 0
        interval = 1.0 / self.tps

        try:
            while True:
                cust = self.rng.choice(customers)
                txn  = self.inject_transaction(cust)
                count += 1
                print(
                    f"[{count:>4}/{total or '∞'}]  "
                    f"{txn.platform:<5}  {txn.payment_status:<8}  "
                    f"₹{txn.amount:>8.0f}  {txn.receiver_id}"
                )
                if total and count >= total:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            pass
        finally:
            if self._producer:
                self._producer.flush(5)
            print(f"Done. Total injected: {count}")

    # ── Transaction builders ───────────────────────────────────────────────

    def _build_random(self, customer: Dict[str, Any]) -> TransactionEvent:
        """
        Build a realistic everyday Indian transaction.
        Covers P2P, dining, groceries, medical, travel, entertainment,
        utilities, e-commerce — all the normal things people spend on.
        These should NOT trigger stress signals in the model.
        """
        monthly = float(customer.get("monthly_income", 60000))

        # Weighted random selection from rich merchant pool
        receiver_id, receiver_name, (lo, hi), _ = self.rng.choices(
            NORMAL_MERCHANTS,
            weights=_NORMAL_WEIGHTS,
            k=1,
        )[0]

        # Scale amount to customer's income segment
        # A low-income customer shouldn't be spending Rs5000 at a restaurant
        income_scale = min(monthly / 60000, 3.0)  # cap at 3x
        lo_scaled = max(lo, lo * income_scale * 0.5)
        hi_scaled = min(hi * income_scale, hi * 2.0)

        amount = round(self.rng.uniform(lo_scaled, hi_scaled))
        amount = max(10.0, amount)  # minimum Rs10

        # Realistic balance: customer has 2–6 months of salary
        bal_before = round(self.rng.uniform(monthly * 2, monthly * 6))
        bal_after  = max(0.0, bal_before - amount)

        # Platform: most normal transactions are UPI, some POS
        if receiver_id.endswith("@bbps"):
            platform = "BBPS"
        elif "metro@" in receiver_id or "irctc" in receiver_id:
            platform = self.rng.choice(["UPI", "UPI", "MOBILE"])
        else:
            platform = self.rng.choices(["UPI", "UPI", "UPI", "POS"], weights=[7, 7, 7, 3])[0]

        return TransactionEvent(
            event_id=str(uuid.uuid4()),
            customer_id=str(customer["customer_id"]),
            account_number=customer.get("account_number"),
            sender_id=customer.get("upi_vpa", f"user{self.rng.randint(1,999)}@sbi"),
            sender_name=f"{customer['first_name']} {customer['last_name']}",
            receiver_id=receiver_id,
            receiver_name=receiver_name,
            amount=float(amount),
            platform=platform,
            payment_status="success",
            reference_number=generate_reference_number(platform, self.rng),
            balance_before=float(bal_before),
            balance_after=float(bal_after),
            txn_timestamp=datetime.now(timezone.utc),
        )

    def _build_stress(self, customer: Dict[str, Any]) -> TransactionEvent:
        """Build a stress transaction — lending app or failed NACH EMI."""
        monthly  = float(customer.get("monthly_income", 50000))
        scenario = self.rng.choices(["lending", "failed_emi"], weights=[0.60, 0.40])[0]

        if scenario == "lending":
            rid, rname, platform, (lo, hi) = self.rng.choice(STRESS_SCENARIOS)
            amount     = round(self.rng.uniform(lo, hi) / 100) * 100
            bal_before = round(self.rng.uniform(monthly * 0.5, monthly * 2))
            bal_after  = max(0.0, bal_before - amount)
            status     = "success"
        else:
            # Failed NACH EMI
            rid        = "HDFC_NACH_EMI_HDFC_PL_2023_00000001@nach"
            rname      = "EMI Auto-debit"
            platform   = "NACH"
            amount     = round(monthly * self.rng.uniform(0.10, 0.25))
            bal_before = round(self.rng.uniform(monthly * 0.2, monthly * 0.8))
            bal_after  = bal_before  # balance unchanged on failed
            status     = "failed"

        return TransactionEvent(
            event_id=str(uuid.uuid4()),
            customer_id=str(customer["customer_id"]),
            account_number=customer.get("account_number"),
            sender_id=(customer.get("upi_vpa") if scenario == "lending"
                       else customer.get("account_number")),
            sender_name=f"{customer['first_name']} {customer['last_name']}",
            receiver_id=rid,
            receiver_name=rname,
            amount=float(amount),
            platform=platform,
            payment_status=status,
            reference_number=generate_reference_number(platform, self.rng),
            balance_before=float(bal_before),
            balance_after=float(bal_after),
            txn_timestamp=datetime.now(timezone.utc),
        )

    def _build_recovery(self, customer: Dict[str, Any]) -> TransactionEvent:
        """Build a recovery transaction — salary credit or on-time EMI."""
        monthly  = float(customer.get("monthly_income", 50000))
        scenario = self.rng.choice(["salary", "emi_success", "grocery"])

        if scenario == "salary":
            amount     = round(monthly * self.rng.uniform(0.97, 1.03))
            bal_before = round(self.rng.uniform(monthly * 0.5, monthly))
            bal_after  = bal_before + amount
            return TransactionEvent(
                event_id=str(uuid.uuid4()),
                customer_id=str(customer["customer_id"]),
                account_number=customer.get("account_number"),
                sender_id="tcspayroll@neft",
                sender_name="TCS Payroll Services",
                receiver_id=customer.get("account_number"),
                receiver_name=f"{customer['first_name']} {customer['last_name']}",
                amount=float(amount), platform="NEFT", payment_status="success",
                reference_number=generate_reference_number("NEFT", self.rng),
                balance_before=float(bal_before), balance_after=float(bal_after),
                txn_timestamp=datetime.now(timezone.utc),
            )

        elif scenario == "emi_success":
            emi        = round(monthly * self.rng.uniform(0.10, 0.25))
            bal_before = round(self.rng.uniform(monthly * 2, monthly * 4))
            bal_after  = max(0.0, bal_before - emi)
            return TransactionEvent(
                event_id=str(uuid.uuid4()),
                customer_id=str(customer["customer_id"]),
                account_number=customer.get("account_number"),
                sender_id=customer.get("account_number"),
                sender_name=f"{customer['first_name']} {customer['last_name']}",
                receiver_id="HDFC_NACH_EMI_HDFC_PL_2023_00000001@nach",
                receiver_name="EMI Auto-debit",
                amount=float(emi), platform="NACH", payment_status="success",
                reference_number=generate_reference_number("NACH", self.rng),
                balance_before=float(bal_before), balance_after=float(bal_after),
                txn_timestamp=datetime.now(timezone.utc),
            )

        else:
            # Normal grocery — benign
            amount     = round(self.rng.uniform(300, 1500))
            bal_before = round(self.rng.uniform(monthly * 2, monthly * 4))
            return TransactionEvent(
                event_id=str(uuid.uuid4()),
                customer_id=str(customer["customer_id"]),
                account_number=customer.get("account_number"),
                sender_id=customer.get("upi_vpa"),
                sender_name=f"{customer['first_name']} {customer['last_name']}",
                receiver_id="bigbasket@okaxis", receiver_name="BigBasket",
                amount=float(amount), platform="UPI", payment_status="success",
                reference_number=generate_reference_number("UPI", self.rng),
                balance_before=float(bal_before),
                balance_after=max(0.0, float(bal_before) - amount),
                txn_timestamp=datetime.now(timezone.utc),
            )

    def _build_custom(self, customer: Dict[str, Any], ov: Dict) -> TransactionEvent:
        """Build a transaction with manual field overrides."""
        monthly  = float(customer.get("monthly_income", 50000))
        amount   = float(ov.get("amount", self.rng.uniform(100, 5000)))
        bb       = float(ov.get("balance_before", monthly * 2))
        ba       = float(ov.get("balance_after", max(0.0, bb - amount)))
        platform = ov.get("platform", "UPI")

        return TransactionEvent(
            event_id=str(uuid.uuid4()),
            customer_id=str(customer["customer_id"]),
            account_number=customer.get("account_number"),
            sender_id=ov.get("sender_id", customer.get("upi_vpa")),
            sender_name=ov.get("sender_name",
                               f"{customer['first_name']} {customer['last_name']}"),
            receiver_id=ov.get("receiver_id", "merchant@upi"),
            receiver_name=ov.get("receiver_name", "Merchant"),
            amount=amount, platform=platform,
            payment_status=ov.get("payment_status", "success"),
            reference_number=generate_reference_number(platform, self.rng),
            balance_before=bb, balance_after=ba,
            txn_timestamp=datetime.now(timezone.utc),
        )


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--mode",      choices=["random", "stress", "recovery"], default="random")
    p.add_argument("--tps",       type=float, default=2.0)
    p.add_argument("--total",     type=int,   default=50)
    p.add_argument("--customers", type=int,   default=20)
    args = p.parse_args()
    RealTimeInjector(mode=args.mode, tps=args.tps).run_continuous(
        n_customers=args.customers, total=args.total,
    )