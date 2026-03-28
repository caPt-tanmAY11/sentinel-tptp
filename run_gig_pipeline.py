"""
run_gig_pipeline.py
─────────────────────────────────────────────────────────────────────────────
SENTINEL V2 — Gig Worker End-to-End Pipeline

A fully self-contained pipeline that demonstrates the complete gig worker
stress detection workflow from DB setup through real-time assessment.

Steps
─────
  migrate     Apply gig_worker_migration.sql — creates assessment + income tables
  train       Train the GigStressClassifier on 500 simulated workers
  simulate    Batch-generate N workers, inject to DB, classify all
  realtime    Continuously inject workers one-by-one (Ctrl+C to stop)
  report      Query DB and print a full stress assessment report
  truncate    Truncate all gig worker DB tables (with confirmation prompt)
  all         migrate → train → simulate → report  (recommended first run)

Usage examples
──────────────
  # Full pipeline (first run):
  python run_gig_pipeline.py --step all

  # Real-time mode — infinite loop of FOOD_DELIVERY workers at 1/s:
  python run_gig_pipeline.py --step realtime --worker-type FOOD_DELIVERY

  # Real-time mode — 20 RIDE_SHARE workers then stop:
  python run_gig_pipeline.py --step realtime --worker-type RIDE_SHARE --count 20

  # Batch simulate 100 random gig workers:
  python run_gig_pipeline.py --step simulate --count 100

  # Just show the DB report:
  python run_gig_pipeline.py --step report

  # Truncate all gig worker tables (prompts for confirmation):
  python run_gig_pipeline.py --step truncate

Worker types
────────────
  all  RIDE_SHARE  FOOD_DELIVERY  QUICK_COMMERCE  HOME_SERVICES
  LOGISTICS  FIELD_SERVICES  GENERAL_GIG  ECOMMERCE_RESELLER

─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import json
import os
import random
import signal
import string
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta, date
from typing import Any, Dict, List, Optional, Tuple

# ── Sentinel imports (no existing code modified) ──────────────────────────────
from config.settings import get_settings
from gig_worker.gig_worker_simulator import (
    GIG_PLATFORMS,
    WEEKLY_INCOME_BY_CATEGORY,
    GigWorkerProfile,
    _generate_profile,
    _simulate_weekly_payouts,
    pairs_to_feature_records,
)
from gig_worker.gig_stress_classifier import GigStressClassifier, MODEL_PATH
from gig_worker.gig_realtime_injector import (
    VALID_WORKER_TYPES,
    _db_connect,
    _apply_migration,
    _profile_to_customer_row,
    _generate_payout_txn,
    _generate_spend_txn,
    _attach_balances,
    _insert_customer,
    _insert_transactions,
    _insert_assessment,
    _SPEND_POOL,
    _SPEND_WEIGHTS,
)

import psycopg2
import psycopg2.extras

settings = get_settings()

# ── Colour helpers (ANSI, safe on Windows via sys.stdout.write) ───────────────
_USE_COLOUR = sys.stdout.isatty() and os.name != "nt"

def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOUR else text

def _green(t):  return _c(t, "32")
def _red(t):    return _c(t, "31")
def _yellow(t): return _c(t, "33")
def _bold(t):   return _c(t, "1")
def _cyan(t):   return _c(t, "36")
def _dim(t):    return _c(t, "2")


# ── Weekly income DB insert ────────────────────────────────────────────────────

def _insert_weekly_income(
    conn: psycopg2.extensions.connection,
    customer_id: str,
    assessment_id: str,
    profile: GigWorkerProfile,
    pair_predictions: List[Dict[str, Any]],
) -> int:
    """
    Insert one row per week into gig_worker_weekly_income.

    For each week N > 1, the model's prediction for the (week N-1, week N) pair
    is stored as triggered_stress / wow_change_pct.
    Week 1 has no prior pair so triggered_stress = False.

    Returns number of rows inserted.
    """
    now_utc   = datetime.now(timezone.utc)
    base_date = (now_utc - timedelta(weeks=len(profile.weekly_payouts))).date()

    # Index pair predictions by curr_week_num for fast lookup
    pair_by_week: Dict[int, Dict] = {p["curr_week_num"]: p for p in pair_predictions}

    rows: List[Dict] = []
    for record in profile.weekly_payouts:
        week_start = base_date + timedelta(weeks=record.week_num - 1)
        pair = pair_by_week.get(record.week_num)
        rows.append({
            "income_id":        str(uuid.uuid4()),
            "customer_id":      customer_id,
            "assessment_id":    assessment_id,
            "week_num":         record.week_num,
            "week_label":       record.week_label,
            "week_start_date":  week_start.isoformat(),
            "payout_amount":    round(record.payout_amount, 2),
            "platform_vpa":     record.platform_vpa,
            "platform_name":    record.platform_name,
            # drop_pct from (prev, curr) pair; None for week 1 (no prev)
            "wow_change_pct":   round(pair["drop_pct"] * -1, 4) if pair else None,
            "is_stress_week":   record.is_stress_week,
            # triggered_stress = model prediction for this pair
            "triggered_stress": bool(pair["is_stressed"]) if pair else False,
        })

    sql = """
        INSERT INTO gig_worker_weekly_income (
            income_id, customer_id, assessment_id,
            week_num, week_label, week_start_date,
            payout_amount, platform_vpa, platform_name,
            wow_change_pct, is_stress_week, triggered_stress
        ) VALUES (
            %(income_id)s, %(customer_id)s, %(assessment_id)s,
            %(week_num)s, %(week_label)s, %(week_start_date)s,
            %(payout_amount)s, %(platform_vpa)s, %(platform_name)s,
            %(wow_change_pct)s, %(is_stress_week)s, %(triggered_stress)s
        ) ON CONFLICT DO NOTHING
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows, page_size=50)
    conn.commit()
    return len(rows)


def _insert_assessment_returning_id(
    conn: psycopg2.extensions.connection,
    customer_id: str,
    profile: GigWorkerProfile,
    prediction: Dict[str, Any],
    txn_count: int,
) -> str:
    """Same as gig_realtime_injector._insert_assessment but returns assessment_id."""
    recent_records  = profile.weekly_payouts[-8:]
    income_snapshot = [
        {
            "week":           r.week_label,
            "amount":         r.payout_amount,
            "wow_change":     round(r.wow_change * 100, 2),
            "is_stress_week": r.is_stress_week,
        }
        for r in recent_records
    ]
    wow_snapshot = [
        {"week": r.week_label, "wow_change_pct": round(r.wow_change * 100, 2)}
        for r in recent_records if r.week_num > 1
    ]
    trigger_week = next(
        (r.week_num for r in profile.weekly_payouts if r.week_num >= 13 and r.wow_change < -0.50),
        None,
    )
    assessment_id = str(uuid.uuid4())
    sql = """
        INSERT INTO gig_worker_stress_assessments (
            assessment_id, customer_id,
            platform_vpa, platform_name, platform_category,
            baseline_weekly_income, weeks_simulated,
            weekly_income_snapshot, wow_changes_snapshot,
            max_wow_drop_pct, stress_probability,
            is_stressed, stress_label, stress_trigger_week,
            model_version, injected_txn_count, assessed_at
        ) VALUES (
            %(assessment_id)s, %(customer_id)s,
            %(platform_vpa)s, %(platform_name)s, %(platform_category)s,
            %(baseline_weekly_income)s, %(weeks_simulated)s,
            %(weekly_income_snapshot)s, %(wow_changes_snapshot)s,
            %(max_wow_drop_pct)s, %(stress_probability)s,
            %(is_stressed)s, %(stress_label)s, %(stress_trigger_week)s,
            %(model_version)s, %(injected_txn_count)s, NOW()
        )
    """
    params = {
        "assessment_id":          assessment_id,
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
    return assessment_id


# ── Per-week display helper ────────────────────────────────────────────────────

def _print_worker_week_table(
    seq: int,
    profile: GigWorkerProfile,
    pair_results: List[Dict[str, Any]],
    prediction: Dict[str, Any],
    txn_count: int,
) -> None:
    """
    Print a week-by-week income + stress table for one worker.

    Columns: Week | Prev Income | Curr Income | Drop% | Model Prob | Stress
    """
    verdict = _red("STRESSED") if prediction["predicted_stressed"] else _green("NOT_STRESSED")
    print(
        f"\n  Worker #{seq}  {_bold(profile.full_name)}"
        f"  |  {profile.platform_category}  |  {profile.platform_name}"
        f"  |  {profile.city}"
        f"  |  Baseline Rs{profile.baseline_weekly_income:,.0f}/wk"
    )
    print(
        f"  {'Wk':>4}  {'Prev Income':>12}  {'Curr Income':>12}  "
        f"{'Drop%':>8}  {'Prob':>6}  Status"
    )
    print("  " + _dim("─" * 66))

    # Week 1: no prev pair
    w1 = profile.weekly_payouts[0]
    print(
        f"  W{w1.week_num:02d}  "
        f"{'—':>12}  "
        f"Rs{w1.payout_amount:>10,.0f}  "
        f"{'—':>8}  {'—':>6}  —"
    )

    for r in pair_results:
        drop_str   = f"{r['drop_pct']:+.1f}%" if r["drop_pct"] != 0 else "  0.0%"
        stress_col = _red("!! STRESSED") if r["is_stressed"] else _dim("OK")
        print(
            f"  W{r['curr_week_num']:02d}  "
            f"Rs{r['prev_week_income']:>10,.0f}  "
            f"Rs{r['curr_week_income']:>10,.0f}  "
            f"{drop_str:>8}  {r['stress_probability']:>5.3f}  {stress_col}"
        )

    print("  " + _dim("─" * 66))
    print(
        f"  Verdict: {verdict}  "
        f"|  Max drop: {prediction['max_wow_drop_pct']:+.1f}%  "
        f"|  Txns injected: {txn_count}"
    )


# ── Core per-worker pipeline function ─────────────────────────────────────────

def _process_one_worker(
    conn: psycopg2.extensions.connection,
    clf: GigStressClassifier,
    platforms: List[Tuple[str, str, str]],
    rng: random.Random,
    seq: int,
    n_weeks: int = 16,
    print_table: bool = True,
) -> Dict[str, Any]:
    """
    Complete single-worker pipeline:

      1. Generate profile
      2. Insert into customers
      3. Simulate transactions → insert
      4. Pass each consecutive (prev_income, curr_income) pair to the model
      5. Insert assessment summary
      6. Insert weekly income rows with per-week stress flags from the model

    Returns result dict.
    """
    import numpy as np

    # 1. Generate profile
    profile = _generate_profile(rng, idx=seq)
    vpa, name, category = rng.choice(platforms)
    lo, hi = WEEKLY_INCOME_BY_CATEGORY[category]
    profile.platform_vpa      = vpa
    profile.platform_name     = name
    profile.platform_category = category
    profile.baseline_weekly_income = round(rng.uniform(lo, hi) / 100) * 100

    payout_rng    = random.Random(rng.randint(0, 2 ** 31))
    payout_np_rng = np.random.default_rng(rng.randint(0, 2 ** 31))
    profile.weekly_payouts = _simulate_weekly_payouts(
        profile, n_weeks=n_weeks, rng=payout_rng, np_rng=payout_np_rng,
    )

    # 2. Build customer row + insert
    cust_row = _profile_to_customer_row(profile, rng, seq)
    _insert_customer(conn, cust_row)

    # 3. Generate transactions (weekly payouts + daily spending)
    now_utc = datetime.now(timezone.utc)
    base_dt = now_utc - timedelta(weeks=n_weeks)
    txns: List[Dict] = []
    monthly = float(cust_row["monthly_income"])

    for record in profile.weekly_payouts:
        txns.append(_generate_payout_txn(record, cust_row, base_dt, rng))

    for day_offset in range(n_weeks * 7):
        day_dt  = base_dt + timedelta(days=day_offset)
        n_spend = rng.randint(2, 4)
        for _ in range(n_spend):
            txns.append(_generate_spend_txn(cust_row, day_dt, monthly, rng))

    _attach_balances(txns, float(cust_row["opening_balance"]))
    txn_count = _insert_transactions(conn, txns)

    # 4. Pass each consecutive (prev, curr) income pair to the model one by one
    pair_results = []
    for i in range(1, len(profile.weekly_payouts)):
        prev_rec = profile.weekly_payouts[i - 1]
        curr_rec = profile.weekly_payouts[i]
        result   = clf.predict_pair(
            prev_week_income=float(prev_rec.payout_amount),
            curr_week_income=float(curr_rec.payout_amount),
        )
        result["prev_week_num"]   = prev_rec.week_num
        result["curr_week_num"]   = curr_rec.week_num
        result["curr_week_label"] = curr_rec.week_label
        pair_results.append(result)

    # Derive worker-level summary from pair results
    any_stressed = any(r["is_stressed"] for r in pair_results)
    max_prob     = max((r["stress_probability"] for r in pair_results), default=0.0)
    max_drop     = max((r["drop_pct"] for r in pair_results if r["drop_pct"] > 0), default=0.0)

    prediction = {
        "stress_probability":  round(max_prob, 4),
        "predicted_stressed":  any_stressed,
        "stress_label":        "STRESSED" if any_stressed else "NOT_STRESSED",
        "max_wow_drop_pct":    round(max_drop, 1),
        "pair_results":        pair_results,
    }

    # 5. Insert assessment (returns assessment_id)
    assessment_id = _insert_assessment_returning_id(
        conn, profile.worker_id, profile, prediction, txn_count
    )

    # 6. Insert per-week income rows — stressed flag comes from model pair prediction
    _insert_weekly_income(
        conn, profile.worker_id, assessment_id, profile, pair_results
    )

    # 7. Print week-by-week table
    if print_table:
        _print_worker_week_table(seq, profile, pair_results, prediction, txn_count)

    return {
        "worker_id":         profile.worker_id,
        "assessment_id":     assessment_id,
        "name":              profile.full_name,
        "city":              profile.city,
        "platform_name":     profile.platform_name,
        "platform_category": profile.platform_category,
        "baseline_weekly":   profile.baseline_weekly_income,
        "max_wow_drop":      max_drop / 100.0,
        "stress_prob":       prediction["stress_probability"],
        "stress_label":      prediction["stress_label"],
        "is_stressed":       prediction["predicted_stressed"],
        "txn_count":         txn_count,
        "weeks":             n_weeks,
    }


# ── Step: migrate ─────────────────────────────────────────────────────────────

def step_migrate(args) -> None:
    print()
    print(_bold("=" * 68))
    print(_bold("  STEP: migrate — Apply Gig Worker DB Migration"))
    print(_bold("=" * 68))

    conn = _db_connect()
    _apply_migration(conn)
    conn.close()

    print(_green("  [OK] gig_worker_stress_assessments — ready"))
    print(_green("  [OK] gig_worker_weekly_income       — ready"))
    print()


# ── Step: train ───────────────────────────────────────────────────────────────

def step_train(args) -> GigStressClassifier:
    n = getattr(args, "train_workers", 500)
    print()
    print(_bold("=" * 68))
    print(_bold(f"  STEP: train — GigStressClassifier ({n} simulated workers)"))
    print(_bold(f"  Features : prev_week_income, curr_week_income (2 raw values)"))
    print(_bold(f"  Label    : (prev - curr) / prev > 50%  →  STRESSED"))
    print(_bold("=" * 68))

    clf = GigStressClassifier()
    clf.train(n_workers=n, seed=42, save=True)
    print()
    return clf


# ── Step: simulate (batch) ────────────────────────────────────────────────────

def _auto_clear_gig_data(conn: psycopg2.extensions.connection) -> int:
    """
    Remove all existing gig worker records before a fresh simulate run.

    Deletes GIG_WORKER customers — which cascades through:
      customers → transactions
      customers → gig_worker_stress_assessments → gig_worker_weekly_income

    Returns the number of customers deleted.
    """
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM customers WHERE employment_type = 'GIG_WORKER' "
            "RETURNING customer_id"
        )
        deleted = cur.rowcount
    conn.commit()
    return deleted


def step_simulate(args, clf: Optional[GigStressClassifier] = None) -> None:
    n           = getattr(args, "count", 50)
    worker_type = getattr(args, "worker_type", "all")
    n_weeks     = getattr(args, "weeks", 16)

    print()
    print(_bold("=" * 68))
    print(_bold(f"  STEP: simulate — {n} Gig Workers  ({worker_type})"))
    print(_bold(f"  Simulation window : {n_weeks} weeks per worker"))
    print(_bold(f"  Model input       : (prev_week_income, curr_week_income) pairs"))
    print(_bold("=" * 68))

    if clf is None:
        clf = GigStressClassifier()
        if os.path.exists(MODEL_PATH):
            clf.load()
        else:
            print(_yellow("  [!] No saved model — training now…"))
            clf.train(n_workers=500, seed=42, save=True)

    conn = _db_connect()
    _apply_migration(conn)

    # Auto-clear previous gig worker data so each simulate run is fresh
    deleted = _auto_clear_gig_data(conn)
    if deleted > 0:
        print(_dim(f"  [clear] Removed {deleted} previous GIG_WORKER records (customers + cascades)"))

    platforms = _filter_platforms(worker_type)
    rng       = random.Random(int.from_bytes(os.urandom(8), "big"))

    results: List[Dict] = []
    stressed = 0
    t0 = time.time()

    for i in range(1, n + 1):
        try:
            r = _process_one_worker(
                conn, clf, platforms, rng,
                seq=i, n_weeks=n_weeks, print_table=True,
            )
            results.append(r)
            stressed += int(r["is_stressed"])
        except Exception as exc:
            import traceback
            print(_yellow(f"\n  Worker #{i}  ERROR: {exc}"))
            traceback.print_exc()

    elapsed = time.time() - t0
    conn.close()

    print()
    print(_bold("=" * 68))
    print(_bold("  Simulation complete"))
    _print_summary(results, stressed, elapsed, n_weeks)
    print()


# ── Step: realtime ────────────────────────────────────────────────────────────

def step_realtime(args) -> None:
    worker_type = getattr(args, "worker_type", "all")
    tps         = max(0.1, getattr(args, "tps", 1.0))
    limit       = getattr(args, "count", None)   # None = infinite
    n_weeks  = getattr(args, "weeks", 16)
    interval = 1.0 / tps

    print()
    print(_bold("=" * 68))
    print(_bold("  STEP: realtime — Continuous Gig Worker Injection"))
    print(_bold(f"  Worker type : {worker_type}"))
    print(_bold(f"  TPS         : {tps}  |  Limit: {limit if limit else 'infinite (Ctrl+C to stop)'}"))
    print(_bold(f"  Weeks/worker: {n_weeks}"))
    print(_bold("=" * 68))

    # Load / train classifier once
    clf = GigStressClassifier()
    if os.path.exists(MODEL_PATH):
        clf.load()
    else:
        print(_yellow("  [!] No saved model — training now…"))
        clf.train(n_workers=500, seed=42, save=True)

    conn      = _db_connect()
    _apply_migration(conn)
    platforms = _filter_platforms(worker_type)
    rng       = random.Random(int.from_bytes(os.urandom(8), "big"))

    # Graceful shutdown on Ctrl+C
    _stop = {"flag": False}
    def _handle_sigint(sig, frame):
        _stop["flag"] = True
        print(_yellow("\n\n  [Ctrl+C] Stopping after current worker…"))
    signal.signal(signal.SIGINT, _handle_sigint)

    # Header (reprinted every 25 workers)
    def _print_header():
        hdr = (
            f"\n  {'#':>5}  {'Name':<22} {'Category':<20} {'City':<12} "
            f"{'Rs/wk':>8} {'WoW Drop':>9} {'Prob':>6}  {'Verdict':<15} "
            f"{'Trigger Wk':>10}  Txns"
        )
        print(_bold(hdr))
        print("  " + _dim("-" * (len(hdr) - 2)))

    _print_header()

    results: List[Dict] = []
    stressed = 0
    seq      = 0
    t0       = time.time()

    try:
        while not _stop["flag"]:
            seq += 1
            if limit and seq > limit:
                break

            loop_start = time.time()
            try:
                r = _process_one_worker(
                    conn, clf, platforms, rng,
                    seq=seq, n_weeks=n_weeks, print_table=False,
                )
                results.append(r)
                stressed += int(r["is_stressed"])

                wow_str     = f"{r['max_wow_drop']*100:+.1f}%" if r["max_wow_drop"] > 0 else "  —  "
                verdict_str = _red("STRESSED [!]   ") if r["is_stressed"] else _green("NOT_STRESSED   ")
                trigger_str = f"Week {r.get('trigger_week', '—')}" if r["is_stressed"] else "  —  "

                # Running stats suffix
                pct_stressed = stressed / len(results) * 100
                stats_str    = _dim(f"  [{stressed}/{len(results)} stressed = {pct_stressed:.0f}%]")

                print(
                    f"  {seq:>5}  {r['name']:<22} {r['platform_category']:<20} "
                    f"{r['city']:<12} {r['baseline_weekly']:>8,.0f} "
                    f"  {wow_str:>8}  {r['stress_prob']:>5.2f}  {verdict_str}"
                    f"{r['txn_count']:>5} txns{stats_str}"
                )

                # Re-print header every 25 workers
                if seq % 25 == 0:
                    _print_header()

            except Exception as exc:
                print(_yellow(f"  {seq:>5}  ERROR: {exc}"))

            # Rate-limit
            elapsed_worker = time.time() - loop_start
            sleep_time     = max(0.0, interval - elapsed_worker)
            if sleep_time > 0 and not _stop["flag"]:
                time.sleep(sleep_time)

    finally:
        conn.close()
        elapsed = time.time() - t0
        print()
        print(_bold("=" * 68))
        print(_bold("  Real-time injection stopped."))
        _print_summary(results, stressed, elapsed)
        print()


# ── Step: report ──────────────────────────────────────────────────────────────

def step_report(args) -> None:
    limit = getattr(args, "report_rows", 20)

    print()
    print(_bold("=" * 68))
    print(_bold("  STEP: report — Gig Worker Stress DB Report"))
    print(_bold("=" * 68))

    conn = _db_connect()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # ── 1. Overview ──────────────────────────────────────────────────────
    cur.execute("""
        SELECT
            COUNT(*)                                        AS total_assessed,
            COUNT(*) FILTER (WHERE is_stressed = TRUE)     AS total_stressed,
            COUNT(*) FILTER (WHERE is_stressed = FALSE)    AS total_not_stressed,
            ROUND(AVG(stress_probability)::NUMERIC, 4)     AS avg_probability,
            ROUND(AVG(baseline_weekly_income)::NUMERIC, 0) AS avg_weekly_income,
            ROUND(AVG(max_wow_drop_pct)::NUMERIC, 2)       AS avg_max_wow_drop,
            MIN(assessed_at)                               AS first_assessed,
            MAX(assessed_at)                               AS last_assessed
        FROM gig_worker_stress_assessments
    """)
    ov = dict(cur.fetchone() or {})

    total = int(ov.get("total_assessed") or 0)
    if total == 0:
        print(_yellow("\n  No assessments found. Run --step simulate or --step realtime first.\n"))
        conn.close()
        return

    stressed_n = int(ov.get("total_stressed") or 0)
    print(f"\n  {_bold('Overview')}")
    print(f"  {'Total workers assessed':<35} {total:,}")
    print(f"  {'Stressed (prob >= 0.50)':<35} {stressed_n:,}  ({stressed_n/total*100:.1f}%)")
    print(f"  {'Not Stressed':<35} {total-stressed_n:,}  ({(total-stressed_n)/total*100:.1f}%)")
    print(f"  {'Avg stress probability':<35} {ov.get('avg_probability', 0):.4f}")
    print(f"  {'Avg baseline weekly income':<35} Rs {float(ov.get('avg_weekly_income') or 0):,.0f}")
    avg_drop = ov.get("avg_max_wow_drop")
    print(f"  {'Avg max WoW income drop':<35} {float(avg_drop):.1f}%" if avg_drop else "  N/A")
    print(f"  {'First assessment':<35} {str(ov.get('first_assessed',''))[:19]}")
    print(f"  {'Last assessment':<35} {str(ov.get('last_assessed',''))[:19]}")

    # ── 2. By platform category ──────────────────────────────────────────
    cur.execute("""
        SELECT
            platform_category,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE is_stressed) AS stressed,
            ROUND(AVG(stress_probability)::NUMERIC, 3) AS avg_prob,
            ROUND(AVG(baseline_weekly_income)::NUMERIC, 0) AS avg_weekly
        FROM gig_worker_stress_assessments
        GROUP BY platform_category
        ORDER BY stressed DESC, total DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]

    print(f"\n  {_bold('By Platform Category')}")
    print(f"  {'Category':<22} {'Total':>6} {'Stressed':>9} {'Rate':>6} "
          f"{'Avg Prob':>9} {'Avg Rs/wk':>11}")
    print("  " + "-" * 68)
    for r in rows:
        cat      = r["platform_category"]
        tot      = int(r["total"])
        stressed_r = int(r["stressed"])
        rate     = stressed_r / tot * 100 if tot else 0
        bar      = "#" * int(rate / 5)
        print(
            f"  {cat:<22} {tot:>6} {stressed_r:>9} {rate:>5.1f}% "
            f"{float(r['avg_prob']):>9.3f} {float(r['avg_weekly']):>10,.0f}  {_dim(bar)}"
        )

    # ── 3. Weekly income trend (last 16 weeks, across all workers) ───────
    cur.execute("""
        SELECT
            week_num,
            ROUND(AVG(payout_amount)::NUMERIC, 0) AS avg_payout,
            ROUND(AVG(wow_change_pct)::NUMERIC, 2) AS avg_wow,
            COUNT(*) FILTER (WHERE triggered_stress) AS stress_triggers
        FROM gig_worker_weekly_income
        GROUP BY week_num
        ORDER BY week_num
    """)
    weekly = [dict(r) for r in cur.fetchall()]

    if weekly:
        print(f"\n  {_bold('Population-level Weekly Income Trend')}")
        print(f"  {'Week':<8} {'Avg Payout':>12} {'Avg WoW%':>10} {'Stress Triggers':>17}  Trend")
        print("  " + "-" * 68)
        max_pay = max(float(w["avg_payout"]) for w in weekly) or 1
        for w in weekly:
            wk    = int(w["week_num"])
            pay   = float(w["avg_payout"])
            wow   = float(w["avg_wow"]) if w["avg_wow"] is not None else 0.0
            trigs = int(w["stress_triggers"] or 0)
            bar_w = int(pay / max_pay * 30)
            bar   = "=" * bar_w
            stress_marker = _red(" <<< STRESS") if wk >= 13 else ""
            print(
                f"  W{wk:02d}     Rs{pay:>10,.0f}  {wow:>+9.2f}%  {trigs:>17}  "
                f"{_dim(bar)}{stress_marker}"
            )

    # ── 4. Most stressed workers (top N) ────────────────────────────────
    cur.execute(f"""
        SELECT
            c.first_name || ' ' || c.last_name AS name,
            c.city,
            g.platform_category,
            g.platform_name,
            g.baseline_weekly_income,
            g.max_wow_drop_pct,
            g.stress_probability,
            g.stress_trigger_week,
            g.assessed_at
        FROM gig_worker_stress_assessments g
        JOIN customers c ON c.customer_id = g.customer_id
        WHERE g.is_stressed = TRUE
        ORDER BY g.stress_probability DESC, g.max_wow_drop_pct DESC
        LIMIT {limit}
    """)
    top = [dict(r) for r in cur.fetchall()]

    if top:
        print(f"\n  {_bold(f'Top {len(top)} Most Stressed Workers')}")
        print(f"  {'Name':<22} {'City':<12} {'Category':<20} {'Rs/wk':>8} "
              f"{'WoW Drop':>9} {'Prob':>6} {'Trigger':>8}")
        print("  " + "-" * 90)
        for r in top:
            wk  = r["stress_trigger_week"] or "—"
            drop = float(r["max_wow_drop_pct"] or 0)
            print(
                f"  {str(r['name']):<22} {str(r['city']):<12} "
                f"{str(r['platform_category']):<20} "
                f"{float(r['baseline_weekly_income']):>8,.0f} "
                f"  {drop:>8.1f}%  {float(r['stress_probability']):>5.2f}  "
                f"{'Wk '+str(wk) if wk != '—' else '   —':>8}"
            )

    # ── 5. Most recent assessments ───────────────────────────────────────
    cur.execute(f"""
        SELECT
            c.first_name || ' ' || c.last_name AS name,
            g.platform_category,
            g.stress_label,
            g.stress_probability,
            g.injected_txn_count,
            g.assessed_at
        FROM gig_worker_stress_assessments g
        JOIN customers c ON c.customer_id = g.customer_id
        ORDER BY g.assessed_at DESC
        LIMIT {limit}
    """)
    recent = [dict(r) for r in cur.fetchall()]

    if recent:
        print(f"\n  {_bold(f'Last {len(recent)} Assessments')}")
        print(f"  {'Name':<22} {'Category':<20} {'Label':<15} {'Prob':>6} "
              f"{'Txns':>6}  Assessed At")
        print("  " + "-" * 88)
        for r in recent:
            label_str = (
                _red(f"{r['stress_label']:<15}")
                if r["stress_label"] == "STRESSED"
                else _green(f"{r['stress_label']:<15}")
            )
            print(
                f"  {str(r['name']):<22} {str(r['platform_category']):<20} "
                f"{label_str} {float(r['stress_probability']):>6.3f} "
                f"{int(r['injected_txn_count'] or 0):>6}  "
                f"{str(r['assessed_at'])[:19]}"
            )

    conn.close()
    print()
    print(_bold("=" * 68))
    print()


# ── Step: truncate ───────────────────────────────────────────────────────────

def step_truncate(args) -> None:
    """
    Truncate all gig worker tables in the database.

    Affected tables (in FK-safe order):
      1. gig_worker_weekly_income       (child)
      2. gig_worker_stress_assessments  (parent)

    NOTE: This does NOT touch the customers or transactions tables.
    Prompts for confirmation before deleting anything.
    """
    print()
    print(_bold("=" * 68))
    print(_bold("  STEP: truncate — Clear Gig Worker DB Tables"))
    print(_bold("=" * 68))
    print()
    print(_yellow("  WARNING: this will permanently delete ALL GIG_WORKER data:"))
    print(_yellow("    • customers WHERE employment_type = 'GIG_WORKER'"))
    print(_yellow("    • their transactions   (CASCADE)"))
    print(_yellow("    • gig_worker_stress_assessments  (CASCADE)"))
    print(_yellow("    • gig_worker_weekly_income       (CASCADE)"))
    print()
    print("  Non-GIG_WORKER customers and data are NOT touched.")
    print()

    confirm = input("  Type  yes  to confirm, anything else to abort: ").strip().lower()
    if confirm != "yes":
        print(_yellow("\n  Aborted — no data was deleted."))
        print()
        return

    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            # Delete GIG_WORKER customers — cascades to:
            #   transactions, gig_worker_stress_assessments, gig_worker_weekly_income
            cur.execute(
                "DELETE FROM customers WHERE employment_type = 'GIG_WORKER' "
                "RETURNING customer_id"
            )
            deleted_customers = cur.rowcount
        conn.commit()
        print()
        print(_green(f"  [OK] GIG_WORKER customers deleted  : {deleted_customers:,}"))
        print(_green(f"       (transactions, assessments, weekly income cascaded)"))
    finally:
        conn.close()
    print()


# ── Step: all ─────────────────────────────────────────────────────────────────

def step_all(args) -> None:
    t0 = time.time()
    print()
    print(_bold("=" * 68))
    print(_bold("  GIG WORKER PIPELINE — Full End-to-End Run"))
    print(_bold(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"))
    print(_bold("=" * 68))

    step_migrate(args)
    clf = step_train(args)
    step_simulate(args, clf=clf)
    step_report(args)

    print(_bold(f"  PIPELINE COMPLETE  ({time.time()-t0:.1f}s)"))
    print(_bold("=" * 68))
    print()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _filter_platforms(worker_type: str) -> List[Tuple[str, str, str]]:
    if worker_type == "all":
        return GIG_PLATFORMS
    return [p for p in GIG_PLATFORMS if p[2] == worker_type]


def _print_summary(
    results: List[Dict],
    stressed: int,
    elapsed: float,
    n_weeks: int = 16,
) -> None:
    total = len(results)
    if total == 0:
        return
    approx_txns = total * (n_weeks + n_weeks * 3)   # payouts + ~3 spend txns/day
    print(f"\n  Workers processed  : {total}")
    print(f"  STRESSED           : {stressed:>4}  ({stressed/total*100:.1f}%)")
    print(f"  NOT STRESSED       : {total-stressed:>4}  ({(total-stressed)/total*100:.1f}%)")
    print(f"  Elapsed            : {elapsed:.1f}s  ({total/elapsed:.1f} workers/s)")
    print(f"\n  PostgreSQL records written:")
    print(f"    customers                      → {total} rows")
    print(f"    transactions                   → ~{approx_txns:,} rows")
    print(f"    gig_worker_stress_assessments  → {total} rows")
    print(f"    gig_worker_weekly_income       → {total * n_weeks} rows  ({total} workers × {n_weeks} weeks)")
    print(f"    pair predictions stored        → {total * (n_weeks - 1)} week transitions evaluated")


# ── Entry point ───────────────────────────────────────────────────────────────

STEPS = {
    "migrate":  step_migrate,
    "train":    step_train,
    "simulate": step_simulate,
    "realtime": step_realtime,
    "report":   step_report,
    "truncate": step_truncate,
    "all":      step_all,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python run_gig_pipeline.py",
        description="SENTINEL V2 — Gig Worker End-to-End Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Steps:
  migrate    Create/update gig worker tables in PostgreSQL
  train      Train GigStressClassifier on simulated data
  simulate   Batch-inject N gig workers and classify all
  realtime   Continuously inject workers in real-time (Ctrl+C to stop)
  report     Query DB and print full stress assessment report
  truncate   Truncate all gig worker DB tables (prompts for confirmation)
  all        migrate -> train -> simulate -> report

Examples:
  python run_gig_pipeline.py --step all
  python run_gig_pipeline.py --step realtime --worker-type FOOD_DELIVERY
  python run_gig_pipeline.py --step realtime --worker-type RIDE_SHARE --count 20 --tps 2
  python run_gig_pipeline.py --step simulate --count 100 --worker-type QUICK_COMMERCE
  python run_gig_pipeline.py --step train --train-workers 800 --weeks-span 12
  python run_gig_pipeline.py --step simulate --count 50 --weeks-span 12
  python run_gig_pipeline.py --step report --report-rows 30
  python run_gig_pipeline.py --step truncate
        """,
    )

    parser.add_argument(
        "--step",
        choices=list(STEPS.keys()),
        default="all",
        help="Pipeline step to run (default: all). Use 'truncate' to clear DB tables.",
    )
    parser.add_argument(
        "--worker-type",
        dest="worker_type",
        choices=VALID_WORKER_TYPES,
        default="all",
        metavar="TYPE",
        help=(
            "Gig worker platform category.\n"
            "Options: " + "  ".join(VALID_WORKER_TYPES)
        ),
    )
    parser.add_argument(
        "--count",
        type=int,
        default=50,
        help="Number of workers to inject (simulate/realtime). Default: 50. "
             "Use 0 for infinite realtime.",
    )
    parser.add_argument(
        "--tps",
        type=float,
        default=1.0,
        help="Workers per second for realtime mode (default: 1.0)",
    )
    parser.add_argument(
        "--weeks",
        type=int,
        default=16,
        help="Weeks of income history to simulate per worker (default: 16)",
    )
    parser.add_argument(
        "--train-workers",
        dest="train_workers",
        type=int,
        default=500,
        help="Number of synthetic workers for classifier training (default: 500)",
    )
    parser.add_argument(
        "--report-rows",
        dest="report_rows",
        type=int,
        default=20,
        help="Max rows to show in report tables (default: 20)",
    )

    args = parser.parse_args()

    # --count 0 in realtime = infinite
    if args.step == "realtime" and args.count == 0:
        args.count = None

    STEPS[args.step](args)


if __name__ == "__main__":
    main()
