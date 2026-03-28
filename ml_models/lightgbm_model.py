"""
ml_models/lightgbm_model.py
─────────────────────────────────────────────────────────────────────────────
LightGBM wrapper for the PulseScorer.
Input:  48-dimensional delta feature vector
Output: severity probability [0.0, 1.0]
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List, Optional

import numpy as np

from feature_engine.delta_features import DELTA_FEATURE_NAMES

MODEL_DIR = Path(__file__).parent / "saved_models"
MODEL_DIR.mkdir(exist_ok=True)

LGBM_PARAMS: Dict[str, Any] = {
    "objective":         "binary",
    "metric":            ["binary_logloss", "auc"],
    "boosting_type":     "gbdt",
    "learning_rate":     0.05,
    "num_leaves":        31,
    "max_depth":         7,
    "min_child_samples": 40,
    "feature_fraction":  0.75,
    "bagging_fraction":  0.80,
    "bagging_freq":      3,
    "reg_alpha":         0.5,
    "reg_lambda":        0.5,
    "min_gain_to_split": 0.01,
    "max_bin":           255,
    "path_smooth":       0.5,
    "verbose":          -1,
    "n_jobs":           -1,
    "deterministic":     True,
    "seed":              42,
    "is_unbalance":      True,
}


class SentinelLightGBM:

    def __init__(self):
        self.model         = None
        self.feature_names = DELTA_FEATURE_NAMES
        self.model_version = "lgbm_v2.0.0"
        self.n_features    = 48

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val:   np.ndarray,
        y_val:   np.ndarray,
        num_boost_round:      int = 2000,
        early_stopping_rounds:int = 80,
    ) -> Dict[str, Any]:
        import lightgbm as lgb
        from sklearn.metrics import roc_auc_score, average_precision_score

        n_pos = int(np.sum(y_train == 1))
        n_neg = int(np.sum(y_train == 0))
        params = {**LGBM_PARAMS}
        if not params.get("is_unbalance", False):
            params["scale_pos_weight"] = n_neg / max(n_pos, 1)

        dtrain = lgb.Dataset(X_train, label=y_train, feature_name=self.feature_names)
        dval   = lgb.Dataset(X_val,   label=y_val,   feature_name=self.feature_names,
                             reference=dtrain)

        self.model = lgb.train(
            params, dtrain,
            num_boost_round=num_boost_round,
            valid_sets=[dval],
            callbacks=[
                lgb.early_stopping(stopping_rounds=early_stopping_rounds, verbose=False),
                lgb.log_evaluation(period=50),
            ],
        )

        y_pred = self.model.predict(X_val)
        return {
            "auc":            round(float(roc_auc_score(y_val, y_pred)),           4),
            "avg_precision":  round(float(average_precision_score(y_val, y_pred)), 4),
            "best_iteration": self.model.best_iteration,
            "n_train":        len(y_train),
            "n_val":          len(y_val),
            "pos_rate_train": round(float(np.mean(y_train)), 4),
            "scale_pos_weight": round(n_neg / max(n_pos, 1), 2),
        }

    def predict_severity(self, X: np.ndarray) -> np.ndarray:
        """Predict severity [0.0, 1.0] for a batch. X shape: (n, 48)"""
        if self.model is None:
            raise RuntimeError("Model not loaded.")
        X = np.nan_to_num(X.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
        return self.model.predict(X)

    def predict_single(self, x: np.ndarray) -> float:
        """Predict severity for one sample. x shape: (48,)"""
        return float(self.predict_severity(x.reshape(1, -1))[0])

    def get_shap_values(self, X: np.ndarray) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("Model not loaded.")
        import shap
        return shap.TreeExplainer(self.model).shap_values(X)

    def get_feature_importance(self) -> Dict[str, float]:
        if self.model is None:
            return {}
        raw   = self.model.feature_importance(importance_type="gain")
        total = float(np.sum(raw)) or 1.0
        return {n: round(float(v) / total, 6) for n, v in zip(self.feature_names, raw)}

    def save(self) -> None:
        if self.model is None:
            raise RuntimeError("Nothing to save.")
        path = MODEL_DIR / "lgbm_pulse_scorer.txt"
        self.model.save_model(str(path))
        with open(MODEL_DIR / "lgbm_meta.json", "w") as f:
            json.dump({
                "model_version": self.model_version,
                "n_features":    self.n_features,
                "feature_names": self.feature_names,
            }, f, indent=2)
        print(f"  ✓ Model saved → {path}")

    def load(self) -> None:
        import lightgbm as lgb
        path = MODEL_DIR / "lgbm_pulse_scorer.txt"
        if not path.exists():
            raise FileNotFoundError(f"Model not found at {path}. Run training first.")
        self.model = lgb.Booster(model_file=str(path))
        meta_path  = MODEL_DIR / "lgbm_meta.json"
        if meta_path.exists():
            with open(meta_path) as f:
                self.model_version = json.load(f).get("model_version", self.model_version)
        print(f"  ✓ LightGBM loaded ({self.model_version})")

    @property
    def is_loaded(self) -> bool:
        return self.model is not None