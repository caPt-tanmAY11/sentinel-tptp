"""
database/seed.py
─────────────────────────────────────────────────────────────────────────────
Seeds PostgreSQL with:
  1. Customer profiles
  2. Loans per customer
  3. Credit cards per customer
  4. 120-day raw transaction history per customer

Run via: python run_pipeline.py --step seed
─────────────────────────────────────────────────────────────────────────────
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import psycopg2
from psycopg2.extras import execute_values
from datetime import date
from tqdm import tqdm

from config.settings import get_settings
from data_generator.customer_generator import generate_all_customers
from data_generator.raw_transaction_generator import RawTransactionGenerator

settings = get_settings()
INIT_SQL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "init.sql")


# ── Database connection ───────────────────────────────────────────────────────

def get_connection():
    return psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )


# ── Schema management ─────────────────────────────────────────────────────────

def ensure_schema(conn):
    """Run init.sql if the customers table doesn't exist yet."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'customers'
        )
    """)
    exists = cursor.fetchone()[0]
    if not exists:
        print("  Schema not found — running init.sql...")
        with open(INIT_SQL_PATH, "r") as f:
            sql = f.read()
        cursor.execute(sql)
        conn.commit()
        print("  ✓ Schema created")
    else:
        print("  ✓ Schema already exists")
    cursor.close()


def truncate_all(conn):
    """Truncate all tables for a clean re-seed."""
    cursor = conn.cursor()
    cursor.execute("""
        TRUNCATE TABLE
            transaction_pulse_events,
            pulse_scores,
            customer_baselines,
            transactions,
            credit_cards,
            loans,
            customers
        RESTART IDENTITY CASCADE
    """)
    conn.commit()
    cursor.close()
    print("  ✓ All tables truncated")


# ── Insert helpers ────────────────────────────────────────────────────────────

def seed_customers(conn, customers):
    print(f"  Inserting {len(customers)} customers...")
    cursor = conn.cursor()
    today = date.today()

    values = []
    for c in customers:
        open_date = date.fromisoformat(c["account_open_date"])
        vintage_months = (today.year - open_date.year) * 12 + (today.month - open_date.month)

        values.append((
            c["customer_id"],
            c["first_name"],
            c["last_name"],
            c["email"],
            c["phone"],
            c["date_of_birth"],
            c["gender"],
            c["pan_number"],
            c["aadhaar_hash"],
            c["employment_type"],
            c.get("employer_id"),
            c.get("employer_name"),
            c["monthly_income"],
            c["expected_salary_day"],
            c["state"],
            c["city"],
            c["pincode"],
            c["geography_risk_tier"],
            c["customer_segment"],
            c["account_id"],
            c["account_number"],
            c.get("account_type", "SAVINGS"),
            c["account_open_date"],
            vintage_months,
            c.get("upi_vpa"),
            c.get("ifsc_code"),
            c.get("opening_balance", 0),
            c.get("historical_delinquency_count", 0),
            c.get("credit_bureau_score"),
        ))

    execute_values(cursor, """
        INSERT INTO customers (
            customer_id, first_name, last_name, email, phone,
            date_of_birth, gender, pan_number, aadhaar_hash,
            employment_type, employer_id, employer_name,
            monthly_income, expected_salary_day,
            state, city, pincode, geography_risk_tier, customer_segment,
            account_id, account_number, account_type, account_open_date,
            customer_vintage_months, upi_vpa, ifsc_code, opening_balance,
            historical_delinquency_count, credit_bureau_score
        ) VALUES %s
        ON CONFLICT (customer_id) DO NOTHING
    """, values, page_size=200)

    conn.commit()
    cursor.close()
    print(f"  ✓ {len(customers)} customers inserted")


def seed_loans(conn, loans):
    if not loans:
        print("  No loans to insert")
        return
    print(f"  Inserting {len(loans)} loans...")
    cursor = conn.cursor()

    values = [(
        l["loan_id"],
        l["loan_account_number"],
        l["customer_id"],
        l["loan_type"],
        l["sanctioned_amount"],
        l["outstanding_principal"],
        l["emi_amount"],
        l["emi_due_date"],
        l["interest_rate"],
        l["tenure_months"],
        l["remaining_tenure"],
        l["disbursement_date"],
        l.get("days_past_due", 0),
        l.get("failed_auto_debit_count_30d", 0),
        l.get("nach_vpa"),
        l.get("nach_rrn_prefix"),
        l.get("status", "ACTIVE"),
    ) for l in loans]

    execute_values(cursor, """
        INSERT INTO loans (
            loan_id, loan_account_number, customer_id, loan_type,
            sanctioned_amount, outstanding_principal, emi_amount, emi_due_date,
            interest_rate, tenure_months, remaining_tenure, disbursement_date,
            days_past_due, failed_auto_debit_count_30d,
            nach_vpa, nach_rrn_prefix, status
        ) VALUES %s
        ON CONFLICT (loan_id) DO NOTHING
    """, values, page_size=200)

    conn.commit()
    cursor.close()
    print(f"  ✓ {len(loans)} loans inserted")


def seed_credit_cards(conn, cards):
    if not cards:
        print("  No credit cards to insert")
        return
    print(f"  Inserting {len(cards)} credit cards...")
    cursor = conn.cursor()

    values = [(
        c["card_id"],
        c["card_account_number"],
        c["customer_id"],
        c["credit_limit"],
        c["current_balance"],
        c["credit_utilization_pct"],
        c["min_payment_due"],
        c["min_payment_made"],
        c["bureau_enquiry_count_90d"],
        c.get("payment_due_date", 10),
        c.get("status", "ACTIVE"),
    ) for c in cards]

    execute_values(cursor, """
        INSERT INTO credit_cards (
            card_id, card_account_number, customer_id,
            credit_limit, current_balance, credit_utilization_pct,
            min_payment_due, min_payment_made, bureau_enquiry_count_90d,
            payment_due_date, status
        ) VALUES %s
        ON CONFLICT (card_id) DO NOTHING
    """, values, page_size=200)

    conn.commit()
    cursor.close()
    print(f"  ✓ {len(cards)} credit cards inserted")


def seed_transactions(conn, customers, all_loans, batch_size=50):
    """
    Generate and insert transactions for all customers in batches.
    Uses customer-specific seeds for reproducibility.
    """
    print(f"  Generating and inserting transactions for {len(customers)} customers...")

    # Build a lookup: customer_id → list of loans
    loans_by_customer = {}
    for loan in all_loans:
        cid = loan["customer_id"]
        loans_by_customer.setdefault(cid, []).append(loan)

    total_txns = 0
    cursor = conn.cursor()

    for i, customer in enumerate(tqdm(customers, desc="  Generating transactions", unit="cust")):
        cid = customer["customer_id"]
        customer_loans = loans_by_customer.get(cid, [])

        # Deterministic seed per customer
        cust_seed = hash(cid) % (2**31)

        generator = RawTransactionGenerator(
            customer=customer,
            loans=customer_loans,
            credit_card=None,   # credit card transactions added in future layer
            seed=cust_seed,
        )
        txns = generator.generate(days_back=settings.BASELINE_HISTORY_TOTAL_DAYS)

        if not txns:
            continue

        values = [(
            t["transaction_id"],
            t["customer_id"],
            t["account_number"],
            t.get("sender_id"),
            t.get("sender_name"),
            t.get("receiver_id"),
            t.get("receiver_name"),
            t["amount"],
            t["platform"],
            t["payment_status"],
            t.get("reference_number"),
            t.get("balance_before"),
            t.get("balance_after"),
            t["txn_timestamp"],
        ) for t in txns]

        execute_values(cursor, """
            INSERT INTO transactions (
                transaction_id, customer_id, account_number,
                sender_id, sender_name,
                receiver_id, receiver_name,
                amount, platform, payment_status, reference_number,
                balance_before, balance_after,
                txn_timestamp
            ) VALUES %s
            ON CONFLICT DO NOTHING
        """, values, page_size=500)

        total_txns += len(txns)

        # Commit in batches to avoid holding large transactions
        if (i + 1) % batch_size == 0:
            conn.commit()

    conn.commit()
    cursor.close()
    print(f"  ✓ {total_txns:,} transactions inserted")
    return total_txns


# ── Verification queries ──────────────────────────────────────────────────────

def print_seed_summary(conn):
    """Print a summary of what was seeded."""
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM customers")
    n_customers = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM loans")
    n_loans = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM credit_cards")
    n_cards = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM transactions")
    n_txns = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM transactions WHERE payment_status = 'failed'
    """)
    n_failed = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(DISTINCT customer_id) FROM transactions
        WHERE receiver_id ILIKE '%@upi'
        AND receiver_id IN (
            'slice@upi','lazypay@upi','simpl@upi','fibe@ybl',
            'cashe@upi','kreditbee@upi','mpokket@upi','navi@hdfcbank'
        )
    """)
    n_lending_customers = cursor.fetchone()[0]

    cursor.execute("""
        SELECT platform, COUNT(*) as cnt
        FROM transactions
        GROUP BY platform
        ORDER BY cnt DESC
    """)
    platform_counts = cursor.fetchall()

    cursor.close()

    print()
    print("=" * 55)
    print("  SENTINEL V2 — Seed Summary")
    print("=" * 55)
    print(f"  Customers:              {n_customers:>8,}")
    print(f"  Loans:                  {n_loans:>8,}")
    print(f"  Credit cards:           {n_cards:>8,}")
    print(f"  Transactions (total):   {n_txns:>8,}")
    print(f"  Failed transactions:    {n_failed:>8,}")
    print(f"  Customers with lending  ")
    print(f"    app transfers:        {n_lending_customers:>8,}")
    print()
    print("  Transactions by platform:")
    for platform, cnt in platform_counts:
        print(f"    {platform:<12} {cnt:>8,}")
    print("=" * 55)


# ── Main entry point ──────────────────────────────────────────────────────────

def run_seed(n_customers=None, truncate=False):
    """
    Full seed run.

    Args:
        n_customers: Override NUM_CUSTOMERS from settings (useful for testing).
        truncate:    If True, truncates all tables before seeding.
    """
    start = time.time()
    print()
    print("=" * 55)
    print("  SENTINEL V2 — Database Seeding")
    print("=" * 55)

    conn = get_connection()

    try:
        print("\n[1/6] Schema check...")
        ensure_schema(conn)

        if truncate:
            print("\n[1b] Truncating existing data...")
            truncate_all(conn)

        print(f"\n[2/6] Generating {n_customers or settings.NUM_CUSTOMERS} customer profiles...")
        customers, all_loans, all_credit_cards = generate_all_customers(
            n=n_customers,
            seed=42,
        )
        print(f"  ✓ {len(customers)} customers, {len(all_loans)} loans, {len(all_credit_cards)} cards")

        print("\n[3/6] Inserting customers...")
        seed_customers(conn, customers)

        print("\n[4/6] Inserting loans...")
        seed_loans(conn, all_loans)

        print("\n[5/6] Inserting credit cards...")
        seed_credit_cards(conn, all_credit_cards)

        print("\n[6/6] Generating and inserting transactions...")
        print(f"  (120 days × {len(customers)} customers — this takes 2–5 minutes)")
        seed_transactions(conn, customers, all_loans)

        print_seed_summary(conn)

    finally:
        conn.close()

    elapsed = time.time() - start
    print(f"\n  Total time: {elapsed:.1f}s")
    print("  Seeding complete.\n")


if __name__ == "__main__":
    run_seed(truncate=True)