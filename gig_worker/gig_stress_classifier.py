"""
gig_worker/gig_stress_classifier.py
─────────────────────────────────────────────────────────────────────────────
LightGBM binary classifier for gig worker financial stress detection.

Stress definition (hard observable rule):
    A specific week transition is STRESSED when the income drops by more than
    50% compared to the immediately preceding week.

    Formula applied per (prev, curr) pair:
        drop = (prev_week_income - curr_week_income) / prev_week_income
        if drop > 0.50 → STRESSED transition

Model design
─────────────
Input  : A single (prev_week_income, curr_week_income) pair — raw ₹ amounts.
         The model receives both raw values and learns the drop threshold.
         No pre-computed WoW ratios are passed; the model discovers the
         relationship between prev and curr from the training distribution.

Output : Binary label  0 = NOT_STRESSED,  1 = STRESSED (transition)
         + probability score  [0.0, 1.0]

Feature set (2 features only):
  prev_week_income   Raw ₹ income of week N-1
  curr_week_income   Raw ₹ income of week N

Training data:
  All consecutive (prev, curr) income pairs extracted from simulated workers.
  For 500 workers × 15 pairs = 7,500 training pairs.
  ~35% of workers are stressed, each with ~1 stress transition ≈ 2.3% positive rate.
  LightGBM scale_pos_weight handles the imbalance.

Usage:
    python -m gig_worker.gig_stress_classifier

    Or import:
        from gig_worker.gig_stress_classifier import GigStressClassifier
        clf = GigStressClassifier()
        clf.train()
        result = clf.predict_pair(prev_income=7200.0, curr_income=3100.0)
─────────────────────────────────────────────────────────────────────────────
"""
import os
import pickle
from typing import List, Dict, Any, Optional

import numpy as np

try:
    import lightgbm as lgb
    _HAS_LGB = True
except ImportError:
    _HAS_LGB = False

try:
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.metrics import (
        classification_report,
        roc_auc_score,
        confusion_matrix,
    )
    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False

from gig_worker.gig_worker_simulator import (
    simulate_gig_workers,
    pairs_to_feature_records,
    GigWorkerProfile,
)

# ── Paths ─────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
SAVED_MODELS_DIR = os.path.join(_HERE, "saved_models")
MODEL_PATH = os.path.join(SAVED_MODELS_DIR, "gig_stress_lgbm.pkl")

# ── Feature columns (2 raw income values — no pre-computed ratios) ─────────
FEATURE_COLS = ["prev_week_income", "curr_week_income"]
LABEL_COL    = "is_stress_transition"


# ── Classifier ────────────────────────────────────────────────────────────────

class GigStressClassifier:
    """
    Trains and serves a gig worker stress transition classifier.

    Each inference call takes ONE (prev_week_income, curr_week_income) pair.
    The model learns the boundary:
        drop = (prev - curr) / prev > 0.50  →  STRESSED

    For whole-profile inference, predict_profile() iterates all consecutive
    pairs and reports per-week stress flags plus a worker-level summary.
    """

    def __init__(self) -> None:
        self.model   = None
        self.feature_cols = FEATURE_COLS

    # ── Training ──────────────────────────────────────────────────────────────

    def train(
        self,
        n_workers: int = 500,
        seed: int = 42,
        save: bool = True,
    ) -> Dict[str, Any]:
        """
        Simulate gig worker data, extract (prev, curr) pairs, train, save.

        Training data = all consecutive income pairs from all simulated workers.
        Label: is_stress_transition = 1  if  (prev-curr)/prev > 0.50

        Args:
            n_workers : Number of synthetic worker profiles to simulate.
            seed      : Master RNG seed.
            save      : Persist model to MODEL_PATH.

        Returns:
            Dict with accuracy, AUC, classification_report, confusion_matrix.
        """
        if not _HAS_SKLEARN:
            raise RuntimeError(
                "scikit-learn is required for training. "
                "Install with: pip install scikit-learn"
            )

        print(f"[GigStressClassifier] Simulating {n_workers} workers to extract income pairs…")
        profiles = simulate_gig_workers(n=n_workers, seed=seed)

        # Extract all (prev, curr) pairs from all workers
        all_pairs: List[Dict[str, Any]] = []
        for p in profiles:
            all_pairs.extend(pairs_to_feature_records(p.weekly_payouts))

        X = np.array(
            [[r["prev_week_income"], r["curr_week_income"]] for r in all_pairs],
            dtype=float,
        )
        y = np.array([r["is_stress_transition"] for r in all_pairs], dtype=int)

        total_pairs   = len(y)
        stress_pairs  = int(y.sum())
        pos_rate      = stress_pairs / total_pairs if total_pairs > 0 else 0.0

        print(f"[GigStressClassifier] Training pairs : {total_pairs:,}")
        print(f"[GigStressClassifier] Stress pairs   : {stress_pairs:,}  ({pos_rate*100:.1f}%)")
        print(f"[GigStressClassifier] Features       : {FEATURE_COLS}")

        # Temporal split: last 20% of pairs as test set
        split_idx = int(len(X) * 0.80)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]

        if _HAS_LGB:
            scale_pos = max(1.0, (1 - pos_rate) / pos_rate) if pos_rate > 0 else 1.0
            params = {
                "objective":         "binary",
                "metric":            ["binary_logloss", "auc"],
                "boosting_type":     "gbdt",
                "learning_rate":     0.05,
                "num_leaves":        15,
                "max_depth":         4,
                "min_child_samples": 5,
                "feature_fraction":  1.0,
                "bagging_fraction":  0.80,
                "bagging_freq":      5,
                "reg_alpha":         0.1,
                "reg_lambda":        0.1,
                "scale_pos_weight":  scale_pos,
                "verbose":           -1,
                "seed":              seed,
            }
            dtrain = lgb.Dataset(X_train, label=y_train,
                                 feature_name=FEATURE_COLS)
            dval   = lgb.Dataset(X_test, label=y_test,
                                 feature_name=FEATURE_COLS, reference=dtrain)
            callbacks = [lgb.early_stopping(50, verbose=False),
                         lgb.log_evaluation(period=-1)]
            booster = lgb.train(
                params, dtrain,
                num_boost_round=500,
                valid_sets=[dval],
                callbacks=callbacks,
            )
            self.model = booster
            y_prob = booster.predict(X_test)
        else:
            print("[GigStressClassifier] LightGBM not found — using GradientBoostingClassifier")
            clf = GradientBoostingClassifier(
                n_estimators=200, learning_rate=0.05,
                max_depth=3, random_state=seed,
            )
            clf.fit(X_train, y_train)
            self.model = clf
            y_prob = clf.predict_proba(X_test)[:, 1]

        y_pred   = (y_prob >= 0.50).astype(int)
        accuracy = float((y_pred == y_test).mean())
        try:
            auc = float(roc_auc_score(y_test, y_prob))
        except Exception:
            auc = float("nan")

        report = classification_report(
            y_test, y_pred,
            target_names=["NOT_STRESSED", "STRESSED"],
            output_dict=False,
        )
        cm = confusion_matrix(y_test, y_pred).tolist()

        print(f"\n[GigStressClassifier] ── Evaluation ────────────────────────────")
        print(f"  Accuracy : {accuracy*100:.2f}%")
        print(f"  ROC-AUC  : {auc:.4f}")
        print(f"\n{report}")
        print(f"  Confusion matrix (rows=actual, cols=predicted):")
        print(f"    NOT_STRESSED predicted → {cm[0]}")
        print(f"    STRESSED     predicted → {cm[1]}")

        if save:
            os.makedirs(SAVED_MODELS_DIR, exist_ok=True)
            with open(MODEL_PATH, "wb") as f:
                pickle.dump({
                    "model":   self.model,
                    "backend": "lgb" if _HAS_LGB else "sklearn",
                }, f)
            print(f"\n[GigStressClassifier] Model saved → {MODEL_PATH}")

        return {
            "accuracy":              accuracy,
            "auc":                   auc,
            "classification_report": report,
            "confusion_matrix":      cm,
        }

    # ── Loading ───────────────────────────────────────────────────────────────

    def load(self) -> None:
        """Load a previously saved model from disk."""
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(
                f"No saved model at {MODEL_PATH}. Run .train() first."
            )
        with open(MODEL_PATH, "rb") as f:
            payload = pickle.load(f)
        self.model = payload["model"]
        print(f"[GigStressClassifier] Model loaded ← {MODEL_PATH}")

    # ── Core inference: single pair ────────────────────────────────────────────

    def predict_pair(
        self,
        prev_week_income: float,
        curr_week_income: float,
    ) -> Dict[str, Any]:
        """
        Predict stress for one (prev_week_income, curr_week_income) transition.

        The drop percentage is computed transparently:
            drop_pct = (prev - curr) / prev × 100

        Returns:
            prev_week_income  : input prev income (₹)
            curr_week_income  : input curr income (₹)
            drop_pct          : income change % (positive = drop, negative = rise)
            stress_probability: model output probability [0.0, 1.0]
            is_stressed       : bool (prob >= 0.50)
            stress_label      : "STRESSED" or "NOT_STRESSED"
        """
        if self.model is None:
            raise RuntimeError("Model not loaded. Call .train() or .load() first.")

        drop_pct = (
            (prev_week_income - curr_week_income) / prev_week_income * 100
            if prev_week_income > 0 else 0.0
        )
        X = np.array([[prev_week_income, curr_week_income]], dtype=float)

        if _HAS_LGB and hasattr(self.model, "predict"):
            prob = float(self.model.predict(X)[0])
        else:
            prob = float(self.model.predict_proba(X)[0, 1])

        is_hard_stress = drop_pct > 50.0
        if is_hard_stress:
            prob = max(prob, 0.95)

        is_stressed = bool(prob >= 0.50) or is_hard_stress

        return {
            "prev_week_income":  prev_week_income,
            "curr_week_income":  curr_week_income,
            "drop_pct":          round(drop_pct, 2),
            "stress_probability": round(prob, 4),
            "is_stressed":       is_stressed,
            "stress_label":      "STRESSED" if is_stressed else "NOT_STRESSED",
        }

    # ── Profile-level inference (iterates all pairs) ─────────────────────────

    def predict_profile(
        self, profile: GigWorkerProfile
    ) -> Dict[str, Any]:
        """
        Run pair-by-pair inference over all consecutive weeks in a profile.

        For each transition (week N-1 → week N):
          • pass (prev_income, curr_income) to predict_pair()
          • record per-week stress flag and probability

        Worker-level summary:
          predicted_stressed = True  if ANY week transition is STRESSED
          stress_probability = max pair probability across all transitions

        Returns dict compatible with gig_realtime_injector expectations:
            worker_id, name, city, platform,
            baseline_weekly_income, stress_probability,
            predicted_stressed, stress_label, actual_stressed,
            max_wow_drop_pct, pair_results (list, one per week transition)
        """
        pair_results: List[Dict[str, Any]] = []
        for i in range(1, len(profile.weekly_payouts)):
            prev_rec = profile.weekly_payouts[i - 1]
            curr_rec = profile.weekly_payouts[i]
            result   = self.predict_pair(
                prev_week_income=float(prev_rec.payout_amount),
                curr_week_income=float(curr_rec.payout_amount),
            )
            result["prev_week_num"] = prev_rec.week_num
            result["curr_week_num"] = curr_rec.week_num
            result["curr_week_label"] = curr_rec.week_label
            pair_results.append(result)

        any_stressed = any(r["is_stressed"] for r in pair_results)
        max_prob     = max((r["stress_probability"] for r in pair_results), default=0.0)
        max_drop     = max((r["drop_pct"] for r in pair_results if r["drop_pct"] > 0), default=0.0)

        return {
            "worker_id":              profile.worker_id,
            "name":                   profile.full_name,
            "city":                   profile.city,
            "platform":               profile.platform_name,
            "baseline_weekly_income": profile.baseline_weekly_income,
            "stress_probability":     round(max_prob, 4),
            "predicted_stressed":     any_stressed,
            "stress_label":           "STRESSED" if any_stressed else "NOT_STRESSED",
            "actual_stressed":        profile.is_stressed,
            "max_wow_drop_pct":       round(max_drop, 1),
            "pair_results":           pair_results,
        }


# ── Demo entry point ──────────────────────────────────────────────────────────

def run_demo() -> None:
    """
    End-to-end demo:
      1. Train on 500 simulated workers (pair-level features)
      2. Run pair-by-pair inference on 5 fresh worker profiles
      3. Print a week-by-week stress table for each worker
    """
    print("=" * 70)
    print("  SENTINEL V2 — Gig Worker Stress Classifier  (pair-level model)")
    print("  Stress criterion: (prev_income - curr_income) / prev_income > 50%")
    print("=" * 70 + "\n")

    clf = GigStressClassifier()
    clf.train(n_workers=500, seed=42)

    print("\n" + "─" * 70)
    print("  Inference on 5 fresh profiles (seed=99) — week-by-week view")
    print("─" * 70)

    test_profiles = simulate_gig_workers(n=5, seed=99)
    for profile in test_profiles:
        pred = clf.predict_profile(profile)
        print(f"\n  Worker: {profile.full_name:<22} | {profile.platform_category:<20} | "
              f"{profile.city:<12} | Baseline Rs{profile.baseline_weekly_income:,.0f}/wk")
        print(f"  {'Wk':>4}  {'Prev Income':>12}  {'Curr Income':>12}  "
              f"{'Drop%':>8}  {'Prob':>6}  Status")
        print("  " + "─" * 66)
        for r in pred["pair_results"]:
            drop_str  = f"{r['drop_pct']:+.1f}%" if r["prev_week_income"] > 0 else "    —"
            status    = "!! STRESSED" if r["is_stressed"] else "OK"
            print(
                f"  W{r['curr_week_num']:02d}  "
                f"Rs{r['prev_week_income']:>10,.0f}  "
                f"Rs{r['curr_week_income']:>10,.0f}  "
                f"{drop_str:>8}  {r['stress_probability']:>5.3f}  {status}"
            )
        verdict = "STRESSED" if pred["predicted_stressed"] else "NOT_STRESSED"
        actual  = "STRESSED" if pred["actual_stressed"] else "NOT_STRESSED"
        match   = "✓" if verdict == actual else "✗"
        print(f"  → Verdict: {verdict}  |  Actual: {actual}  {match}  "
              f"|  Max drop: {pred['max_wow_drop_pct']:+.1f}%")

    print("\n" + "=" * 70)
    print("  Demo complete.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_demo()
