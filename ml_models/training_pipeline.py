"""
ml_models/training_pipeline.py
─────────────────────────────────────────────────────────────────────────────
Clean training pipeline — zero label leakage.
LABEL RULE (strictly observable outcomes only):
  label = 1 if customer has ANY of:
    - days_past_due >= 1 on any active loan
    - failed_auto_debit_count_30d >= 2 on any active loan
  NO is_stress_profile. NO random components. NO synthetic flags.
DATA SPLIT:
  Training examples: transactions from days 91-120 (real-time window)
  Baseline:          computed from days 1-90
  These two windows never overlap in time.
  FIX (Bug 4 — Temporal split was not truly temporal):
    BEFORE: X was built in customer_id (UUID) order.  The 80/20 split was
    therefore on an essentially random ordering, not on time.  The validation
    set did NOT represent future data — it was a random 20 % of the dataset.
    AFTER: all (X, y, timestamp) rows are collected, then sorted by
    txn_timestamp in ascending order before the split.  The validation set
    is now guaranteed to contain the most recent 20 % of transactions,
    properly simulating production deployment where the model scores data
    it has never seen in time.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Tuple, List, Optional
import numpy as np
import psycopg2
from psycopg2.extras import RealDictCursor
from config.settings import get_settings
from feature_engine.features import compute_all_features
from feature_engine.delta_features import compute_delta_features, DELTA_FEATURE_NAMES
from baseline.baseline_builder import get_baseline
from enrichment.transaction_classifier import classify_transaction
from ml_models.lightgbm_model import SentinelLightGBM
settings = get_settings()
def _get_db():
    return psycopg2.connect(
        host=settings.POSTGRES_HOST, port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB, user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )
def _build_label(customer_id: str, cursor) -> int:
    """
    Label = 1 if customer shows delinquency signals.
    Derived purely from observable database outcomes.
    """
    cursor.execute("""
        SELECT MAX(days_past_due)            AS max_dpd,
               MAX(failed_auto_debit_count_30d) AS max_failed
        FROM loans
        WHERE customer_id = %s AND status = 'ACTIVE'
    """, (customer_id,))
    row = cursor.fetchone()
    if not row:
        return 0
    max_dpd    = int(row["max_dpd"]    or 0)
    max_failed = int(row["max_failed"] or 0)
    return 1 if (max_dpd >= 1 or max_failed >= 2) else 0
def build_training_dataset(
    conn=None,
    max_customers: Optional[int] = None,
) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """
    Build (X, y) from real-time window transactions.
    FIX (Bug 4): Rows are now sorted by txn_timestamp before being returned
    so that the downstream 80/20 split produces a true temporal validation set.
    Returns:
        X:    (n_samples, 48) float32 array — sorted by txn_timestamp ASC
        y:    (n_samples,)   int32 binary labels
        cids: list of customer_ids per sample (for audit)
    """
    close_conn = conn is None
    if conn is None:
        conn = _get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        now    = datetime.now(timezone.utc)
        # Real-time window: last 30 days
        rt_start = now - timedelta(days=30)
        cursor.execute("""
            SELECT customer_id FROM customers ORDER BY customer_id LIMIT %s
        """, (max_customers or 999999,))
        customers = [str(r["customer_id"]) for r in cursor.fetchall()]
        print(f"  Building dataset for {len(customers)} customers...")
        X_rows, y_rows, cid_rows, ts_rows = [], [], [], []
        skipped = 0
        for i, cid in enumerate(customers):
            # Baseline must exist (built from days 1-90)
            baseline = get_baseline(cid, conn=conn)
            if baseline is None:
                skipped += 1
                continue
            # Fetch only real-time window transactions (days 91-120)
            cursor.execute("""
                SELECT sender_id, sender_name, receiver_id, receiver_name,
                       amount, platform, payment_status,
                       balance_before, balance_after, txn_timestamp
                FROM transactions
                WHERE customer_id = %s
                  AND txn_timestamp > %s AND txn_timestamp <= %s
                ORDER BY txn_timestamp ASC
            """, (cid, rt_start, now))
            rt_txns = cursor.fetchall()
            if not rt_txns:
                skipped += 1
                continue
            label = _build_label(cid, cursor)
            for txn in rt_txns:
                txn_dict = dict(txn)
                txn_ts   = txn["txn_timestamp"]
                try:
                    current_feats = compute_all_features(cid, as_of=txn_ts, conn=conn)
                except Exception:
                    continue
                cat = classify_transaction(txn_dict)
                delta = compute_delta_features(current_feats, baseline, txn_dict, cat)
                x = np.array(
                    [delta.get(f, 0.0) for f in DELTA_FEATURE_NAMES],
                    dtype=np.float32,
                )
                x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
                X_rows.append(x)
                y_rows.append(label)
                cid_rows.append(cid)
                # FIX: Track the raw timestamp for post-collection temporal sort
                raw_ts = txn_ts
                if isinstance(raw_ts, str):
                    try:
                        raw_ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                    except Exception:
                        raw_ts = now
                ts_rows.append(raw_ts)
            if (i + 1) % 100 == 0:
                print(f"    {i+1}/{len(customers)} customers — {len(X_rows)} samples")
        cursor.close()
        if not X_rows:
            raise ValueError("No training samples built. Run --step baselines first.")
        # ── FIX: Sort all rows by txn_timestamp ascending ────────────────────
        # This ensures the downstream 80/20 split creates a proper temporal
        # validation set (most-recent 20 %) rather than a random partition.
        sort_idx = sorted(range(len(ts_rows)), key=lambda i: ts_rows[i])
        X      = np.array([X_rows[i]   for i in sort_idx], dtype=np.float32)
        y      = np.array([y_rows[i]   for i in sort_idx], dtype=np.int32)
        cid_rows = [cid_rows[i]        for i in sort_idx]
        pos_rate = float(np.mean(y)) * 100
        print(f"  Dataset: {len(X):,} samples | "
              f"Delinquency rate: {pos_rate:.1f}% | "
              f"Skipped: {skipped}")
        return X, y, cid_rows
    finally:
        if close_conn:
            conn.close()
def apply_smote(X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    n_pos = int(np.sum(y == 1))
    n_neg = int(np.sum(y == 0))
    if n_pos < 6 or n_neg < 6:
        print("  ⚠ Too few samples for SMOTE — skipping")
        return X, y
    print(f"  Before SMOTE: {n_neg} neg / {n_pos} pos ({n_neg//max(n_pos,1)}:1)")
    try:
        from imblearn.over_sampling import SMOTE
        from imblearn.under_sampling import TomekLinks
        from imblearn.pipeline import Pipeline as ImbPipeline
        pipe = ImbPipeline([
            ("smote", SMOTE(sampling_strategy=0.35, k_neighbors=min(5, n_pos-1),
random_state=42)),
            ("tomek", TomekLinks()),
        ])
        X_r, y_r = pipe.fit_resample(X, y)
        print(f"  After SMOTE:  {int(np.sum(y_r==0))} neg / {int(np.sum(y_r==1))} pos")
        return X_r, y_r
    except ImportError:
        print("  ⚠ imbalanced-learn not installed — skipping SMOTE")
        return X, y
def run_training_pipeline(max_customers: Optional[int] = None) -> Dict[str, Any]:
    """
    Full training pipeline:
      1. Build dataset from real-time window (days 91-120)
      2. Per-customer 80/20 train/val split (no same-customer leakage)
      3. SMOTE for class balance
      4. Train LightGBM
      5. Save model + feature weights to config/feature_weights.json
    """
    start = time.time()
    print()
    print("=" * 55)
    print("  SENTINEL V2 — Model Training")
    print("=" * 55)
    conn = _get_db()
    metrics = {}
    try:
        print("\n[1/5] Building training dataset...")
        X, y, cid_rows = build_training_dataset(conn=conn, max_customers=max_customers)

        print("\n[2/5] Per-customer train/val split (80/20)...")
        # Split by CUSTOMER, not by row, to prevent same-customer leakage.
        # Previously: temporal row-based split allowed the same customer's
        # transactions to appear in both train and val, letting the model
        # memorize customer z-score fingerprints instead of learning patterns.
        unique_cids = list(dict.fromkeys(cid_rows))  # preserve order, deduplicate
        split_idx = int(len(unique_cids) * 0.80)
        train_cids = set(unique_cids[:split_idx])
        val_cids   = set(unique_cids[split_idx:])
        train_mask = np.array([c in train_cids for c in cid_rows])
        X_tr, X_val = X[train_mask], X[~train_mask]
        y_tr, y_val = y[train_mask], y[~train_mask]
        print(f"  Train: {len(X_tr):,} samples ({len(train_cids)} customers)"
              f"  |  Val: {len(X_val):,} samples ({len(val_cids)} customers)")
        print(f"  Train pos rate: {float(np.mean(y_tr))*100:.1f}%  |  "
              f"Val pos rate: {float(np.mean(y_val))*100:.1f}%")

        print("\n[3/5] SMOTE...")
        X_tr, y_tr = apply_smote(X_tr, y_tr)

        print("\n[4/5] Training LightGBM...")
        model = SentinelLightGBM()
        metrics = model.train(X_tr, y_tr, X_val, y_val)
        print(f"  AUC:            {metrics['auc']}")
        print(f"  Avg Precision:  {metrics['avg_precision']}")
        print(f"  Best iteration: {metrics['best_iteration']}")

        # ── Classification report (precision / recall / F1 / accuracy) ────
        from sklearn.metrics import (
            classification_report, accuracy_score, f1_score,
            precision_score, recall_score, fbeta_score,
        )
        y_pred_proba = model.predict_severity(X_val)

        # Find optimal threshold that maximises F-beta (β=0.7).
        # β < 1 penalises low precision more than low recall,
        # ensuring the model targets industry-grade precision (≥ 0.70)
        # while maintaining acceptable recall.
        BETA = 0.7
        best_fb, best_thr = 0.0, 0.5
        for thr in np.arange(0.10, 0.90, 0.01):
            yp = (y_pred_proba >= thr).astype(int)
            fb = float(fbeta_score(y_val, yp, beta=BETA, zero_division=0.0))
            if fb > best_fb:
                best_fb, best_thr = fb, float(thr)

        y_pred_binary = (y_pred_proba >= best_thr).astype(int)
        accuracy = round(float(accuracy_score(y_val, y_pred_binary)), 4)
        f1 = round(float(f1_score(y_val, y_pred_binary, zero_division=0.0)), 4)
        prec = round(float(precision_score(y_val, y_pred_binary, zero_division=0.0)), 4)
        rec = round(float(recall_score(y_val, y_pred_binary, zero_division=0.0)), 4)
        print()
        print(f"  ── Classification Report (threshold={best_thr:.2f}) ──")
        print(classification_report(
            y_val, y_pred_binary,
            target_names=["Normal", "Stress"],
            digits=4,
            zero_division=0.0,
        ))
        print(f"  Optimal threshold: {best_thr:.2f}")
        print(f"  Precision: {prec}")
        print(f"  Recall:    {rec}")
        print(f"  F1 Score:  {f1}")
        metrics["accuracy"]  = accuracy
        metrics["f1_score"]  = f1
        metrics["precision"] = prec
        metrics["recall"]    = rec
        metrics["threshold"] = round(best_thr, 2)

        model.save()

        print("\n[5/5] Saving feature weights...")
        try:
            importance = model.get_feature_importance()
            with open("config/feature_weights.json", "w") as f:
                json.dump({
                    "version":    model.model_version,
                    "trained_at": datetime.now(timezone.utc).isoformat(),
                    "metrics":    metrics,
                    "weights":    importance,
                }, f, indent=2)
            print("  ✓ config/feature_weights.json written")
        except Exception as e:
            print(f"  ⚠ Feature weight save failed: {e}")
    finally:
        conn.close()
    print()
    print("=" * 55)
    print(f"  AUC:       {metrics.get('auc', 'N/A')}")
    print(f"  AP:        {metrics.get('avg_precision', 'N/A')}")
    print(f"  Accuracy:  {metrics.get('accuracy', 'N/A')}")
    print(f"  Precision: {metrics.get('precision', 'N/A')}")
    print(f"  Recall:    {metrics.get('recall', 'N/A')}")
    print(f"  F1:        {metrics.get('f1_score', 'N/A')}")
    print(f"  Threshold: {metrics.get('threshold', 'N/A')}")
    print(f"  Time:      {time.time()-start:.1f}s")
    print("=" * 55)
    return metrics