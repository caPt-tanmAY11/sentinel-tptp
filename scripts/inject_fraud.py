"""
scripts/inject_fraud.py
─────────────────────────────────────────────────────────────────────────────
Probable Fault Detection (PFD) — Fraud Scenario Generator

Injects synthetic fraud transactions directly into Kafka so that the full
PulseEngine pipeline (fraud gate → alert persistence → email) is exercised
exactly as it would be in production.

USAGE
─────
  # Pick a random customer, run the combined scenario (all 3 signals):
  python -m scripts.inject_fraud --scenario combined

  # Target a specific customer:
  python -m scripts.inject_fraud --scenario international --customer-id <uuid>

  # Frequency burst — 12 rapid-fire transactions then the spike transaction:
  python -m scripts.inject_fraud --scenario freq_burst --customer-id <uuid>

  # Amount spike only (single large transaction):
  python -m scripts.inject_fraud --scenario amount_spike --customer-id <uuid>

  # All four scenarios back-to-back on the same customer:
  python -m scripts.inject_fraud --scenario all --customer-id <uuid>

  # Dry-run: print what would be sent, don't touch Kafka:
  python -m scripts.inject_fraud --scenario combined --dry-run

SCENARIOS
─────────
  international   → Signal 1  — foreign currency / non-IN receiver
  amount_spike    → Signal 2  — amount far above customer's 30d baseline
  freq_burst      → Signal 3  — rapid burst of transactions in 60 min
  combined        → Signals 1+2+3 in one shot (highest composite score)
  all             → Runs all four scenarios sequentially

DESIGN NOTES
────────────
  • Every injected event goes through the real Kafka → consumer → PulseEngine
    path, so the fraud gate fires naturally and persists a real fraud_alert row.

  • For `freq_burst` we first inject (FREQ_MIN_COUNT - 1) = 4 normal warm-up
    transactions at normal amounts, then fire the spike transaction. This
    satisfies the FREQ_MIN_COUNT=5 floor in fraud_detector.py.

  • For `amount_spike` we read the customer's real 30d mean from Postgres and
    multiply by (AMOUNT_ZSCORE_THRESHOLD + 2) × std_dev so the Z-score is
    guaranteed to exceed the threshold even on sparse data.

  • All injected transactions use payment_status='success' so they are counted
    by the fraud detector's history queries.

  • Timestamps are set to NOW() by default (realtime mode).
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor

# ── Project imports ───────────────────────────────────────────────────────────
# Ensure project root is on sys.path when running as `python scripts/inject_fraud.py`
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import get_settings
from schemas.transaction_event import TransactionEvent
from data_generator.indian_names import generate_reference_number

settings = get_settings()

# ── Thresholds — must mirror fraud_detector.py exactly ───────────────────────
AMOUNT_ZSCORE_THRESHOLD: float = 3.0
AMOUNT_LOOKBACK_DAYS:    int   = 30
AMOUNT_MIN_SAMPLES:      int   = 5
FREQ_MIN_COUNT:          int   = 5      # warm-up count before the burst txn
FREQ_MULTIPLIER:         float = 3.0
FREQ_BASELINE_DAYS:      int   = 30

# ── Foreign-country / currency pools ─────────────────────────────────────────
FOREIGN_CURRENCIES = ["USD", "EUR", "GBP", "AED", "SGD", "JPY", "CHF"]
FOREIGN_COUNTRIES  = ["US", "GB", "AE", "SG", "JP", "DE", "CH", "AU"]
FOREIGN_MERCHANTS  = [
    ("amazon.us@stripe",   "Amazon US"),
    ("netflix@paypal",     "Netflix International"),
    ("aliexpress@alipay",  "AliExpress"),
    ("booking.com@swift",  "Booking.com BV"),
    ("airbnb@stripe",      "Airbnb Ireland UC"),
    ("steam@valve",        "Valve Corporation"),
    ("paypal@paypal",      "PayPal (Europe)"),
    ("skype@microsoft",    "Microsoft Ireland"),
]

# ── Colours for terminal output ───────────────────────────────────────────────
RED    = "\033[91m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_db() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )


def _fetch_customer(customer_id: Optional[str], conn) -> Dict:
    cur = conn.cursor(cursor_factory=RealDictCursor)
    if customer_id:
        cur.execute(
            """
            SELECT customer_id, account_number, upi_vpa,
                   monthly_income, first_name, last_name
            FROM customers
            WHERE customer_id = %s
            """,
            (customer_id,),
        )
        row = cur.fetchone()
        if not row:
            print(f"{RED}✗ Customer {customer_id} not found in DB.{RESET}")
            sys.exit(1)
        return dict(row)
    else:
        cur.execute(
            """
            SELECT customer_id, account_number, upi_vpa,
                   monthly_income, first_name, last_name
            FROM customers
            ORDER BY RANDOM()
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            print(f"{RED}✗ No customers found in DB. Run the seed first.{RESET}")
            sys.exit(1)
        return dict(row)


def _fetch_amount_baseline(customer_id: str, conn) -> Tuple[float, float, int]:
    """
    Returns (mean, std, sample_count) from the customer's last 30d transactions.
    Used to compute a guaranteed amount-spike value.
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """
        SELECT
            COUNT(*)           AS sample_count,
            AVG(amount)        AS mean_amount,
            STDDEV_POP(amount) AS std_amount
        FROM transactions
        WHERE customer_id    = %s
          AND payment_status = 'success'
          AND txn_timestamp  >= NOW() - INTERVAL '%s days'
        """,
        (customer_id, AMOUNT_LOOKBACK_DAYS),
    )
    row = cur.fetchone()
    if not row or (row["sample_count"] or 0) < AMOUNT_MIN_SAMPLES:
        return 5_000.0, 2_000.0, 0   # safe fallback
    return (
        float(row["mean_amount"] or 5_000),
        float(row["std_amount"]  or 2_000),
        int(row["sample_count"]  or 0),
    )


def _fetch_freq_baseline(customer_id: str, conn) -> float:
    """
    Returns the customer's baseline hourly transaction rate over last 30 days.
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """
        SELECT COUNT(*) AS total_count
        FROM transactions
        WHERE customer_id   = %s
          AND txn_timestamp >= NOW() - INTERVAL '%s days'
        """,
        (customer_id, FREQ_BASELINE_DAYS),
    )
    row = cur.fetchone()
    total = int(row["total_count"] or 0) if row else 0
    return round(total / (FREQ_BASELINE_DAYS * 24), 4)


# ─────────────────────────────────────────────────────────────────────────────
# Kafka producer helper
# ─────────────────────────────────────────────────────────────────────────────

def _get_producer():
    from confluent_kafka import Producer
    return Producer({
        "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
        "acks": "all",
    })


def _publish(producer, event: TransactionEvent, dry_run: bool) -> None:
    if dry_run:
        return
    producer.produce(
        topic=settings.TOPIC_RAW_TRANSACTIONS,
        key=event.customer_id.encode("utf-8"),
        value=event.to_kafka_payload(),
    )
    producer.poll(0)


# ─────────────────────────────────────────────────────────────────────────────
# Transaction builders
# ─────────────────────────────────────────────────────────────────────────────

def _base_event(customer: Dict, **overrides) -> TransactionEvent:
    """Construct a TransactionEvent with sensible defaults for a given customer."""
    monthly  = float(customer.get("monthly_income") or 50_000)
    amount   = overrides.pop("amount", random.uniform(200, 2_000))
    bb       = overrides.pop("balance_before", monthly * 2.0)
    ba       = overrides.pop("balance_after",  max(0.0, bb - amount))
    platform = overrides.pop("platform", "UPI")
    return TransactionEvent(
        event_id        = str(uuid.uuid4()),
        customer_id     = str(customer["customer_id"]),
        account_number  = customer.get("account_number"),
        sender_id       = overrides.pop("sender_id", customer.get("upi_vpa")),
        sender_name     = overrides.pop("sender_name",
                            f"{customer['first_name']} {customer['last_name']}"),
        receiver_id     = overrides.pop("receiver_id", "merchant@upi"),
        receiver_name   = overrides.pop("receiver_name", "Merchant"),
        amount          = amount,
        platform        = platform,
        payment_status  = overrides.pop("payment_status", "success"),
        reference_number= generate_reference_number(platform, random),
        balance_before  = bb,
        balance_after   = ba,
        txn_timestamp   = overrides.pop("txn_timestamp", datetime.now(timezone.utc)),
        **overrides,
    )


def build_international_event(customer: Dict) -> TransactionEvent:
    """Signal 1: Foreign currency + non-IN receiver."""
    rng      = random.Random()
    currency = rng.choice(FOREIGN_CURRENCIES)
    country  = rng.choice(FOREIGN_COUNTRIES)
    vpa, name = rng.choice(FOREIGN_MERCHANTS)
    amount   = round(rng.uniform(3_000, 25_000), 2)   # INR equivalent
    monthly  = float(customer.get("monthly_income") or 50_000)

    return _base_event(
        customer,
        amount           = amount,
        balance_before   = monthly * 2,
        balance_after    = max(0.0, monthly * 2 - amount),
        platform         = "NEFT",
        receiver_id      = vpa,
        receiver_name    = name,
        receiver_vpa     = vpa,
        currency         = currency,
        receiver_country = country,
    )


def build_amount_spike_event(customer: Dict, mean: float, std: float) -> TransactionEvent:
    """
    Signal 2: Z-score guaranteed to exceed AMOUNT_ZSCORE_THRESHOLD.
    spike = mean + (threshold + 2.0) * max(std, mean * 0.3)
    This ensures the spike fires even when std is very low.
    """
    effective_std = max(std, mean * 0.3)
    spike_amount  = round(mean + (AMOUNT_ZSCORE_THRESHOLD + 2.0) * effective_std, 2)
    spike_amount  = max(spike_amount, 50_000)   # minimum ₹50,000 to look suspicious
    monthly       = float(customer.get("monthly_income") or 50_000)

    return _base_event(
        customer,
        amount         = spike_amount,
        balance_before = monthly * 3,
        balance_after  = max(0.0, monthly * 3 - spike_amount),
        platform       = "IMPS",
        receiver_id    = "unknown.payee@ybl",
        receiver_name  = "Unknown Payee",
        receiver_vpa   = "unknown.payee@ybl",
    )


def build_warmup_events(customer: Dict, count: int) -> List[TransactionEvent]:
    """
    Normal small transactions used to prime the frequency counter before
    the burst transaction. These look like everyday UPI payments.
    """
    receivers = [
        ("swiggy@icici",    "Swiggy",      350,  800),
        ("zomato@kotak",    "Zomato",      280,  600),
        ("bigbasket@axis",  "BigBasket",   500, 1500),
        ("petrol@hpcl",     "HPCL Petrol", 400, 1200),
        ("dmart@upi",       "D-Mart",      600, 2000),
        ("amazon@apl",      "Amazon India",800, 3000),
        ("ola@upi",         "Ola Cabs",    120,  500),
        ("metro@bbps",      "Metro Card",  200,  500),
    ]
    monthly = float(customer.get("monthly_income") or 50_000)
    events  = []
    for i in range(count):
        vpa, name, lo, hi = random.choice(receivers)
        amount = round(random.uniform(lo, hi), 2)
        events.append(_base_event(
            customer,
            amount        = amount,
            balance_before= monthly * 2 - i * amount,
            balance_after = monthly * 2 - (i + 1) * amount,
            platform      = "UPI",
            receiver_id   = vpa,
            receiver_name = name,
            receiver_vpa  = vpa,
        ))
    return events


def build_freq_burst_events(customer: Dict, baseline_hourly: float) -> Tuple[List[TransactionEvent], TransactionEvent]:
    """
    Signal 3: Returns (warmup_events, spike_event).
    Warmup events bring hourly count to FREQ_MIN_COUNT.
    Spike event is the final transaction that pushes count well above
    baseline × FREQ_MULTIPLIER.
    """
    # We need total in-window count > max(FREQ_MIN_COUNT, baseline * FREQ_MULTIPLIER)
    target_total  = max(FREQ_MIN_COUNT + 1, int(baseline_hourly * FREQ_MULTIPLIER) + 3)
    warmup_count  = target_total - 1   # spike txn itself counts as +1

    warmup_events = build_warmup_events(customer, warmup_count)

    # Spike transaction — small amount but part of a burst (amount alone won't flag)
    monthly = float(customer.get("monthly_income") or 50_000)
    spike   = _base_event(
        customer,
        amount        = round(random.uniform(200, 1_000), 2),
        balance_before= monthly * 0.5,
        balance_after = monthly * 0.5 - 500,
        platform      = "UPI",
        receiver_id   = "suspicious@paytm",
        receiver_name = "Suspicious Payee",
        receiver_vpa  = "suspicious@paytm",
    )
    return warmup_events, spike


def build_combined_event(customer: Dict, mean: float, std: float) -> TransactionEvent:
    """
    Signals 1 + 2 + 3: A single large international transaction that also
    triggers the amount spike. Frequency spike comes from prior warmup events.
    """
    rng      = random.Random()
    currency = rng.choice(FOREIGN_CURRENCIES)
    country  = rng.choice(FOREIGN_COUNTRIES)
    vpa, name = rng.choice(FOREIGN_MERCHANTS)

    effective_std = max(std, mean * 0.3)
    spike_amount  = round(mean + (AMOUNT_ZSCORE_THRESHOLD + 2.5) * effective_std, 2)
    spike_amount  = max(spike_amount, 75_000)
    monthly       = float(customer.get("monthly_income") or 50_000)

    return _base_event(
        customer,
        amount           = spike_amount,
        balance_before   = monthly * 3,
        balance_after    = max(0.0, monthly * 3 - spike_amount),
        platform         = "RTGS",
        receiver_id      = vpa,
        receiver_name    = name,
        receiver_vpa     = vpa,
        currency         = currency,
        receiver_country = country,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scenario runners
# ─────────────────────────────────────────────────────────────────────────────

def _print_event(label: str, event: TransactionEvent, dry_run: bool) -> None:
    tag = f"{YELLOW}[DRY RUN]{RESET} " if dry_run else ""
    print(f"\n  {tag}{CYAN}{label}{RESET}")
    print(f"    event_id     : {event.event_id}")
    print(f"    customer_id  : {event.customer_id}")
    print(f"    amount       : ₹{event.amount:,.2f}  ({event.currency})")
    print(f"    platform     : {event.platform}")
    print(f"    receiver     : {event.receiver_name}  ({event.receiver_vpa or event.receiver_id})")
    print(f"    receiver_cntry: {event.receiver_country}")
    print(f"    timestamp    : {event.txn_timestamp.isoformat()}")


def run_international(customer: Dict, producer, dry_run: bool) -> None:
    print(f"\n{BOLD}📡 Scenario: INTERNATIONAL{RESET}")
    event = build_international_event(customer)
    _print_event("→ Publishing international transaction …", event, dry_run)
    _publish(producer, event, dry_run)
    if not dry_run:
        producer.flush(5)
    print(f"  {GREEN}✓ Done — watch the fraud-alerts dashboard.{RESET}")


def run_amount_spike(customer: Dict, conn, producer, dry_run: bool) -> None:
    print(f"\n{BOLD}💸 Scenario: AMOUNT SPIKE{RESET}")
    mean, std, samples = _fetch_amount_baseline(str(customer["customer_id"]), conn)
    print(f"  Baseline: mean=₹{mean:,.0f}  std=₹{std:,.0f}  samples={samples}")

    event = build_amount_spike_event(customer, mean, std)
    expected_z = (event.amount - mean) / max(std, mean * 0.3)
    print(f"  Spike amount: ₹{event.amount:,.0f}  (expected Z ≈ {expected_z:.1f}σ)")
    _print_event("→ Publishing amount-spike transaction …", event, dry_run)
    _publish(producer, event, dry_run)
    if not dry_run:
        producer.flush(5)
    print(f"  {GREEN}✓ Done — watch the fraud-alerts dashboard.{RESET}")


def run_freq_burst(customer: Dict, conn, producer, dry_run: bool) -> None:
    print(f"\n{BOLD}⚡ Scenario: FREQUENCY BURST{RESET}")
    baseline_hourly = _fetch_freq_baseline(str(customer["customer_id"]), conn)
    print(f"  Baseline hourly rate: {baseline_hourly:.2f} txns/hr")

    warmup_events, spike_event = build_freq_burst_events(customer, baseline_hourly)
    total_in_window = len(warmup_events) + 1

    print(f"  Injecting {len(warmup_events)} warm-up transactions …")
    for i, ev in enumerate(warmup_events, 1):
        _print_event(f"  Warmup {i}/{len(warmup_events)}", ev, dry_run)
        _publish(producer, ev, dry_run)
        if not dry_run:
            producer.poll(0)
            time.sleep(0.1)   # small gap — stays within 60-min window

    print(f"\n  Now firing the burst-trigger transaction (txn #{total_in_window} in 60 min) …")
    _print_event("→ Burst trigger transaction", spike_event, dry_run)
    _publish(producer, spike_event, dry_run)
    if not dry_run:
        producer.flush(5)
    print(f"  {GREEN}✓ Done — {total_in_window} txns in last 60 min vs "
          f"baseline {baseline_hourly:.2f}/hr.{RESET}")


def run_combined(customer: Dict, conn, producer, dry_run: bool) -> None:
    print(f"\n{BOLD}🔴 Scenario: COMBINED (all 3 signals){RESET}")
    mean, std, samples = _fetch_amount_baseline(str(customer["customer_id"]), conn)
    baseline_hourly = _fetch_freq_baseline(str(customer["customer_id"]), conn)
    print(f"  Amount baseline: mean=₹{mean:,.0f}  std=₹{std:,.0f}  samples={samples}")
    print(f"  Freq baseline  : {baseline_hourly:.2f} txns/hr")

    # Step 1 — warmup for frequency signal
    warmup_events, _ = build_freq_burst_events(customer, baseline_hourly)
    print(f"\n  Injecting {len(warmup_events)} warm-up transactions …")
    for i, ev in enumerate(warmup_events, 1):
        _print_event(f"  Warmup {i}/{len(warmup_events)}", ev, dry_run)
        _publish(producer, ev, dry_run)
        if not dry_run:
            producer.poll(0)
            time.sleep(0.1)

    # Step 2 — the combined fraud transaction (intl + spike + freq)
    event = build_combined_event(customer, mean, std)
    expected_z = (event.amount - mean) / max(std, mean * 0.3)
    print(f"\n  Combined spike: ₹{event.amount:,.0f}  Z≈{expected_z:.1f}σ  "
          f"currency={event.currency}  country={event.receiver_country}")
    _print_event("→ Publishing combined fraud transaction …", event, dry_run)
    _publish(producer, event, dry_run)
    if not dry_run:
        producer.flush(5)
    print(f"  {GREEN}✓ Done — all 3 signals should fire. Check fraud-alerts dashboard.{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="inject_fraud",
        description="Sentinel PFD — Inject synthetic fraud scenarios into Kafka",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scripts.inject_fraud --scenario combined
  python -m scripts.inject_fraud --scenario international --customer-id <uuid>
  python -m scripts.inject_fraud --scenario amount_spike  --customer-id <uuid>
  python -m scripts.inject_fraud --scenario freq_burst    --customer-id <uuid>
  python -m scripts.inject_fraud --scenario all           --customer-id <uuid>
  python -m scripts.inject_fraud --scenario combined      --dry-run
        """,
    )
    parser.add_argument(
        "--scenario",
        choices=["international", "amount_spike", "freq_burst", "combined", "all"],
        required=True,
        help="Which fraud scenario to inject",
    )
    parser.add_argument(
        "--customer-id",
        dest="customer_id",
        default=None,
        help="Target customer UUID. Omit to pick a random customer.",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="Print what would be sent without publishing to Kafka",
    )
    args = parser.parse_args()

    # ── Connect ───────────────────────────────────────────────────────────────
    print(f"\n{BOLD}Sentinel PFD — Fraud Scenario Injector{RESET}")
    print("─" * 52)

    conn     = _get_db()
    customer = _fetch_customer(args.customer_id, conn)

    print(f"  Target customer : {BOLD}{customer['first_name']} {customer['last_name']}{RESET}")
    print(f"  customer_id     : {customer['customer_id']}")
    print(f"  monthly_income  : ₹{float(customer.get('monthly_income') or 0):,.0f}")
    if args.dry_run:
        print(f"  {YELLOW}Mode: DRY RUN — no Kafka messages will be published{RESET}")

    producer = None if args.dry_run else _get_producer()

    scenarios_to_run = (
        ["international", "amount_spike", "freq_burst", "combined"]
        if args.scenario == "all"
        else [args.scenario]
    )

    for scenario in scenarios_to_run:
        if scenario == "international":
            run_international(customer, producer, args.dry_run)
        elif scenario == "amount_spike":
            run_amount_spike(customer, conn, producer, args.dry_run)
        elif scenario == "freq_burst":
            run_freq_burst(customer, conn, producer, args.dry_run)
        elif scenario == "combined":
            run_combined(customer, conn, producer, args.dry_run)

        if len(scenarios_to_run) > 1 and scenario != scenarios_to_run[-1]:
            print(f"\n  {YELLOW}── Waiting 3s before next scenario …{RESET}")
            time.sleep(3)

    conn.close()
    print(f"\n{GREEN}{BOLD}✓ Injection complete.{RESET}\n")


if __name__ == "__main__":
    main()