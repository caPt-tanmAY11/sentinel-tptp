"""
scripts/build_baselines.py
─────────────────────────────────────────────────────────────────────────────
Builds statistical baselines for all customers in the database.
Run via: python run_pipeline.py --step baselines

Uses only days 1–90 of history. Real-time window never touched.
─────────────────────────────────────────────────────────────────────────────
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from psycopg2.extras import RealDictCursor
from tqdm import tqdm

from config.settings import get_settings
from baseline.baseline_builder import build_customer_baseline

settings = get_settings()


def _get_redis():
    try:
        import redis
        r = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True)
        r.ping()
        print("  ✓ Redis connected")
        return r
    except Exception as e:
        print(f"  ⚠ Redis unavailable: {e}. Writing to PostgreSQL only.")
        return None


def run_build_baselines():
    start = time.time()
    print()
    print("=" * 55)
    print("  SENTINEL V2 — Building Customer Baselines")
    print("=" * 55)
    print(f"  Baseline window:    days 1–{settings.BASELINE_WINDOW_DAYS} of history")
    print(f"  Snapshot interval:  every {settings.BASELINE_SNAPSHOT_INTERVAL_DAYS} days")
    print(f"  Min transactions:   {settings.BASELINE_MIN_TRANSACTIONS}")
    print()

    conn = psycopg2.connect(
        host=settings.POSTGRES_HOST, port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB, user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )
    redis_client = _get_redis()

    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT customer_id FROM customers ORDER BY customer_id")
    customer_ids = [str(r["customer_id"]) for r in cursor.fetchall()]
    cursor.close()

    print(f"  Customers: {len(customer_ids):,}")

    ok, low_conf, errors = 0, 0, 0

    for cid in tqdm(customer_ids, desc="  Building", unit="cust"):
        try:
            bl = build_customer_baseline(cid, conn=conn, redis_client=redis_client)
            if bl:
                ok += 1
                if bl.low_confidence:
                    low_conf += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"\n  ⚠ Error for {cid[:8]}…: {e}")

    conn.close()

    print()
    print("=" * 55)
    print(f"  Baselines built:     {ok:>6,}")
    print(f"  Low confidence:      {low_conf:>6,}  (< {settings.BASELINE_MIN_TRANSACTIONS} txns)")
    print(f"  Errors:              {errors:>6,}")
    print(f"  Time:                {time.time()-start:>6.1f}s")
    print("=" * 55)


if __name__ == "__main__":
    run_build_baselines()