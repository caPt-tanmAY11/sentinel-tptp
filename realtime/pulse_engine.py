"""
realtime/pulse_engine.py
─────────────────────────────────────────────────────────────────────────────
Orchestrates the complete real-time scoring pipeline for one transaction.
Target latency: < 100ms end-to-end.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import psycopg2
from psycopg2.extras import RealDictCursor

from config.settings import get_settings
from schemas.transaction_event import TransactionEvent
from enrichment.transaction_classifier import classify_transaction
from feature_engine.features import compute_all_features
from feature_engine.delta_features import compute_delta_features, DELTA_FEATURE_NAMES
from baseline.baseline_builder import get_baseline
from realtime.pulse_accumulator import (
    compute_direction, compute_delta, apply_delta, assign_risk_tier,
    apply_cibil_modifier,
)

settings = get_settings()


def _get_db():
    return psycopg2.connect(
        host=settings.POSTGRES_HOST, port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB, user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )


class PulseEngine:
    """
    Real-time transaction scoring engine.
    One instance per process. Lazy-loads model on first call.
    """

    def __init__(self, redis_client=None):
        self.redis_client  = redis_client
        self._model        = None
        self._model_loaded = False
        self._lstm_encoder = None
        self._lstm_loaded  = False

    def _get_lstm_encoder(self):
        if not self._lstm_loaded:
            from ml_models.lstm_encoder import load_encoder
            self._lstm_encoder = load_encoder()
            self._lstm_loaded = True
            if self._lstm_encoder:
                print("  ✓ LSTM encoder loaded for real-time scoring")
        return self._lstm_encoder
        self._lstm_encoder = None
        self._lstm_loaded  = False

    def _get_model(self):
        if not self._model_loaded:
            from ml_models.lightgbm_model import SentinelLightGBM
            self._model = SentinelLightGBM()
            try:
                self._model.load()
            except FileNotFoundError:
                print("  ⚠ Model not found — using classifier stress_weight as fallback")
                self._model = None
            self._model_loaded = True
        return self._model

    def _get_lstm_encoder(self):
        if not self._lstm_loaded:
            from ml_models.lstm_encoder import load_encoder
            self._lstm_encoder = load_encoder()
            self._lstm_loaded = True
            if self._lstm_encoder:
                print("  ✓ LSTM encoder loaded for real-time scoring")
        return self._lstm_encoder

    def process(self, event: TransactionEvent, conn=None) -> Dict[str, Any]:
        """
        Full pipeline for one transaction event.
        Returns score result dict matching transaction_pulse_events columns.
        """
        t_start    = time.time()
        close_conn = conn is None
        if conn is None:
            conn = _get_db()

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cid    = event.customer_id

            # Step 1: Fetch baseline
            baseline = get_baseline(cid, redis_client=self.redis_client, conn=conn)
            if baseline is None:
                return self._neutral_result(event, "no_baseline", t_start)

            # Step 1b: Fetch CIBIL score for this customer
            try:
                cursor.execute(
                    "SELECT credit_bureau_score FROM customers WHERE customer_id = %s",
                    (cid,)
                )
                row = cursor.fetchone()
                cibil_score = int(row["credit_bureau_score"]) if row and row["credit_bureau_score"] else None
            except Exception:
                cibil_score = None

            # Step 2: Classify transaction
            txn_dict = {
                "sender_id": event.sender_id, "sender_name": event.sender_name,
                "receiver_id": event.receiver_id, "receiver_name": event.receiver_name,
                "amount": event.amount, "platform": event.platform,
                "payment_status": event.payment_status,
                "balance_before": event.balance_before, "balance_after": event.balance_after,
                "txn_timestamp": event.txn_timestamp.isoformat(),
            }
            category = classify_transaction(txn_dict, event.account_number)

            # Step 3: Current features as_of transaction timestamp
            try:
                current_features = compute_all_features(cid, as_of=event.txn_timestamp, conn=conn)
            except Exception as e:
                return self._neutral_result(event, f"feature_error:{e}", t_start)

            # Step 4: Delta vector with LSTM embedding
            from ml_models.lstm_encoder import extract_embedding

            # Fetch last 20 transactions for LSTM sequence
            lstm_encoder = self._get_lstm_encoder()
            if lstm_encoder is not None:
                cursor2 = conn.cursor(cursor_factory=RealDictCursor)
                cursor2.execute("""
                    SELECT sender_id, sender_name, receiver_id, receiver_name,
                           amount, platform, payment_status,
                           balance_before, balance_after, txn_timestamp
                    FROM transactions
                    WHERE customer_id = %s AND txn_timestamp < %s
                    ORDER BY txn_timestamp DESC LIMIT 20
                """, (cid, event.txn_timestamp))
                recent_txns = list(reversed([dict(r) for r in cursor2.fetchall()]))
                cursor2.close()
                lstm_emb = extract_embedding(lstm_encoder, recent_txns)
            else:
                lstm_emb = None

            # Fetch EMI dates for this customer
            cursor.execute("SELECT emi_due_date FROM loans WHERE customer_id = %s AND status = 'ACTIVE'", (cid,))
            emi_dates = [r["emi_due_date"] for r in cursor.fetchall() if r["emi_due_date"] is not None]

            delta_feats = compute_delta_features(
                current_features=current_features,
                baseline=baseline,
                transaction=txn_dict,
                category=category,
                lstm_embedding=lstm_emb,
                customer_emi_dates=emi_dates,
            )

            # Step 5: Model inference → severity
            import numpy as np
            x     = np.array([delta_feats.get(f, 0.0) for f in DELTA_FEATURE_NAMES], dtype=np.float32)
            model = self._get_model()
            if model and model.is_loaded:
                raw_prob = float(model.predict_single(x))
                # BLEND: 40% ML Customer Profile Risk + 60% Semantic Transaction Risk
                # Ensures a Grocery txn (0.0 weight) visibly drops severity vs Lending App (0.85 weight)
                severity = (raw_prob * 0.5) + (category.stress_weight * 0.5)
            else:
                severity = float(category.stress_weight)  # fallback

            # Step 5b: Apply CIBIL modifier to severity before direction/delta
            direction_pre = compute_direction(category.category, severity)
            severity, direction_pre = apply_cibil_modifier(severity, direction_pre, cibil_score)

            # Step 6: Direction + bounded delta
            direction    = direction_pre
            pulse_before = self._get_current_pulse_score(cid, cursor)
            delta        = compute_delta(severity, direction, pulse_before)
            pulse_after  = apply_delta(pulse_before, delta)
            tier_info    = assign_risk_tier(pulse_after, cibil_score)

            # Step 7: Update overall pulse score
            self._upsert_pulse_score(cid, pulse_after, tier_info, cursor, conn)

            # Refresh Redis
            if self.redis_client:
                self._cache_pulse_score(cid, pulse_after, tier_info)

            # Step 8: SHAP top features (best-effort)
            top_features = self._get_top_shap(model, x) if (model and model.is_loaded) else []

            # Step 9: Write transaction_pulse_event
            event_id   = str(uuid.uuid4())
            latency_ms = int((time.time() - t_start) * 1000)

            cursor.execute("""\
                INSERT INTO transaction_pulse_events (
                    event_id, customer_id, transaction_id, event_ts,
                    amount, platform, receiver_id, payment_status,
                    inferred_category, classifier_confidence, delta_features,
                    txn_severity, severity_direction, delta_applied,
                    pulse_score_before, pulse_score_after,
                    top_features, model_version, scoring_latency_ms
                ) VALUES (%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s, %s,%s,%s, %s,%s, %s,%s,%s)
            """, (
                event_id, cid, event.event_id, datetime.now(timezone.utc),
                event.amount, event.platform, event.receiver_id, event.payment_status,
                category.category, round(category.confidence, 4),
                json.dumps({k: round(v, 4) for k, v in delta_feats.items()}),
                round(severity, 6), direction, round(delta, 6),
                round(pulse_before, 6), round(pulse_after, 6),
                json.dumps(top_features),
                model.model_version if (model and model.is_loaded) else "fallback",
                latency_ms,
            ))

            # ── Also write to raw transactions table so customer profile
            #    Transaction History section shows real-time events ──────
            try:
                cursor.execute("""\
                    INSERT INTO transactions (
                        transaction_id, customer_id, account_number,
                        sender_id, sender_name,
                        receiver_id, receiver_name,
                        amount, platform, payment_status,
                        reference_number,
                        balance_before, balance_after,
                        txn_timestamp
                    ) VALUES (%s,%s,%s, %s,%s, %s,%s, %s,%s,%s, %s, %s,%s, %s)
                    ON CONFLICT DO NOTHING
                """, (
                    event.event_id, cid, event.account_number,
                    event.sender_id,   event.sender_name,
                    event.receiver_id, event.receiver_name,
                    event.amount, event.platform, event.payment_status,
                    None,  # reference_number — not in TransactionEvent, nullable
                    event.balance_before, event.balance_after,
                    event.txn_timestamp,
                ))
            except Exception as txn_err:
                # Non-blocking — pulse scoring continues even if raw insert fails
                print(f"  ⚠ Raw transaction insert failed (non-fatal): {txn_err}")

            conn.commit()
            cursor.close()

            return {
                "event_id":              event_id,
                "customer_id":           cid,
                "scored_at":             datetime.now(timezone.utc).isoformat(),
                "amount":                event.amount,
                "platform":              event.platform,
                "inferred_category":     category.category,
                "classifier_confidence": round(category.confidence, 4),
                "txn_severity":          round(severity, 6),
                "severity_direction":    direction,
                "delta_applied":         round(delta, 6),
                "pulse_score_before":    round(pulse_before, 6),
                "pulse_score_after":     round(pulse_after, 6),
                "risk_tier":             tier_info["tier"],
                "risk_label":            tier_info["label"],
                "cibil_score":           cibil_score,
                "top_features":          top_features,
                "model_version":         model.model_version if (model and model.is_loaded) else "fallback",
                "scoring_latency_ms":    latency_ms,
            }

        except Exception:
            try: conn.rollback()
            except Exception: pass
            raise
        finally:
            if close_conn:
                conn.close()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_current_pulse_score(self, customer_id: str, cursor) -> float:
        if self.redis_client:
            try:
                cached = self.redis_client.get(f"pulse:{customer_id}")
                if cached:
                    return float(json.loads(cached).get("score", 0.0))
            except Exception:
                pass
        cursor.execute("""
            SELECT pulse_score FROM pulse_scores
            WHERE customer_id = %s ORDER BY score_ts DESC LIMIT 1
        """, (customer_id,))
        row = cursor.fetchone()
        return float(row["pulse_score"]) if row else 0.0

    def _upsert_pulse_score(self, customer_id, pulse_score, tier_info, cursor, conn):
        cursor.execute("""
            INSERT INTO pulse_scores (score_id, customer_id, pulse_score,
                risk_tier, risk_label, score_ts, last_updated)
            VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        """, (str(uuid.uuid4()), customer_id, round(pulse_score, 6),
              tier_info["tier"], tier_info["label"]))

    def _cache_pulse_score(self, customer_id, pulse_score, tier_info):
        try:
            self.redis_client.setex(
                f"pulse:{customer_id}", 86400,
                json.dumps({"score": round(pulse_score, 6),
                            "tier": tier_info["tier"],
                            "label": tier_info["label"],
                            "ts": datetime.now(timezone.utc).isoformat()}),
            )
        except Exception:
            pass

    def _get_top_shap(self, model, x) -> list:
        try:
            import numpy as np
            shap_vals = model.get_shap_values(x.reshape(1, -1))
            arr = shap_vals[0] if hasattr(shap_vals, '__len__') else shap_vals
            idx = sorted(range(len(arr)), key=lambda i: abs(float(arr[i])), reverse=True)[:5]
            return [{"feature": DELTA_FEATURE_NAMES[i],
                     "shap": round(float(arr[i]), 4),
                     "direction": "stress" if float(arr[i]) > 0 else "relief"}
                    for i in idx]
        except Exception:
            return []

    def _neutral_result(self, event, reason, t_start):
        return {
            "event_id": event.event_id, "customer_id": event.customer_id,
            "scored_at": datetime.now(timezone.utc).isoformat(),
            "amount": event.amount, "platform": event.platform,
            "inferred_category": "UNKNOWN", "classifier_confidence": 0.0,
            "txn_severity": 0.0, "severity_direction": "neutral",
            "delta_applied": 0.0, "pulse_score_before": 0.0, "pulse_score_after": 0.0,
            "risk_tier": 5, "risk_label": "STABLE", "top_features": [],
            "model_version": "fallback",
            "scoring_latency_ms": int((time.time() - t_start) * 1000),
            "skip_reason": reason,
        }