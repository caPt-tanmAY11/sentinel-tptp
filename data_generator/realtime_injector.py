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

import os
import random
import time
import uuid
from datetime import datetime, timezone, timedelta
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


# ── Normal merchant pool ───────────────────────────────────────────────────
# (receiver_id, receiver_name, amount_range_inr, weight)

NORMAL_MERCHANTS: List[Tuple[str, str, Tuple[float, float], int]] = [
    # P2P transfers
    ("friend_rahul@ybl",       "Rahul Sharma",          (50,   2000),  12),
    ("priya.menon@hdfcbank",   "Priya Menon",           (50,   3000),  10),
    ("amit.kumar99@okaxis",    "Amit Kumar",            (100,  1500),  10),
    ("sneha.joshi@paytm",      "Sneha Joshi",           (50,   2000),   8),
    ("vikram1992@oksbi",       "Vikram Singh",          (200,  5000),   6),
    ("neha.gupta@ibl",         "Neha Gupta",            (50,   1000),   8),
    ("rohan.das@icicibank",    "Rohan Das",             (100,  3000),   6),
    ("sunita.patel@ybl",       "Sunita Patel",          (50,   2000),   6),
    # Dining
    ("zomato@axl",             "Zomato",                (120,   800),  14),
    ("swiggy@icicibank",       "Swiggy",                (100,   700),  12),
    ("dominos@upi",            "Domino's Pizza",        (200,   600),   6),
    ("mcdonalds@hdfcbank",     "McDonald's India",      (150,   500),   5),
    ("kfc@ybl",                "KFC India",             (200,   600),   4),
    ("haldirams@okaxis",       "Haldiram's",            (80,    400),   5),
    ("barbeque_nation@upi",    "Barbeque Nation",       (500,  2000),   3),
    # Coffee
    ("cafecoffe@upi",          "Café Coffee Day",       (80,    350),   8),
    ("starbucks@hdfcbank",     "Starbucks India",       (200,   600),   5),
    ("chaayos@upi",            "Chaayos",               (60,    200),   6),
    # Grocery
    ("bigbasket@okaxis",       "BigBasket",             (200,  2000),  14),
    ("blinkit@icicibank",      "Blinkit",               (100,  1500),  10),
    ("dmartrewards@upi",       "DMart",                 (500,  3000),   8),
    ("jiomart@upi",            "JioMart",               (200,  2500),   7),
    ("zepto@ybl",              "Zepto",                 (100,  1200),   6),
    ("kirana_store@okaxis",    "Local Kirana Store",    (50,    500),  10),
    # Medical
    ("apollopharmacy@upi",     "Apollo Pharmacy",       (100,  2000),   8),
    ("1mghealth@ybl",          "1mg",                   (100,  3000),   5),
    # Travel
    ("oladriver@upi",          "Ola Cab",               (80,    600),  10),
    ("uber@razorpay",          "Uber India",            (80,    700),   8),
    ("rapido@upi",             "Rapido Bike",           (30,    150),   8),
    ("nammametro@bbps",        "Namma Metro",           (20,    100),   6),
    ("irctc@upi",              "IRCTC Rail Booking",    (200,  3000),   5),
    # Entertainment
    ("bookmyshow@hdfcbank",    "BookMyShow",            (200,   800),   6),
    ("netflix@ybl",            "Netflix India",         (149,   649),   6),
    ("hotstar@icicibank",      "Disney+ Hotstar",       (149,   299),   5),
    # E-commerce
    ("amazon@axisbank",        "Amazon India",          (200,  5000),  10),
    ("flipkart@axisbank",      "Flipkart",              (200,  4000),   9),
    ("myntra@upi",             "Myntra",                (300,  3000),   6),
    # Fuel
    ("hpcl@upi",               "HPCL Petrol Pump",      (500,  3000),   8),
    ("iocl@upi",               "IOCL Fuel Station",     (500,  3000),   7),
    # Utilities
    ("bescom@bbps",            "BESCOM Electricity",    (300,  2500),   5),
    ("airtel@bbps",            "Airtel Recharge",       (149,   599),   8),
    ("jio@bbps",               "Jio Recharge",          (149,   449),   8),
    # Fitness
    ("curefitapp@upi",         "Cult.fit Gym",          (500,  2000),   4),
]
_NORMAL_WEIGHTS = [m[3] for m in NORMAL_MERCHANTS]

# ── Investment merchants (classify → INVESTMENT_DEBIT = relief) ────────────
# (receiver_id, receiver_name, amount_range_inr, platform, weight)
INVESTMENT_MERCHANTS: List[Tuple[str, str, Tuple[float, float], str, int]] = [
    ("zerodha@upi",            "Zerodha — Stock Purchase",        (500,  50000), "UPI",  14),
    ("groww@upi",              "Groww — Mutual Fund SIP",         (500,  25000), "UPI",  16),
    ("smallcase@upi",          "Smallcase Portfolio",             (1000, 50000), "UPI",   8),
    ("paytmmoney@okaxis",      "Paytm Money — SIP",               (500,  20000), "UPI",  10),
    ("coinzerodha@upi",        "Coin by Zerodha — MF",            (500,  25000), "UPI",  10),
    ("sbimf@neft",             "SBI Mutual Fund",                 (1000, 50000), "NEFT", 10),
    ("hdfcmf@neft",            "HDFC Mutual Fund",                (1000, 50000), "NEFT",  9),
    ("iciciprudmf@neft",       "ICICI Pru Mutual Fund",           (1000, 40000), "NEFT",  8),
    ("nps@neft",               "National Pension System (NPS)",   (500,  10000), "NEFT",  6),
    ("kuvera@upi",             "Kuvera — Direct MF",              (500,  30000), "UPI",   9),
    ("etmoney@upi",            "ET Money — SIP",                  (500,  20000), "UPI",   8),
    ("angelone@upi",           "Angel One — Equity",              (1000, 50000), "UPI",   7),
    ("upstox@upi",             "Upstox — Stock/ETF",              (500,  40000), "UPI",   9),
    ("iifl@neft",              "IIFL Securities",                 (1000, 50000), "NEFT",  6),
]
_INVEST_WEIGHTS = [m[4] for m in INVESTMENT_MERCHANTS]

# ── Stress scenarios ───────────────────────────────────────────────────────
STRESS_SCENARIOS: List[Tuple[str, str, str, Tuple[float, float]]] = [
    ("slice@upi",        "Slice Fintech Pvt Ltd",  "UPI",  (3000,  12000)),
    ("lazypay@upi",      "LazyPay",                "UPI",  (2000,  10000)),
    ("fibe@ybl",         "Fibe EarlySalary",       "UPI",  (5000,  20000)),
    ("kreditbee@upi",    "KreditBee",              "UPI",  (4000,  15000)),
    ("navi@hdfcbank",    "Navi Technologies",      "UPI",  (5000,  25000)),
    ("cashe@upi",        "CASHe",                  "UPI",  (3000,  15000)),
    ("mpokket@upi",      "mPokket",                "UPI",  (2000,  10000)),
    ("moneyview@ybl",    "MoneyView Loans",        "UPI",  (5000,  25000)),
]

# ── Mode mix for 'random' — truly mixed, not just normal transactions ──────
# (sub_mode, weight)
# random mode picks one of these sub-modes per transaction
_RANDOM_MIX = [
    ("normal",     55),   # everyday spending
    ("investment", 15),   # SIP / stock purchase → relief signal
    ("salary",     10),   # salary credit       → relief signal
    ("stress",      8),   # lending app / failed EMI → stress signal
    ("recovery",    7),   # on-time EMI         → relief signal
    ("emi_fail",    5),   # pure failed NACH    → strong stress signal
]
_RANDOM_MIX_KEYS    = [m[0] for m in _RANDOM_MIX]
_RANDOM_MIX_WEIGHTS = [m[1] for m in _RANDOM_MIX]


class RealTimeInjector:
    """
    Injects synthetic real-time transactions into Kafka for pipeline testing.

    Modes:
      random   — true mix: normal + investment + salary + stress + recovery
      stress   — lending apps + failed EMI (concentrated stress signals)
      recovery — salary credit + on-time EMI (concentrated relief signals)

    span_hours > 0: transactions are assigned timestamps spread evenly over
                    the past <span_hours> hours instead of using now().
                    This produces proper historical graphs per customer.
    """

    def __init__(self, mode: str = "random", tps: float = 2.0, span_hours: float = 0.0):
        self.mode       = mode
        self.tps        = tps
        self.span_hours = span_hours
        # Use os.urandom-seeded RNG — never deterministic across runs
        self.rng        = random.Random(int.from_bytes(os.urandom(8), "big"))
        self._producer  = None

    def _prod(self):
        if self._producer is None:
            self._producer = _get_producer()
        return self._producer

    # ── Public API ────────────────────────────────────────────────────────

    def inject_transaction(
        self,
        customer: Dict[str, Any],
        override: Optional[Dict] = None,
        timestamp: Optional[datetime] = None,
    ) -> TransactionEvent:
        """Generate and publish one transaction for the given customer."""
        if override:
            txn = self._build_custom(customer, override, timestamp)
        elif self.mode == "stress":
            txn = self._build_stress(customer, timestamp)
        elif self.mode == "recovery":
            txn = self._build_recovery(customer, timestamp)
        else:
            txn = self._build_random(customer, timestamp)

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
        """
        Continuously inject transactions.

        If self.span_hours > 0, all <total> transactions are assigned
        timestamps spread evenly over [now - span_hours, now] so that
        per-customer pulse history graphs show a realistic curve.
        In this mode transactions are injected as fast as the pipeline
        can process them (sleep is skipped).
        """
        customers = _get_customers(n_customers)
        if not customers:
            print("No customers found in DB. Run --step seed first.")
            return

        backfill = self.span_hours > 0 and total and total > 0
        if backfill:
            now        = datetime.now(timezone.utc)
            span_start = now - timedelta(hours=self.span_hours)
            span_secs  = self.span_hours * 3600.0
            print(
                f"Backfill mode | span={self.span_hours}h | "
                f"total={total} | mode={self.mode} | customers={len(customers)}"
            )
        else:
            print(f"Injecting at {self.tps} TPS | mode={self.mode} | customers={len(customers)}")

        count    = 0
        interval = 1.0 / self.tps

        try:
            while True:
                cust = self.rng.choice(customers)

                # Compute timestamp for this transaction
                if backfill and total:
                    # Space transactions evenly; add small jitter so they
                    # don't land on exact intervals
                    frac      = count / max(total - 1, 1)
                    jitter    = self.rng.uniform(-span_secs / (total * 4), span_secs / (total * 4))
                    ts_offset = frac * span_secs + jitter
                    ts        = span_start + timedelta(seconds=max(0.0, min(ts_offset, span_secs)))
                else:
                    ts = None  # builders use datetime.now()

                txn = self.inject_transaction(cust, timestamp=ts)
                count += 1
                print(
                    f"[{count:>4}/{total or '∞'}]  "
                    f"{txn.platform:<5}  {txn.payment_status:<8}  "
                    f"₹{txn.amount:>8.0f}  {txn.receiver_name}"
                )
                if total and count >= total:
                    break

                if not backfill:
                    time.sleep(interval)

        except KeyboardInterrupt:
            pass
        finally:
            if self._producer:
                self._producer.flush(5)
            print(f"Done. Total injected: {count}")

    # ── Transaction builders ───────────────────────────────────────────────

    def _ts(self, override: Optional[datetime]) -> datetime:
        """Return override timestamp if provided, else current UTC time."""
        return override if override is not None else datetime.now(timezone.utc)

    def _build_random(self, customer: Dict[str, Any], timestamp: Optional[datetime] = None) -> TransactionEvent:
        """
        True random mix: normal everyday + investment + salary + stress + recovery.
        Sub-mode is picked by weighted random each call — no fixed ordering.
        """
        sub = self.rng.choices(_RANDOM_MIX_KEYS, weights=_RANDOM_MIX_WEIGHTS, k=1)[0]

        if sub == "investment":
            return self._build_investment(customer, timestamp)
        elif sub == "salary":
            return self._build_salary(customer, timestamp)
        elif sub == "stress":
            return self._build_stress(customer, timestamp)
        elif sub == "recovery":
            return self._build_recovery(customer, timestamp)
        else:
            return self._build_normal(customer, timestamp)

    def _build_normal(self, customer: Dict[str, Any], timestamp: Optional[datetime] = None) -> TransactionEvent:
        """Everyday normal transaction — low/neutral severity."""
        monthly = float(customer.get("monthly_income", 60000))
        receiver_id, receiver_name, (lo, hi), _ = self.rng.choices(
            NORMAL_MERCHANTS, weights=_NORMAL_WEIGHTS, k=1
        )[0]

        income_scale = min(monthly / 60000, 3.0)
        lo_scaled    = max(lo, lo * income_scale * 0.5)
        hi_scaled    = min(hi * income_scale, hi * 2.0)
        amount       = max(10.0, round(self.rng.uniform(lo_scaled, hi_scaled)))

        bal_before = round(self.rng.uniform(monthly * 2, monthly * 6))
        bal_after  = max(0.0, bal_before - amount)

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
            txn_timestamp=self._ts(timestamp),
        )

    def _build_investment(self, customer: Dict[str, Any], timestamp: Optional[datetime] = None) -> TransactionEvent:
        """
        Investment transaction — SIP / mutual fund / stock purchase.
        Classifies as INVESTMENT_DEBIT → relief signal in pulse engine.
        """
        monthly = float(customer.get("monthly_income", 60000))
        receiver_id, receiver_name, (lo, hi), platform, _ = self.rng.choices(
            INVESTMENT_MERCHANTS, weights=_INVEST_WEIGHTS, k=1
        )[0]

        # Investment size scales with income — HNI customers invest more
        income_scale = min(monthly / 60000, 5.0)
        amount       = round(self.rng.uniform(lo, min(hi, hi * income_scale)) / 100) * 100
        amount       = max(500.0, float(amount))

        bal_before = round(self.rng.uniform(monthly * 2, monthly * 8))
        bal_after  = max(0.0, bal_before - amount)

        return TransactionEvent(
            event_id=str(uuid.uuid4()),
            customer_id=str(customer["customer_id"]),
            account_number=customer.get("account_number"),
            sender_id=customer.get("upi_vpa") if platform == "UPI" else customer.get("account_number"),
            sender_name=f"{customer['first_name']} {customer['last_name']}",
            receiver_id=receiver_id,
            receiver_name=receiver_name,
            amount=float(amount),
            platform=platform,
            payment_status="success",
            reference_number=generate_reference_number(platform, self.rng),
            balance_before=float(bal_before),
            balance_after=float(bal_after),
            txn_timestamp=self._ts(timestamp),
        )

    def _build_salary(self, customer: Dict[str, Any], timestamp: Optional[datetime] = None) -> TransactionEvent:
        """Salary credit — strong relief signal."""
        monthly    = float(customer.get("monthly_income", 50000))
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
            txn_timestamp=self._ts(timestamp),
        )

    def _build_stress(self, customer: Dict[str, Any], timestamp: Optional[datetime] = None) -> TransactionEvent:
        """Lending app transfer or failed NACH EMI — stress signals."""
        monthly  = float(customer.get("monthly_income", 50000))
        scenario = self.rng.choices(["lending", "failed_emi"], weights=[0.60, 0.40])[0]

        if scenario == "lending":
            rid, rname, platform, (lo, hi) = self.rng.choice(STRESS_SCENARIOS)
            amount     = round(self.rng.uniform(lo, hi) / 100) * 100
            bal_before = round(self.rng.uniform(monthly * 0.5, monthly * 2))
            bal_after  = max(0.0, bal_before - amount)
            status     = "success"
        else:
            rid        = "HDFC_NACH_EMI_HDFC_PL_2023_00000001@nach"
            rname      = "EMI Auto-debit"
            platform   = "NACH"
            amount     = round(monthly * self.rng.uniform(0.10, 0.25))
            bal_before = round(self.rng.uniform(monthly * 0.2, monthly * 0.8))
            bal_after  = bal_before
            status     = "failed"

        return TransactionEvent(
            event_id=str(uuid.uuid4()),
            customer_id=str(customer["customer_id"]),
            account_number=customer.get("account_number"),
            sender_id=(customer.get("upi_vpa") if scenario == "lending" else customer.get("account_number")),
            sender_name=f"{customer['first_name']} {customer['last_name']}",
            receiver_id=rid, receiver_name=rname,
            amount=float(amount), platform=platform, payment_status=status,
            reference_number=generate_reference_number(platform, self.rng),
            balance_before=float(bal_before), balance_after=float(bal_after),
            txn_timestamp=self._ts(timestamp),
        )

    def _build_recovery(self, customer: Dict[str, Any], timestamp: Optional[datetime] = None) -> TransactionEvent:
        """On-time EMI or grocery — recovery / neutral signals."""
        monthly  = float(customer.get("monthly_income", 50000))
        scenario = self.rng.choice(["emi_success", "grocery"])

        if scenario == "emi_success":
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
                txn_timestamp=self._ts(timestamp),
            )
        else:
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
                txn_timestamp=self._ts(timestamp),
            )

    def _build_custom(self, customer: Dict[str, Any], ov: Dict, timestamp: Optional[datetime] = None) -> TransactionEvent:
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
            sender_name=ov.get("sender_name", f"{customer['first_name']} {customer['last_name']}"),
            receiver_id=ov.get("receiver_id", "merchant@upi"),
            receiver_name=ov.get("receiver_name", "Merchant"),
            amount=amount, platform=platform,
            payment_status=ov.get("payment_status", "success"),
            reference_number=generate_reference_number(platform, self.rng),
            balance_before=bb, balance_after=ba,
            txn_timestamp=self._ts(timestamp),
        )


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--mode",      choices=["random", "stress", "recovery"], default="random")
    p.add_argument("--tps",       type=float, default=2.0)
    p.add_argument("--total",     type=int,   default=50)
    p.add_argument("--customers", type=int,   default=20)
    p.add_argument("--span",      type=float, default=0.0,
                   help="Spread transactions over this many past hours (0 = realtime)")
    args = p.parse_args()
    RealTimeInjector(mode=args.mode, tps=args.tps, span_hours=args.span).run_continuous(
        n_customers=args.customers, total=args.total,
    )