"""
SENTINEL V2 — Pipeline Orchestrator
Full end-to-end pipeline: seed → baselines → train → validate → score → monitor
Run individual steps or the full pipeline.
"""

import argparse
import sys
import time
from datetime import datetime, timezone


# ── Step functions ────────────────────────────────────────────────────────────

def run_seed(args):
    from database.seed import run_seed as _seed
    _seed(
        n_customers=getattr(args, "customers", None),
        truncate=getattr(args, "truncate", False),
    )


def run_baselines(args):
    from scripts.build_baselines import run_build_baselines
    run_build_baselines()


def run_train(args):
    from scripts.train_model import run_train as _train
    _train(max_customers=getattr(args, "customers", None))


def run_pretrain_lstm(args):
    """Pre-train the LSTM transaction sequence encoder."""
    print()
    print("=" * 55)
    print("  SENTINEL V2 — LSTM Pre-Training")
    print("=" * 55)
    from ml_models.training_pipeline import run_lstm_pretraining
    run_lstm_pretraining(max_customers=getattr(args, "customers", None))


def run_validate(args):
    """Quick validation: load model, run inference on a few samples, print metrics."""
    print()
    print("=" * 55)
    print("  SENTINEL V2 — Model Validation")
    print("=" * 55)

    from ml_models.lightgbm_model import SentinelLightGBM
    import numpy as np, json
    from pathlib import Path

    model = SentinelLightGBM()
    try:
        model.load()
    except FileNotFoundError:
        print("  ✗ No model found. Run --step train first.")
        return

    # Load feature weights
    weights_path = Path("config/feature_weights.json")
    if weights_path.exists():
        with open(weights_path) as f:
            fw = json.load(f)
        metrics = fw.get("metrics", {})
        print(f"  Model version:   {fw.get('version', '?')}")
        print(f"  Trained at:      {fw.get('trained_at', '?')[:19]}")
        print(f"  AUC:             {metrics.get('auc', '?')}")
        print(f"  Avg Precision:   {metrics.get('avg_precision', '?')}")
        print(f"  Best iteration:  {metrics.get('best_iteration', '?')}")
    else:
        print("  ⚠ config/feature_weights.json not found")

    # Sanity-check inference
    np.random.seed(99)
    x_stress = np.zeros(model.n_features, dtype=np.float32)
    
    # Robustly map features by name since indices can shift
    def set_feat(name, val):
        if hasattr(model, "feature_names") and name in model.feature_names:
            x_stress[model.feature_names.index(name)] = val
            
    set_feat("failed_nach_count_30d", 4.0)
    set_feat("raw_failed_nach_count_30d", 4.0)
    set_feat("lending_app_transfer_count_30d", 3.0)
    set_feat("raw_lending_app_transfer_count_30d", 3.0)
    set_feat("raw_lending_app_dependency_score", 0.8)  # 80% dependency
    set_feat("is_failed", 1.0)

    x_normal = np.zeros(model.n_features, dtype=np.float32)

    p_stress = model.predict_single(x_stress)
    p_normal = model.predict_single(x_normal)

    print()
    print(f"  Stress vector severity:  {round(p_stress, 4)}")
    print(f"  Normal vector severity:  {round(p_normal, 4)}")

    ok = p_stress > p_normal
    print(f"  Model ranking:           {'✓ PASS (stress > normal)' if ok else '✗ FAIL'}")

    # Top 10 features by importance
    imp = model.get_feature_importance()
    top10 = sorted(imp.items(), key=lambda x: -x[1])[:10]
    print()
    print("  Top 10 features by importance:")
    for fname, weight in top10:
        bar = "█" * int(weight * 200)
        print(f"    {fname:<40} {weight:.4f}  {bar}")

    print("=" * 55)


def run_score_batch(args):
    """Batch-score all customers using latest model and baselines."""
    print()
    print("=" * 55)
    print("  SENTINEL V2 — Batch Scoring")
    print("=" * 55)

    import uuid
    import numpy as np
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from datetime import datetime, timedelta, timezone
    from config.settings import get_settings
    from feature_engine.features import compute_all_features
    from feature_engine.delta_features import compute_delta_features, DELTA_FEATURE_NAMES
    from baseline.baseline_builder import get_baseline
    from enrichment.transaction_classifier import classify_transaction
    from ml_models.lightgbm_model import SentinelLightGBM
    from realtime.pulse_accumulator import assign_risk_tier

    s = get_settings()

    model = SentinelLightGBM()
    try:
        model.load()
    except FileNotFoundError:
        print("  ✗ No model found. Run --step train first.")
        return

    conn = psycopg2.connect(
        host=s.POSTGRES_HOST, port=s.POSTGRES_PORT,
        database=s.POSTGRES_DB, user=s.POSTGRES_USER, password=s.POSTGRES_PASSWORD,
    )
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("SELECT customer_id FROM customers ORDER BY customer_id")
    customers = [str(r["customer_id"]) for r in cursor.fetchall()]
    print(f"  Scoring {len(customers)} customers...")

    now       = datetime.now(timezone.utc)
    scored    = 0
    skipped   = 0
    tier_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

    for i, cid in enumerate(customers):
        baseline = get_baseline(cid, conn=conn)
        if baseline is None:
            skipped += 1
            continue

        try:
            current_feats = compute_all_features(cid, as_of=now, conn=conn)
        except Exception:
            skipped += 1
            continue

        # Build a representative "neutral" transaction for batch scoring
        txn_dict = {
            "platform": "UPI", "payment_status": "success",
            "sender_id": "batch@scoring", "receiver_id": "batch@scoring",
            "amount": 0.0, "balance_before": None, "balance_after": None,
            "txn_timestamp": now.isoformat(),
        }
        from enrichment.transaction_category import TransactionCategory
        cat = TransactionCategory(category="UNKNOWN", confidence=0.0,
                                  is_debit=True, is_stress_signal=False, stress_weight=0.0)

        delta = compute_delta_features(current_feats, baseline, txn_dict, cat)
        x = np.array([delta.get(f, 0.0) for f in DELTA_FEATURE_NAMES], dtype=np.float32)
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)

        severity  = float(model.predict_single(x))
        tier_info = assign_risk_tier(severity)

        cursor.execute("""
            INSERT INTO pulse_scores (score_id, customer_id, pulse_score,
                risk_tier, risk_label, score_ts, last_updated)
            VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        """, (str(uuid.uuid4()), cid, round(severity, 6),
              tier_info["tier"], tier_info["label"]))

        tier_dist[tier_info["tier"]] += 1
        scored += 1

        if (i + 1) % 200 == 0:
            conn.commit()
            print(f"    Scored {i+1}/{len(customers)}...")

    conn.commit()
    conn.close()

    print()
    print(f"  Scored:  {scored:,}")
    print(f"  Skipped: {skipped:,}")
    print()
    print("  Risk tier distribution:")
    tier_labels = {1:"CRITICAL", 2:"HIGH", 3:"MODERATE", 4:"WATCH", 5:"STABLE"}
    for tier, cnt in tier_dist.items():
        pct = cnt / max(scored, 1) * 100
        bar = "█" * int(pct / 2)
        print(f"    Tier {tier} {tier_labels[tier]:<10}  {cnt:>5}  ({pct:>5.1f}%)  {bar}")
    print("=" * 55)


def run_monitor(args):
    """Run PSI + AIR monitoring and print summary."""
    print()
    print("=" * 55)
    print("  SENTINEL V2 — Monitoring")
    print("=" * 55)

    from monitoring.psi_air_monitor import run_all_monitoring

    summary = run_all_monitoring()

    print()
    print(f"  Features monitored:  {summary['total_features']}")
    print(f"  Stable:              {summary['stable_features']}")
    print(f"  Watch:               {summary['watch_features']}")
    print(f"  Retrain:             {summary['retrain_features']}")
    print(f"  Retrain needed:      {'⚠ YES' if summary['retrain_needed'] else '✓ No'}")
    print(f"  AIR alerts:          {summary['air_alerts']}")

    if summary["top_drifted"]:
        print()
        print("  Most drifted features:")
        for r in summary["top_drifted"]:
            print(f"    {r['feature_name']:<40}  PSI={r['metric_value']:.4f}  {r['status']}")

    if summary["air_results"]:
        print()
        print("  AIR fairness results:")
        for r in summary["air_results"]:
            icon = "✓" if r["status"] == "PASS" else "⚠"
            print(f"    {icon} {r['feature_name']:<30}  AIR={r['metric_value']:.4f}  {r['status']}")

    print()
    score_psi = summary.get("score_psi", {})
    sev_psi   = summary.get("severity_psi", {})
    print(f"  Score distribution PSI:    {score_psi.get('metric_value', 0):.4f}  {score_psi.get('status', '?')}")
    print(f"  Severity distribution PSI: {sev_psi.get('metric_value', 0):.4f}   {sev_psi.get('status', '?')}")
    print("=" * 55)


def start_api(args):
    """Start the FastAPI scoring service."""
    import uvicorn
    from config.settings import get_settings
    s = get_settings()
    print(f"Starting Sentinel V2 Scoring API on port {s.SCORING_SERVICE_PORT}...")
    print(f"Swagger UI: http://localhost:{s.SCORING_SERVICE_PORT}/docs")
    uvicorn.run(
        "scoring_service.app:app",
        host="0.0.0.0",
        port=s.SCORING_SERVICE_PORT,
        reload=False,
    )


def start_consumer(args):
    """Start the Kafka consumer."""
    from realtime.kafka_consumer import SentinelConsumer
    dry_run = getattr(args, "dry_run", False)
    print(f"Starting Sentinel V2 Kafka Consumer (dry_run={dry_run})...")
    SentinelConsumer(dry_run=dry_run).run()


def run_all(args):
    """Run the complete offline pipeline end-to-end."""
    start = time.time()
    print()
    print("=" * 55)
    print("  SENTINEL V2 — Full Pipeline")
    print(f"  Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 55)

    run_seed(args)
    run_baselines(args)
    run_pretrain_lstm(args)
    run_train(args)
    run_validate(args)
    run_score_batch(args)
    run_monitor(args)

    elapsed = time.time() - start
    print()
    print("=" * 55)
    print(f"  PIPELINE COMPLETE  ({elapsed:.1f}s)")
    print("=" * 55)


# ── Step registry ─────────────────────────────────────────────────────────────

STEPS = {
    "seed":           run_seed,
    "baselines":      run_baselines,
    "pretrain-lstm":  run_pretrain_lstm,
    "train":          run_train,
    "validate":       run_validate,
    "score":          run_score_batch,
    "monitor":        run_monitor,
    "start-api":      start_api,
    "start-consumer": start_consumer,
    "all":            run_all,
}


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="SENTINEL V2 Pipeline Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Steps:
  seed            Generate customers + 120-day raw transactions
  baselines       Build per-customer statistical baselines (days 1-90)
  pretrain-lstm   Pre-train LSTM transaction sequence encoder
  train           Train LightGBM PulseScorer
  validate        Load model and verify inference + feature importance
  score           Batch-score all customers
  monitor         PSI drift + AIR fairness monitoring
  start-api       Start FastAPI scoring service
  start-consumer  Start Kafka consumer
  all             Run seed → baselines → pretrain-lstm → train → validate → score → monitor
        """,
    )
    parser.add_argument(
        "--step",
        choices=list(STEPS.keys()),
        default="all",
        help="Pipeline step to run",
    )
    parser.add_argument(
        "--customers", type=int, default=None,
        help="Override NUM_CUSTOMERS (useful for quick tests)",
    )
    parser.add_argument(
        "--truncate", action="store_true",
        help="Truncate all tables before seeding (use with --step seed)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Consumer: score but do not write to DB",
    )
    args = parser.parse_args()
    STEPS[args.step](args)


if __name__ == "__main__":
    main()